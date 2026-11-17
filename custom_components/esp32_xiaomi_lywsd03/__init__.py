"""ESP32 Xiaomi LYWSD03MMC Home Assistant integration."""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .const import (
    ADD_SERVICE,
    AVAILABILITY_TOPIC,
    BIND_KEY_RE,
    COMMAND_RESULT_TOPIC,
    DEVICE_ID_RE,
    DEVICE_IDENTIFIER_NAMESPACE,
    DISCOVERED_TOPIC,
    DOMAIN,
    IDENTITY_TOPIC,
    MAC_RE,
    NAME,
    PLATFORMS,
    REGISTRY_TOPIC,
    REMOVE_SERVICE,
    REQUEST_TIMEOUT,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)
DATA_GATEWAYS = "gateways"
DATA_UNSUB = "unsub"
DATA_PENDING = "pending"
DATA_PENDING_MACS = "pending_macs"
DATA_ADD_ENTITIES = "add_entities"
DATA_ENTITY_IDS = "entity_ids"


def _decode_payload(payload: str | bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("version") != VERSION:
        return None
    return value


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    data: dict[str, Any] = {
        DATA_GATEWAYS: {},
        DATA_UNSUB: [],
        DATA_PENDING: {},
        DATA_PENDING_MACS: {},
        DATA_ADD_ENTITIES: None,
        DATA_ENTITY_IDS: set(),
    }
    hass.data[DOMAIN][entry.entry_id] = data
    signal = f"{DOMAIN}_{entry.entry_id}_update"
    device_registry = dr.async_get(hass)

    def update_gateway(device_id: str, **values: Any) -> None:
        gateway = data[DATA_GATEWAYS].setdefault(
            device_id,
            {
                "id": device_id,
                "name": f"ESP32-{device_id[-6:]}",
                "model": "ESP32",
                "available": False,
                "discovered": set(),
                "registry": set(),
                "last_result": None,
                "pending": [],
            },
        )
        gateway.update(values)
        async_dispatcher_send(hass, signal, device_id)
        callback = data.get(DATA_ADD_ENTITIES)
        if callback and device_id not in data[DATA_ENTITY_IDS]:
            from .sensor import XiaomiGatewaySensor

            data[DATA_ENTITY_IDS].add(device_id)
            callback([XiaomiGatewaySensor(hass, entry, device_id)])

    def register_gateway_device(device_id: str) -> None:
        """Ensure the shared ESP32 device exists, without creating a second entry."""
        device = data[DATA_GATEWAYS][device_id]
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DEVICE_IDENTIFIER_NAMESPACE, device_id)},
            name=device.get("name"),
            manufacturer="Espressif",
            model=device.get("model", "ESP32"),
        )

    async def identity_message(msg: mqtt.ReceiveMessage) -> None:
        payload = _decode_payload(msg.payload)
        if payload is None:
            return
        device_id = str(payload.get("id", "")).upper()
        name = str(payload.get("name", "")).strip()
        model = str(payload.get("model", "ESP32")).strip() or "ESP32"
        if not re.fullmatch(DEVICE_ID_RE, device_id) or not name:
            _LOGGER.warning("Ignoring invalid ESP32 identity message")
            return
        update_gateway(device_id, name=name[:64], model=model[:64])
        register_gateway_device(device_id)

    async def availability_message(msg: mqtt.ReceiveMessage) -> None:
        match = re.fullmatch(r"esp32/([0-9A-Fa-f]{12})/availability", msg.topic)
        if not match:
            return
        state = str(msg.payload).strip().lower()
        if state not in ("online", "offline"):
            return
        device_id = match.group(1).upper()
        if device_id not in data[DATA_GATEWAYS]:
            return
        update_gateway(device_id, available=state == "online")

    async def snapshot_message(msg: mqtt.ReceiveMessage, kind: str) -> None:
        match = re.fullmatch(
            rf"esp32/([0-9A-Fa-f]{{12}})/xiaomi/{kind}", msg.topic
        )
        if not match:
            return
        device_id = match.group(1).upper()
        if device_id not in data[DATA_GATEWAYS]:
            return
        payload = _decode_payload(msg.payload)
        if payload is None or not isinstance(payload.get("sensors"), list):
            _LOGGER.warning("Ignoring invalid Xiaomi %s snapshot from %s", kind, device_id)
            return
        macs: set[str] = set()
        for item in payload["sensors"]:
            if not isinstance(item, dict):
                continue
            mac = str(item.get("mac", "")).upper()
            if re.fullmatch(MAC_RE, mac):
                macs.add(mac)
        update_gateway(device_id, **{kind: macs})

    async def discovered_message(msg: mqtt.ReceiveMessage) -> None:
        await snapshot_message(msg, "discovered")

    async def registry_message(msg: mqtt.ReceiveMessage) -> None:
        await snapshot_message(msg, "registry")

    def finish_pending(device_id: str, request_id: str, result: str) -> None:
        key = (device_id, request_id)
        pending = data[DATA_PENDING].pop(key, None)
        if pending is None:
            return
        cancel = pending.get("cancel")
        if cancel:
            cancel()
        mac = pending["mac"]
        if pending["action"] == "add":
            data[DATA_PENDING_MACS].pop(mac, None)
        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is not None:
            gateway["pending"] = [
                item for item in gateway["pending"] if item["request_id"] != request_id
            ]
            gateway["last_result"] = {
                "action": pending["action"],
                "mac": mac,
                "result": result,
            }
            async_dispatcher_send(hass, signal, device_id)

    async def result_message(msg: mqtt.ReceiveMessage) -> None:
        match = re.fullmatch(
            r"esp32/([0-9A-Fa-f]{12})/xiaomi/command/result", msg.topic
        )
        if not match:
            return
        device_id = match.group(1).upper()
        payload = _decode_payload(msg.payload)
        if payload is None:
            return
        request_id = payload.get("request_id")
        action = payload.get("action")
        result = payload.get("result")
        mac = str(payload.get("mac", "")).upper()
        if (
            not isinstance(request_id, str)
            or action not in ("add", "remove")
            or not isinstance(result, str)
            or not re.fullmatch(MAC_RE, mac)
        ):
            return
        pending = data[DATA_PENDING].get((device_id, request_id))
        if pending is None or pending["action"] != action or pending["mac"] != mac:
            return
        finish_pending(device_id, request_id, result)

    data[DATA_UNSUB] = [
        await mqtt.async_subscribe(hass, IDENTITY_TOPIC, identity_message, qos=1),
        await mqtt.async_subscribe(hass, AVAILABILITY_TOPIC, availability_message, qos=1),
        await mqtt.async_subscribe(hass, DISCOVERED_TOPIC, discovered_message, qos=1),
        await mqtt.async_subscribe(hass, REGISTRY_TOPIC, registry_message, qos=1),
        await mqtt.async_subscribe(hass, COMMAND_RESULT_TOPIC, result_message, qos=1),
    ]
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def ensure_gateway(device_id: str) -> dict[str, Any]:
        if not re.fullmatch(DEVICE_ID_RE, device_id):
            raise HomeAssistantError("Некорректный ID ESP32-шлюза.")
        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is None:
            raise HomeAssistantError(
                "ESP32-шлюз не обнаружен. Проверьте MQTT и публикацию device/info."
            )
        return gateway

    def reserve_operation(
        device_id: str, action: str, mac: str, request_id: str
    ) -> None:
        pending = {
            "action": action,
            "mac": mac,
            "request_id": request_id,
            "cancel": None,
        }
        data[DATA_PENDING][(device_id, request_id)] = pending
        gateway = data[DATA_GATEWAYS][device_id]
        gateway["pending"].append(
            {"action": action, "mac": mac, "request_id": request_id}
        )
        pending["cancel"] = async_call_later(
            hass,
            REQUEST_TIMEOUT,
            lambda _now: finish_pending(device_id, request_id, "timeout"),
        )
        if action == "add":
            data[DATA_PENDING_MACS][mac] = (device_id, request_id)
        async_dispatcher_send(hass, signal, device_id)

    async def handle_add(call: ServiceCall) -> None:
        device_id = str(call.data["device_id"]).upper()
        mac = str(call.data["mac"]).upper()
        bind_key = str(call.data["bind_key"])
        ensure_gateway(device_id)
        if not re.fullmatch(MAC_RE, mac):
            raise HomeAssistantError("MAC должен иметь формат AA:BB:CC:DD:EE:FF.")
        if not re.fullmatch(BIND_KEY_RE, bind_key):
            raise HomeAssistantError("Bind-key должен содержать ровно 32 шестнадцатеричных символа.")
        for other_id, gateway in data[DATA_GATEWAYS].items():
            if mac in gateway["registry"] and other_id != device_id:
                raise HomeAssistantError(
                    f"Датчик {mac} уже сохранён на другом ESP32-шлюзе."
                )
        reservation = data[DATA_PENDING_MACS].get(mac)
        if reservation is not None:
            raise HomeAssistantError("Для этого датчика уже выполняется добавление.")
        gateway = data[DATA_GATEWAYS][device_id]
        if mac in gateway["registry"]:
            raise HomeAssistantError("Датчик уже сохранён на выбранном шлюзе.")
        request_id = uuid.uuid4().hex
        reserve_operation(device_id, "add", mac, request_id)
        command = {
            "version": VERSION,
            "request_id": request_id,
            "mac": mac,
            "bind_key": bind_key,
        }
        try:
            await mqtt.async_publish(
                hass,
                f"esp32/{device_id}/xiaomi/command/add",
                json.dumps(command, separators=(",", ":")),
                qos=1,
                retain=False,
            )
        except Exception:
            finish_pending(device_id, request_id, "publish_error")
            raise
        finally:
            # Do not retain the secret in integration state or logs.
            command.pop("bind_key", None)
            bind_key = ""

    async def handle_remove(call: ServiceCall) -> None:
        device_id = str(call.data["device_id"]).upper()
        mac = str(call.data["mac"]).upper()
        gateway = ensure_gateway(device_id)
        if not re.fullmatch(MAC_RE, mac):
            raise HomeAssistantError("MAC должен иметь формат AA:BB:CC:DD:EE:FF.")
        if mac not in gateway["registry"]:
            raise HomeAssistantError("Датчик не найден в реестре выбранного шлюза.")
        if any(
            pending["action"] == "remove" and pending["mac"] == mac
            for pending in data[DATA_PENDING].values()
        ):
            raise HomeAssistantError("Для этого датчика уже выполняется удаление.")
        request_id = uuid.uuid4().hex
        reserve_operation(device_id, "remove", mac, request_id)
        command = {"version": VERSION, "request_id": request_id, "mac": mac}
        try:
            await mqtt.async_publish(
                hass,
                f"esp32/{device_id}/xiaomi/command/remove",
                json.dumps(command, separators=(",", ":")),
                qos=1,
                retain=False,
            )
        except Exception:
            finish_pending(device_id, request_id, "publish_error")
            raise

    hass.services.async_register(
        DOMAIN,
        ADD_SERVICE,
        handle_add,
        schema=vol.Schema(
            {
                vol.Required("device_id"): str,
                vol.Required("mac"): str,
                vol.Required("bind_key"): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        REMOVE_SERVICE,
        handle_remove,
        schema=vol.Schema(
            {vol.Required("device_id"): str, vol.Required("mac"): str}
        ),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id, {})
    for pending in data.get(DATA_PENDING, {}).values():
        cancel = pending.get("cancel")
        if cancel:
            cancel()
    for unsub in data.get(DATA_UNSUB, []):
        unsub()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.services.async_remove(DOMAIN, ADD_SERVICE)
    hass.services.async_remove(DOMAIN, REMOVE_SERVICE)
    return unload_ok
