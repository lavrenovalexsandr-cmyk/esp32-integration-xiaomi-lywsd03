"""Gateway-level Xiaomi manager state; sensor measurements come from MQTT Discovery."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity

from .const import DEVICE_IDENTIFIER_NAMESPACE, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    data["add_entities"] = async_add_entities
    entities = []
    for device_id in data["gateways"]:
        data["entity_ids"].add(device_id)
        entities.append(XiaomiGatewaySensor(hass, entry, device_id))
    if entities:
        async_add_entities(entities)


class XiaomiGatewaySensor(SensorEntity):
    """Expose gateway snapshot metadata for the Lovelace manager card."""

    _attr_has_entity_name = True
    _attr_translation_key = "xiaomi_sensors"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
        self.hass = hass
        self.entry = entry
        self.device_id = device_id
        self._attr_unique_id = f"{device_id.lower()}_xiaomi_manager"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.entry.entry_id}_update",
                self._handle_update,
            )
        )

    def _handle_update(self, device_id: str) -> None:
        if device_id == self.device_id:
            self.async_write_ha_state()

    @property
    def _gateway(self):
        return self.hass.data[DOMAIN][self.entry.entry_id]["gateways"].get(
            self.device_id, {}
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DEVICE_IDENTIFIER_NAMESPACE, self.device_id)},
            name=self._gateway.get("name", f"ESP32-{self.device_id[-6:]}"),
            manufacturer="Espressif",
            model=self._gateway.get("model", "ESP32"),
        )

    @property
    def native_value(self) -> int:
        return len(self._gateway.get("registry", set()))

    @property
    def extra_state_attributes(self) -> dict:
        gateway = self._gateway
        return {
            "device_id": self.device_id,
            "available": gateway.get("available", False),
            "discovered": sorted(gateway.get("discovered", set())),
            "registry": sorted(gateway.get("registry", set())),
            "pending": gateway.get("pending", []),
            "last_result": gateway.get("last_result"),
        }
