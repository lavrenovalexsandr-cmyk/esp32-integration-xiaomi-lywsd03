"""Home Assistant integration for ESP32 Xiaomi LYWSD03MMC gateways."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

import probatio
import voluptuous as vol
from homeassistant.components import mqtt, websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    AVAILABILITY_TOPIC,
    BIND_KEY_PATTERN,
    COMMAND_TIMEOUT,
    DATA_GATEWAYS,
    DATA_PENDING,
    DATA_PENDING_ADDS,
    DATA_UNSUB,
    DEVICE_ID_PATTERN,
    DEVICE_IDENTIFIER_NAMESPACE,
    DOMAIN,
    EVENT_COMMAND_RESULT,
    EVENT_STATE_UPDATED,
    IDENTITY_TOPIC,
    MAC_PATTERN,
    MAX_REQUEST_ID_LENGTH,
    PROTOCOL_VERSION,
    SERVICE_ADD_SENSOR,
    SERVICE_REMOVE_SENSOR,
    XIAOMI_TOPICS,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_ID_RE = re.compile(DEVICE_ID_PATTERN)
MAC_RE = re.compile(MAC_PATTERN)
BIND_KEY_RE = re.compile(BIND_KEY_PATTERN)

RESULT_MESSAGES = {
    "success": "Операция выполнена.",
    "already_exists": "Датчик уже сохранён на этом шлюзе.",
    "not_found": "Датчик не найден в реестре шлюза.",
    "full": "Реестр датчиков шлюза заполнен.",
    "invalid_argument": "Шлюз отклонил некорректные аргументы.",
    "storage_error": "Шлюз сообщил об ошибке хранилища.",
    "busy": "Компонент Xiaomi на шлюзе занят. Повторите попытку позже.",
    "not_initialized": "Компонент Xiaomi на шлюзе ещё не инициализирован.",
}


def _new_gateway(device_id: str) -> dict[str, Any]:
    """Return an empty in-memory state for a gateway."""
    return {
        "device_id": device_id,
        "name": f"ESP32-{device_id[-6:]}",
        "model": "ESP32",
        "available": False,
        "identity_received": False,
        "discovered": {},
        "registry": set(),
        "registry_received": False,
        "registry_revision": 0,
        "discovered_received": False,
    }


def _gateway_state(data: dict[str, Any], device_id: str) -> dict[str, Any]:
    """Get or create a gateway state record."""
    return data[DATA_GATEWAYS].setdefault(device_id, _new_gateway(device_id))


def _fire_state_updated(hass: HomeAssistant, device_id: str) -> None:
    """Notify frontend clients that a gateway snapshot changed."""
    hass.bus.async_fire(EVENT_STATE_UPDATED, {"device_id": device_id})


def _parse_snapshot(payload: str | bytes) -> dict[str, Any] | None:
    """Parse and validate a versioned sensor snapshot."""
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(parsed, dict)
        or type(parsed.get("version")) is not int
        or parsed.get("version") != PROTOCOL_VERSION
        or not isinstance(parsed.get("sensors"), list)
    ):
        return None
    return parsed


@websocket_api.websocket_command(
    {probatio.Required("type"): f"{DOMAIN}/get_state"}
)
@websocket_api.async_response
async def websocket_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return gateway snapshots to the Xiaomi Sensor Manager card."""
    entries = hass.data.get(DOMAIN, {})
    data = next(
        (value for key, value in entries.items() if not key.startswith("_")),
        None,
    )
    gateways = []
    if data is not None:
        for gateway in data[DATA_GATEWAYS].values():
            if not gateway["identity_received"]:
                continue
            gateways.append(
                {
                    "device_id": gateway["device_id"],
                    "name": gateway["name"],
                    "model": gateway["model"],
                    "available": gateway["available"],
                    "identity_received": gateway["identity_received"],
                    "registry_received": gateway["registry_received"],
                    "discovered_received": gateway["discovered_received"],
                    "discovered": sorted(
                        gateway["discovered"].values(),
                        key=lambda item: item["mac"],
                    ),
                    "registry": sorted(gateway["registry"]),
                }
            )
    connection.send_result(msg["id"], {"gateways": gateways})


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Xiaomi integration entry."""
    data: dict[str, Any] = {
        DATA_GATEWAYS: {},
        DATA_UNSUB: [],
        DATA_PENDING: {},
        DATA_PENDING_ADDS: {},
        "entry": entry,
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data
    device_registry = dr.async_get(hass)

    async def ensure_gateway(device_id: str) -> dict[str, Any]:
        """Register the shared ESP32 device and return its runtime state."""
        return _gateway_state(data, device_id)

    async def identity_message(msg: mqtt.ReceiveMessage) -> None:
        """Handle the Platform Core gateway identity."""
        match = re.fullmatch(r"esp32/([0-9A-Fa-f]{12})/device/info", msg.topic)
        if not match:
            return
        topic_id = match.group(1).upper()
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Ignoring invalid ESP32 identity payload")
            return
        if not isinstance(payload, dict):
            return
        device_id = str(payload.get("id", "")).upper()
        name = str(payload.get("name", "")).strip()
        model = str(payload.get("model", "ESP32")).strip()
        if (
            device_id != topic_id
            or not DEVICE_ID_RE.fullmatch(device_id)
            or not name
        ):
            _LOGGER.warning("Ignoring invalid ESP32 identity message")
            return
        gateway = await ensure_gateway(device_id)
        gateway["identity_received"] = True
        gateway["name"] = name[:64]
        gateway["model"] = (model or "ESP32")[:64]
        # Refresh the shared registry entry with the identity fields.
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DEVICE_IDENTIFIER_NAMESPACE, device_id)},
            name=gateway["name"],
            model=gateway["model"],
            manufacturer="Espressif",
        )
        _fire_state_updated(hass, device_id)

    async def availability_message(msg: mqtt.ReceiveMessage) -> None:
        """Track gateway availability independently of esp32_ota."""
        match = re.fullmatch(r"esp32/([0-9A-Fa-f]{12})/availability", msg.topic)
        if not match:
            return
        payload = str(msg.payload).strip().lower()
        if payload not in ("online", "offline"):
            _LOGGER.warning("Ignoring invalid ESP32 availability payload")
            return
        device_id = match.group(1).upper()
        gateway = await ensure_gateway(device_id)
        gateway["available"] = payload == "online"
        _fire_state_updated(hass, device_id)

    async def xiaomi_message(msg: mqtt.ReceiveMessage) -> None:
        """Process retained snapshots and command results for every gateway."""
        match = re.fullmatch(
            r"esp32/([0-9A-Fa-f]{12})/xiaomi/(discovered|registry|command/result)",
            msg.topic,
        )
        if not match:
            return
        device_id = match.group(1).upper()
        message_type = match.group(2)
        gateway = await ensure_gateway(device_id)

        if message_type in ("discovered", "registry"):
            snapshot = _parse_snapshot(msg.payload)
            if snapshot is None:
                _LOGGER.warning(
                    "Ignoring invalid Xiaomi %s snapshot from ESP32 %s",
                    message_type,
                    device_id,
                )
                return
            sensors: dict[str, dict[str, Any]] = {}
            registry: set[str] = set()
            for item in snapshot["sensors"][:64]:
                if not isinstance(item, dict):
                    continue
                mac = str(item.get("mac", "")).upper()
                if not MAC_RE.fullmatch(mac):
                    continue
                if message_type == "registry":
                    registry.add(mac)
                else:
                    sensor: dict[str, Any] = {"mac": mac}
                    rssi = item.get("rssi")
                    if isinstance(rssi, int) and not isinstance(rssi, bool):
                        sensor["rssi"] = max(-127, min(20, rssi))
                    sensors[mac] = sensor
            if message_type == "registry":
                gateway["registry"] = registry
                gateway["registry_received"] = True
                gateway["registry_revision"] += 1
                for reserved_mac, reservation in list(data[DATA_PENDING_ADDS].items()):
                    if reserved_mac in registry or (
                        reservation["device_id"] == device_id
                        and reservation["state"] == "uncertain"
                    ) or (
                        reservation["device_id"] == device_id
                        and reservation["state"] == "awaiting_registry"
                        and reservation["registry_revision"] < gateway["registry_revision"]
                    ):
                        data[DATA_PENDING_ADDS].pop(reserved_mac, None)
            else:
                gateway["discovered"] = sensors
                gateway["discovered_received"] = True
            _fire_state_updated(hass, device_id)
            return

        try:
            result = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Ignoring invalid Xiaomi command result from ESP32 %s", device_id)
            return
        if (
            not isinstance(result, dict)
            or type(result.get("version")) is not int
            or result.get("version") != PROTOCOL_VERSION
        ):
            return
        request_id = result.get("request_id")
        action = result.get("action")
        mac = str(result.get("mac", "")).upper()
        status = result.get("result")
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > MAX_REQUEST_ID_LENGTH
            or not isinstance(action, str)
            or action not in ("add", "remove")
            or not MAC_RE.fullmatch(mac)
            or not isinstance(status, str)
            or status not in RESULT_MESSAGES
        ):
            _LOGGER.warning("Ignoring malformed Xiaomi command result from ESP32 %s", device_id)
            return
        pending = data[DATA_PENDING].get((device_id, request_id))
        if pending is not None:
            if pending["action"] != action or pending["mac"] != mac:
                _LOGGER.warning(
                    "Ignoring mismatched Xiaomi command result from ESP32 %s",
                    device_id,
                )
                return
            if not pending["future"].done():
                pending["future"].set_result(status)
        hass.bus.async_fire(
            EVENT_COMMAND_RESULT,
            {
                "device_id": device_id,
                "request_id": request_id,
                "action": action,
                "mac": mac,
                "result": status,
            },
        )

    data[DATA_UNSUB] = [
        await mqtt.async_subscribe(hass, IDENTITY_TOPIC, identity_message, qos=1),
        await mqtt.async_subscribe(hass, AVAILABILITY_TOPIC, availability_message, qos=1),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[0], xiaomi_message, qos=1),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[1], xiaomi_message, qos=1),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[2], xiaomi_message, qos=1),
    ]

    async def send_command(
        action: str,
        device_id_value: str,
        mac_value: str,
        bind_key: str | None = None,
    ) -> None:
        """Publish one command and wait for its correlated result."""
        device_id = device_id_value.strip().upper()
        mac = mac_value.strip().upper()
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise HomeAssistantError("Некорректный ID ESP32.")
        if not MAC_RE.fullmatch(mac):
            raise HomeAssistantError("Укажите MAC датчика в формате AA:BB:CC:DD:EE:FF.")
        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is None or not gateway["identity_received"]:
            raise HomeAssistantError(
                "ESP32 не обнаружена по MQTT identity. Проверьте MQTT и подключение шлюза."
            )
        if action == "add":
            if not isinstance(bind_key, str) or not BIND_KEY_RE.fullmatch(bind_key):
                raise HomeAssistantError("Bind-key должен содержать ровно 32 hex-символа.")
            if mac in data[DATA_PENDING_ADDS]:
                raise HomeAssistantError(
                    "Добавление этого MAC уже выполняется или ожидает синхронизации реестра."
                )
            unsynchronized = [
                item["device_id"]
                for item in data[DATA_GATEWAYS].values()
                if item["identity_received"] and not item["registry_received"]
            ]
            if unsynchronized:
                raise HomeAssistantError(
                    "Реестры всех известных ESP32 ещё не синхронизированы. "
                    "Дождитесь retained snapshots и повторите попытку."
                )
            owner = next(
                (
                    item["device_id"]
                    for item in data[DATA_GATEWAYS].values()
                    if item["identity_received"] and mac in item["registry"]
                ),
                None,
            )
            if owner is not None:
                raise HomeAssistantError(
                    f"Датчик {mac} уже сохранён на шлюзе {owner}."
                )
            data[DATA_PENDING_ADDS][mac] = {
                "device_id": device_id,
                "state": "pending",
                "registry_revision": gateway["registry_revision"],
            }

        keep_add_reservation = False
        request_id = uuid.uuid4().hex
        future: asyncio.Future[str] = hass.loop.create_future()
        pending_key = (device_id, request_id)
        data[DATA_PENDING][pending_key] = {
            "future": future,
            "action": action,
            "mac": mac,
        }
        command: dict[str, Any] = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "mac": mac,
        }
        if action == "add":
            command["bind_key"] = bind_key
        topic = f"esp32/{device_id}/xiaomi/command/{action}"
        try:
            await mqtt.async_publish(
                hass,
                topic,
                json.dumps(command, separators=(",", ":")),
                qos=1,
                retain=False,
            )
            # Do not retain the command or bind-key in integration state.
            command.clear()
            status = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            if status == "success" and action == "add":
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    reservation["state"] = "awaiting_registry"
                    reservation["registry_revision"] = gateway["registry_revision"]
                    keep_add_reservation = True
            elif status != "success":
                raise HomeAssistantError(RESULT_MESSAGES[status])
        except asyncio.TimeoutError as err:
            if action == "add":
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    reservation["state"] = "uncertain"
                    keep_add_reservation = True
            raise HomeAssistantError(
                "Шлюз не подтвердил команду за отведённое время. "
                "Дождитесь синхронизации retained registry перед повторной попыткой."
            ) from err
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError("Не удалось отправить команду ESP32 через MQTT.") from err
        finally:
            data[DATA_PENDING].pop(pending_key, None)
            if action == "add" and not keep_add_reservation:
                data[DATA_PENDING_ADDS].pop(mac, None)
            if not future.done():
                future.cancel()

    async def handle_add_sensor(call: ServiceCall) -> None:
        """Handle add_sensor service calls."""
        await send_command(
            "add",
            str(call.data["device_id"]),
            str(call.data["mac"]),
            str(call.data["bind_key"]),
        )

    async def handle_remove_sensor(call: ServiceCall) -> None:
        """Handle remove_sensor service calls."""
        await send_command(
            "remove",
            str(call.data["device_id"]),
            str(call.data["mac"]),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_SENSOR,
        handle_add_sensor,
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
        SERVICE_REMOVE_SENSOR,
        handle_remove_sensor,
        schema=vol.Schema(
            {
                vol.Required("device_id"): str,
                vol.Required("mac"): str,
            }
        ),
    )

    if not hass.data[DOMAIN].get("_websocket_registered"):
        websocket_api.async_register_command(hass, websocket_get_state)
        hass.data[DOMAIN]["_websocket_registered"] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration entry."""
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    for unsubscribe in data.get(DATA_UNSUB, []):
        unsubscribe()
    for pending in data.get(DATA_PENDING, {}).values():
        future = pending["future"]
        if not future.done():
            future.cancel()
    hass.services.async_remove(DOMAIN, SERVICE_ADD_SENSOR)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE_SENSOR)
    return True
