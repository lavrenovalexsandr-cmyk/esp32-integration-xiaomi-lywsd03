"""Dynamic Xiaomi LYWSD03MMC measurement entities."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DATA_ADD_ENTITIES,
    DATA_GATEWAYS,
    DATA_MEASUREMENTS,
    DATA_SENSOR_ENTITIES,
    DEVICE_IDENTIFIER_NAMESPACE,
    DOMAIN,
    XIAOMI_DEVICE_IDENTIFIER_NAMESPACE,
)

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


def _compact_mac(mac: str) -> str:
    return mac.replace(":", "")


def _sensor_device_id(device_id: str, mac: str) -> str:
    return f"{device_id}_{_compact_mac(mac)}"


class XiaomiMeasurementSensor(SensorEntity):
    """A measurement entity belonging to one saved Xiaomi sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        data: dict[str, Any],
        device_id: str,
        mac: str,
        description: SensorEntityDescription,
    ) -> None:
        self.entity_description = description
        self._data = data
        self._device_id = device_id
        self._mac = mac
        self._attr_unique_id = (
            f"{device_id}_{_compact_mac(mac)}_{description.key}"
        )

    @property
    def device_info(self) -> dr.DeviceInfo:
        """Return the Xiaomi child device linked to its ESP32 gateway."""
        return dr.DeviceInfo(
            identifiers={
                (
                    XIAOMI_DEVICE_IDENTIFIER_NAMESPACE,
                    _sensor_device_id(self._device_id, self._mac),
                )
            },
            name=f"Xiaomi LYWSD03MMC {self._mac}",
            manufacturer="Xiaomi",
            model="LYWSD03MMC",
            via_device=(DEVICE_IDENTIFIER_NAMESPACE, self._device_id),
        )

    @property
    def available(self) -> bool:
        """Follow the parent ESP32 gateway availability."""
        gateway = self._data[DATA_GATEWAYS].get(self._device_id)
        return bool(gateway and gateway["available"])

    @property
    def native_value(self) -> StateType:
        """Return the latest retained measurement, if known."""
        state = self._data[DATA_MEASUREMENTS].get(
            (self._device_id, self._mac), {}
        )
        value = state.get(self.entity_description.key)
        return value if isinstance(value, (int, float)) else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the dynamic Xiaomi sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    data[DATA_ADD_ENTITIES] = async_add_entities

    for device_id in tuple(data[DATA_GATEWAYS]):
        async_reconcile_gateway(hass, entry, data, device_id)


@callback
def async_reconcile_gateway(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
    device_id: str,
) -> None:
    """Create and remove measurement entities to match a gateway registry."""
    gateway = data[DATA_GATEWAYS].get(device_id)
    add_entities: AddEntitiesCallback | None = data.get(DATA_ADD_ENTITIES)
    if (
        gateway is None
        or not gateway["identity_received"]
        or not gateway["registry_received"]
        or add_entities is None
    ):
        return

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    desired_macs: set[str] = gateway["registry"]
    tracked: dict[tuple[str, str], list[XiaomiMeasurementSensor]] = data[
        DATA_SENSOR_ENTITIES
    ]

    for key in tuple(tracked):
        tracked_device_id, mac = key
        if tracked_device_id != device_id or mac in desired_macs:
            continue
        prefix = f"{device_id}_{_compact_mac(mac)}_"
        for registry_entry in tuple(entity_registry.entities.values()):
            if (
                registry_entry.config_entry_id == entry.entry_id
                and registry_entry.platform == DOMAIN
                and registry_entry.unique_id.startswith(prefix)
            ):
                entity_registry.async_remove(registry_entry.entity_id)
        child = device_registry.async_get_device(
            {
                (
                    XIAOMI_DEVICE_IDENTIFIER_NAMESPACE,
                    _sensor_device_id(device_id, mac),
                )
            }
        )
        if child is not None:
            device_registry.async_remove_device(child.id)
        tracked.pop(key, None)

    for mac in sorted(desired_macs):
        key = (device_id, mac)
        if key in tracked:
            continue
        entities = [
            XiaomiMeasurementSensor(data, device_id, mac, description)
            for description in SENSOR_DESCRIPTIONS
        ]
        tracked[key] = entities
        add_entities(entities)


@callback
def async_write_sensor_state(
    data: dict[str, Any], device_id: str, mac: str
) -> None:
    """Write updated measurement or availability state to loaded entities."""
    for entity in data[DATA_SENSOR_ENTITIES].get((device_id, mac), []):
        if entity.hass is not None:
            entity.async_write_ha_state()
