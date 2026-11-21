"""Home Assistant integration for ESP32 Xiaomi Sensor Manager."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import uuid
import time
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, mqtt, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    BIND_KEY_PATTERN,
    COMMAND_TIMEOUT,
    DATA_ADD_ENTITIES,
    DATA_GATEWAYS,
    DATA_MEASUREMENTS,
    DATA_PENDING,
    DATA_PENDING_ADDS,
    DATA_REMOVED_SENSORS,
    DATA_SENSOR_ENTITIES,
    DATA_UNSUB,
    DEVICE_ID_PATTERN,
    DOMAIN,
    EVENT_COMMAND_RESULT,
    EVENT_STATE_UPDATED,
    MEASUREMENTS_TOPIC,
    MAC_PATTERN,
    MAX_SENSORS_PER_GATEWAY,
    MAX_REQUEST_ID_LENGTH,
    PROTOCOL_VERSION,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
    PANEL_WEB_COMPONENT,
    SERVICE_ADD_SENSOR,
    SERVICE_REMOVE_SENSOR,
    XIAOMI_TOPICS,
    ESP32_MANAGER_DOMAIN,
    ESP32_MANAGER_API_VERSION,
    ESP32_MANAGER_EVENT_ADDED,
    ESP32_MANAGER_EVENT_UPDATED,
)
from .sensor import async_reconcile_gateway, async_write_sensor_state

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


def _profile_matches_gateway(gateway: dict[str, Any], profile: Any) -> bool:
    """Return whether a product profile is valid for this Xiaomi integration."""
    if not isinstance(profile, dict):
        return False
    capabilities = profile.get("capabilities")
    firmware_version = profile.get("firmware_version")
    return (
        type(profile.get("schema_version")) is int
        and profile["schema_version"] == 1
        and profile.get("product_id") == "xiaomi_ble_gateway"
        and isinstance(firmware_version, str)
        and bool(firmware_version)
        and firmware_version == gateway.get("sw_version")
        and isinstance(capabilities, list)
        and all(isinstance(item, str) for item in capabilities)
        and "xiaomi_lywsd03" in capabilities
    )


def _new_gateway(device_id: str) -> dict[str, Any]:
    """Return an empty in-memory state for a gateway."""
    return {
        "device_id": device_id,
        "name": f"ESP32-{device_id[-6:]}",
        "model": "ESP32",
        "name_by_user": None,
        "sw_version": None,
        "available": False,
        "availability_received": False,
        "identity_received": False,
        "profile_valid": False,
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
    {vol.Required("type"): f"{DOMAIN}/get_state"}
)
@websocket_api.async_response
async def websocket_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return gateway snapshots to the Xiaomi Sensor Manager panel."""
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
            # Resolve the current user-assigned name from the central API so
            # Home Assistant renames are reflected without waiting for MQTT.
            manager_api = data.get("manager_api")
            manager_device = (
                manager_api["get_device"](gateway["device_id"])
                if manager_api is not None else None
            )
            display_name = (
                manager_device.get("name_by_user")
                if manager_device and manager_device.get("name_by_user")
                else gateway["name"]
            )
            gateways.append(
                {
                    "device_id": gateway["device_id"],
                    "name": display_name,
                    "model": gateway["model"],
                    "available": gateway["available"],
                    "availability_received": gateway["availability_received"],
                    "identity_received": gateway["identity_received"],
                    "registry_received": gateway["registry_received"],
                    "discovered_received": gateway["discovered_received"],
                    "discovered": sorted(
                        gateway["discovered"].values(),
                        key=lambda item: item["mac"],
                    ),
                    "registry": sorted(gateway["registry"]),
                    "sensor_last_seen": {
                        mac: seen
                        for (gateway_id, mac), seen in data["last_measurements"].items()
                        if gateway_id == gateway["device_id"]
                    },
                }
            )
    connection.send_result(msg["id"], {"gateways": gateways})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Xiaomi integration entry."""
    manager_api = hass.data.get(ESP32_MANAGER_DOMAIN, {}).get("api")
    if not isinstance(manager_api, dict) or manager_api.get("version") != ESP32_MANAGER_API_VERSION:
        raise ConfigEntryNotReady(
            "ESP32 Manager is not configured or its public API version is unsupported."
        )

    removed_store = Store(
        hass, 1, f"{DOMAIN}_{entry.entry_id}_removed_sensors"
    )
    stored_removed = await removed_store.async_load()
    removed_sensors: set[tuple[str, str]] = set()
    if isinstance(stored_removed, dict):
        for item in stored_removed.get("sensors", []):
            if not isinstance(item, dict):
                continue
            device_id = str(item.get("device_id", "")).upper()
            mac = str(item.get("mac", "")).upper()
            if DEVICE_ID_RE.fullmatch(device_id) and MAC_RE.fullmatch(mac):
                removed_sensors.add((device_id, mac))

    data: dict[str, Any] = {
        DATA_GATEWAYS: {},
        DATA_UNSUB: [],
        "manager_api": manager_api,
        DATA_PENDING: {},
        DATA_PENDING_ADDS: {},
        DATA_REMOVED_SENSORS: removed_sensors,
        "entry": entry,
        DATA_MEASUREMENTS: {},
        "last_measurements": {},
        DATA_SENSOR_ENTITIES: {},
        DATA_ADD_ENTITIES: None,
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    async def save_removed_sensors() -> None:
        """Persist local removals so retained MQTT state cannot restore them."""
        await removed_store.async_save(
            {
                "sensors": [
                    {"device_id": gateway_id, "mac": mac}
                    for gateway_id, mac in sorted(data[DATA_REMOVED_SENSORS])
                ]
            }
        )

    def ensure_gateway(device_id: str) -> dict[str, Any]:
        """Return the runtime state for one gateway."""
        return _gateway_state(data, device_id)

    @callback
    def sync_gateway_from_manager(snapshot: dict[str, Any]) -> None:
        """Project central ESP32 Manager metadata into the Xiaomi runtime view."""
        device_id = str(snapshot.get("device_id", "")).upper()
        if not DEVICE_ID_RE.fullmatch(device_id):
            return
        gateway = ensure_gateway(device_id)
        was_valid = gateway["profile_valid"]
        was_available = gateway["available"]
        gateway["identity_received"] = True
        gateway["name"] = str(snapshot.get("name") or f"ESP32-{device_id[-6:]}")[:64]
        gateway["name_by_user"] = (
            str(snapshot["name_by_user"])[:64]
            if isinstance(snapshot.get("name_by_user"), str) and snapshot["name_by_user"].strip()
            else None
        )
        gateway["model"] = str(snapshot.get("model") or "ESP32")[:64]
        gateway["sw_version"] = (
            str(snapshot["sw_version"])[:64]
            if isinstance(snapshot.get("sw_version"), str) and snapshot["sw_version"].strip()
            else None
        )
        gateway["available"] = bool(snapshot.get("available", False))
        gateway["availability_received"] = bool(snapshot.get("availability_received", False))
        gateway["profile_valid"] = _profile_matches_gateway(gateway, snapshot.get("profile"))
        if not gateway["available"]:
            gateway["discovered"] = {}
            gateway["discovered_received"] = False
            for sensor_key in tuple(data["last_measurements"]):
                if sensor_key[0] == device_id:
                    data["last_measurements"].pop(sensor_key, None)
        if gateway["profile_valid"]:
            async_reconcile_gateway(hass, entry, data, device_id)
        if was_valid != gateway["profile_valid"] or was_available != gateway["available"]:
            for (sensor_gateway_id, mac) in tuple(data[DATA_SENSOR_ENTITIES]):
                if sensor_gateway_id == device_id:
                    async_write_sensor_state(data, device_id, mac)
        _fire_state_updated(hass, device_id)

    @callback
    def manager_device_event(event) -> None:
        """Apply a device snapshot event emitted by ESP32 Manager."""
        snapshot = event.data.get("device")
        if isinstance(snapshot, dict):
            sync_gateway_from_manager(snapshot)

    async def remove_gateway_data(device_id_value: str) -> None:
        """Remove all Xiaomi-owned state for one ESP32 gateway."""
        device_id = str(device_id_value).upper()
        if not DEVICE_ID_RE.fullmatch(device_id):
            return
        gateway = data[DATA_GATEWAYS].get(device_id)
        macs: set[str] = set()
        if gateway is not None:
            macs.update(gateway["registry"])
            macs.update(gateway["discovered"])
        for collection in (DATA_MEASUREMENTS, "last_measurements"):
            macs.update(mac for (gateway_id, mac) in data[collection] if gateway_id == device_id)
        macs.update(mac for gateway_id, mac in data[DATA_REMOVED_SENSORS] if gateway_id == device_id)
        macs.update(mac for gateway_id, mac in data[DATA_SENSOR_ENTITIES] if gateway_id == device_id)

        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        unique_id_pattern = re.compile(
            rf"^{re.escape(device_id)}_([0-9A-F]{{12}})_(temperature|humidity|battery)$"
        )
        for registry_entry in tuple(entity_registry.entities.values()):
            if registry_entry.config_entry_id != entry.entry_id or registry_entry.platform != DOMAIN:
                continue
            match = unique_id_pattern.fullmatch(registry_entry.unique_id)
            if match is None:
                continue
            compact_mac = match.group(1)
            mac = ":".join(compact_mac[index:index + 2] for index in range(0, 12, 2))
            macs.add(mac)
            entity_registry.async_remove(registry_entry.entity_id)

        topics = [
            f"esp32/{device_id}/xiaomi/discovered",
            f"esp32/{device_id}/xiaomi/registry",
        ]
        topics.extend(f"esp32/{device_id}/xiaomi/sensor/{mac}/state" for mac in macs)
        for topic in topics:
            try:
                await mqtt.async_publish(hass, topic, "", qos=1, retain=True)
            except Exception:
                _LOGGER.warning(
                    "Unable to clear retained Xiaomi topic %s during ESP32 removal",
                    topic, exc_info=True,
                )

        for mac in macs:
            compact_mac = mac.replace(":", "")
            child = device_registry.async_get_device(
                identifiers={(DOMAIN, f"{device_id}_{compact_mac}")}
            )
            if child is not None:
                device_registry.async_remove_device(child.id)

        for collection in (DATA_MEASUREMENTS, "last_measurements", DATA_SENSOR_ENTITIES):
            for key in tuple(data[collection]):
                if key[0] == device_id:
                    data[collection].pop(key, None)
        removed_changed = False
        for key in tuple(data[DATA_REMOVED_SENSORS]):
            if key[0] == device_id:
                data[DATA_REMOVED_SENSORS].discard(key)
                removed_changed = True
        if removed_changed:
            await save_removed_sensors()

        for key, pending in tuple(data[DATA_PENDING].items()):
            if key[0] == device_id:
                future = pending["future"]
                if not future.done():
                    future.cancel()
                data[DATA_PENDING].pop(key, None)
        for mac, reservation in tuple(data[DATA_PENDING_ADDS].items()):
            if reservation.get("device_id") == device_id:
                data[DATA_PENDING_ADDS].pop(mac, None)

        data[DATA_GATEWAYS].pop(device_id, None)
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
        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is None or not gateway["identity_received"]:
            return

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
                # A gateway may publish a retained snapshot from before a local
                # deletion. Keep that sensor hidden until the gateway confirms
                # that its own registry no longer contains it.
                removed = data[DATA_REMOVED_SENSORS]
                confirmed_removed = {
                    item for item in removed
                    if item[0] == device_id and item[1] not in registry
                }
                if confirmed_removed:
                    removed.difference_update(confirmed_removed)
                    await save_removed_sensors()
                gateway["registry"] = {
                    mac for mac in registry
                    if (device_id, mac) not in removed
                }
                gateway["registry_received"] = True
                gateway["registry_revision"] += 1
                for reserved_mac, reservation in list(data[DATA_PENDING_ADDS].items()):
                    if reservation["device_id"] == device_id and (
                        reserved_mac in registry
                        or (
                            reservation["state"] == "awaiting_registry"
                            and reservation["registry_revision"] < gateway["registry_revision"]
                        )
                    ):
                        data[DATA_PENDING_ADDS].pop(reserved_mac, None)
            else:
                gateway["discovered"] = sensors
                gateway["discovered_received"] = True
            if message_type == "registry":
                async_reconcile_gateway(hass, entry, data, device_id)
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

    async def measurement_message(msg: mqtt.ReceiveMessage) -> None:
        """Cache and distribute retained measurements from a saved sensor."""
        match = re.fullmatch(
            r"esp32/([0-9A-Fa-f]{12})/xiaomi/sensor/([0-9A-Fa-f:]{17})/state",
            msg.topic,
        )
        if not match:
            return
        device_id = match.group(1).upper()
        mac = match.group(2).upper()
        if not MAC_RE.fullmatch(mac):
            return
        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is None or not gateway["identity_received"]:
            return
        key = (device_id, mac)
        if key in data[DATA_REMOVED_SENSORS]:
            # Ignore stale retained or live measurements from a locally removed
            # sensor while its gateway has not yet confirmed registry cleanup.
            return
        if not msg.payload:
            data[DATA_MEASUREMENTS].pop(key, None)
            data["last_measurements"].pop(key, None)
            async_write_sensor_state(data, device_id, mac)
            _fire_state_updated(hass, device_id)
            return
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Ignoring invalid Xiaomi measurement payload from ESP32 %s", device_id)
            return
        if (
            not isinstance(payload, dict)
            or type(payload.get("version")) is not int
            or payload.get("version") != PROTOCOL_VERSION
        ):
            _LOGGER.warning("Ignoring unsupported Xiaomi measurement payload from ESP32 %s", device_id)
            return

        existing = data[DATA_MEASUREMENTS].get(key)
        if existing is None and sum(
            sensor_key[0] == device_id for sensor_key in data[DATA_MEASUREMENTS]
        ) >= MAX_SENSORS_PER_GATEWAY:
            _LOGGER.warning(
                "Ignoring Xiaomi measurement beyond the %s-sensor cache limit for ESP32 %s",
                MAX_SENSORS_PER_GATEWAY,
                device_id,
            )
            return

        values: dict[str, int | float] = dict(existing or {})
        temperature = payload.get("temperature")
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            try:
                if math.isfinite(float(temperature)):
                    values["temperature"] = temperature
            except (OverflowError, ValueError):
                pass
        humidity = payload.get("humidity")
        if (
            isinstance(humidity, (int, float))
            and not isinstance(humidity, bool)
            and 0 <= humidity <= 100
        ):
            try:
                if math.isfinite(float(humidity)):
                    values["humidity"] = humidity
            except (OverflowError, ValueError):
                pass
        battery = payload.get("battery")
        if type(battery) is int and 0 <= battery <= 100:
            values["battery"] = battery

        data[DATA_MEASUREMENTS][key] = values
        # Retained MQTT state is useful for restoring sensor values, but it
        # does not prove that the BLE sensor is currently reachable.
        if not msg.retain:
            data["last_measurements"][key] = time.time()
        async_write_sensor_state(data, device_id, mac)
        _fire_state_updated(hass, device_id)

    # Seed from the central registry. ESP32 Manager exclusively owns
    # common identity/profile/availability MQTT subscriptions.
    for snapshot in manager_api["get_devices"]():
        sync_gateway_from_manager(snapshot)

    data[DATA_UNSUB] = [
        hass.bus.async_listen(ESP32_MANAGER_EVENT_ADDED, manager_device_event),
        hass.bus.async_listen(ESP32_MANAGER_EVENT_UPDATED, manager_device_event),
        manager_api["register_remove_handler"](DOMAIN, remove_gateway_data),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[0], xiaomi_message, qos=1),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[1], xiaomi_message, qos=1),
        await mqtt.async_subscribe(hass, XIAOMI_TOPICS[2], xiaomi_message, qos=1),
        await mqtt.async_subscribe(hass, MEASUREMENTS_TOPIC, measurement_message, qos=1),
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
            existing_reservation = data[DATA_PENDING_ADDS].get(mac)
            if existing_reservation is not None and (
                existing_reservation["device_id"] != device_id
                or existing_reservation["state"] not in ("uncertain", "awaiting_registry")
            ):
                raise HomeAssistantError(
                    "Для этого датчика уже выполняется добавление или ожидается синхронизация реестра."
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
        published = False
        command_completed = False
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
            published = True
            # Do not retain the command or bind-key in integration state.
            command.clear()
            status = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
            command_completed = True
            if action == "add" and status in ("success", "already_exists"):
                # Explicitly adding the sensor again on this gateway cancels its
                # local tombstone. Tombstones for other gateways remain intact.
                removed_key = (device_id, mac)
                if removed_key in data[DATA_REMOVED_SENSORS]:
                    data[DATA_REMOVED_SENSORS].discard(removed_key)
                    await save_removed_sensors()
                gateway["registry"].add(mac)
                async_reconcile_gateway(hass, entry, data, device_id)
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    if mac in gateway["registry"]:
                        data[DATA_PENDING_ADDS].pop(mac, None)
                    else:
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
        except asyncio.CancelledError:
            if action == "add" and published:
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    reservation["state"] = "uncertain"
                    keep_add_reservation = True
            raise
        except HomeAssistantError:
            if action == "add" and published and not command_completed:
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    reservation["state"] = "uncertain"
                    keep_add_reservation = True
            raise
        except Exception as err:
            if action == "add" and published:
                reservation = data[DATA_PENDING_ADDS].get(mac)
                if reservation is not None:
                    reservation["state"] = "uncertain"
                    keep_add_reservation = True
            raise HomeAssistantError("Не удалось отправить команду ESP32 через MQTT.") from err
        finally:
            command.clear()
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

    async def best_effort_remove_from_gateway(
        device_id: str, mac: str
    ) -> None:
        """Try to clean the gateway asynchronously without blocking local removal."""
        try:
            await send_command("remove", device_id, mac)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Local removal of Xiaomi sensor %s from ESP32 %s succeeded, "
                "but gateway cleanup was not confirmed: %s",
                mac,
                device_id,
                err,
            )
        except Exception:
            _LOGGER.exception(
                "Local removal of Xiaomi sensor %s succeeded, "
                "but gateway cleanup failed",
                mac,
            )

    async def handle_remove_sensor(call: ServiceCall) -> None:
        """Remove locally first; gateway cleanup is best-effort."""
        device_id = str(call.data["device_id"]).strip().upper()
        mac = str(call.data["mac"]).strip().upper()
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise HomeAssistantError("Некорректный ID ESP32.")
        if not MAC_RE.fullmatch(mac):
            raise HomeAssistantError(
                "Укажите MAC датчика в формате AA:BB:CC:DD:EE:FF."
            )

        gateway = data[DATA_GATEWAYS].get(device_id)
        if gateway is None or not gateway["identity_received"]:
            raise HomeAssistantError(
                "Шлюз не зарегистрирован в Home Assistant. Удаление невозможно."
            )

        # Persist the tombstone before changing runtime state. If storage fails,
        # leave the sensor untouched so a restart cannot resurrect it.
        removed_key = (device_id, mac)
        data[DATA_REMOVED_SENSORS].add(removed_key)
        try:
            await save_removed_sensors()
        except Exception:
            data[DATA_REMOVED_SENSORS].discard(removed_key)
            raise

        gateway["registry"].discard(mac)
        data[DATA_MEASUREMENTS].pop(removed_key, None)
        data["last_measurements"].pop(removed_key, None)
        async_reconcile_gateway(hass, entry, data, device_id)
        _fire_state_updated(hass, device_id)

        if gateway["available"]:
            hass.async_create_task(best_effort_remove_from_gateway(device_id, mac))

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

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

    if not hass.data[DOMAIN].get("_static_path_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_STATIC_URL,
                    str(Path(__file__).parent / "www" / "xiaomi-panel.js"),
                    cache_headers=False,
                )
            ]
        )
        hass.data[DOMAIN]["_static_path_registered"] = True

    if not hass.data[DOMAIN].get("_panel_registered"):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_WEB_COMPONENT,
            sidebar_title="Xiaomi Sensor Manager",
            sidebar_icon="mdi:bluetooth-connect",
            module_url=f"{PANEL_STATIC_URL}?v=3",
            require_admin=True,
        )
        hass.data[DOMAIN]["_panel_registered"] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration entry."""
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return False
    if hass.data.get(DOMAIN, {}).get("_panel_registered"):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        hass.data[DOMAIN]["_panel_registered"] = False
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
