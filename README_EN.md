# ESP32 Home Assistant Integration — Xiaomi LYWSD03MMC

A dedicated Home Assistant integration for ESP32 gateways with Xiaomi LYWSD03MMC BLE sensors.

> Status: target behavior and architecture decisions are documented. The integration and MQTT protocol will be implemented incrementally; the listed features are plans, not existing functionality.

## Purpose

This integration serves only the ESP32 + Xiaomi LYWSD03MMC ecosystem. Generic ESP32 management (OTA, Restart, Factory Reset and base identity) remains in the universal esp32-integration-core and Platform Core. Xiaomi-specific entities and operations do not belong in the universal integration.

## Target features

- Automatically discover multiple ESP32 gateways.
- Create a separate HA device for each gateway.
- Receive discovered and saved Xiaomi sensor lists from gateways.
- Create a separate HA device for each sensor, with temperature, humidity and battery entities when data is available.
- Support multiple gateways concurrently.
- Provide sensor add/remove services.
- Allow room assignment through native Home Assistant Areas.

## Multi-gateway model

1. Each gateway uses the stable device identity provided by Platform Core.
2. Each gateway is registered as a separate HA device.
3. A sensor is identified by its MAC address and registered as a separate HA device.
4. The sensor device is linked to its gateway using the device registry relationship (via_device), where supported by the selected Discovery model.
5. One gateway can manage multiple sensors; multiple gateways can operate in parallel.
6. Add/remove commands target a specific gateway and are never broadcast.
7. A sensor must not be treated as actively managed by multiple gateways. Conflict handling when multiple gateways see the same MAC will be specified in the MQTT contract.
8. No custom rooms or zones are implemented. Users assign sensors to Areas through Home Assistant.

## Sensor management services

Planned service domain: esp32-component-xiaomi-lywsd03.

- add_sensor — add a sensor to a selected gateway using its MAC and bind-key;
- remove_sensor — remove a sensor from a selected gateway using its MAC.

Preliminary fields:
- gateway_id — Home Assistant gateway device identifier;
- mac — sensor MAC address;
- bind_key — 16-byte key in an agreed text representation.

This is a preliminary interface. Final field names and key representation must be specified in a separate MQTT/API document before implementation. The integration must not store the key in its config entry, registry, diagnostics, events or MQTT state. It forwards the key only in a command message; the ESP32 stores it in NVS.

Removal requires gateway_id and mac. Operation statuses must never reveal the key.

## Discovered and saved sensors

The card needs two data sets:
- Discovered — sensors seen over BLE but not yet added/without a saved key.
- Saved — sensors registered on the gateway, including availability and latest measurements.

Data is scoped to a gateway. The card selects a gateway first and then a sensor, distinguishing discovered and saved states.

## Home Assistant Areas

Room assignment is not sent over MQTT or stored in firmware. Users assign the sensor device to an Area through Home Assistant. Sensors must therefore be created as independent HA devices.

## Security

- Never log bind-keys.
- Never publish keys in state, discovery, attributes, diagnostics or events.
- Never store keys in integration options/config entries.
- Never include keys in errors or service confirmations.
- Validate MAC, key length and representation before sending.
- Route commands using the selected gateway identity.

## MQTT contract

The MQTT v1 contract has been agreed and documented separately: [docs/MQTT_PROTOCOL_EN.md](docs/MQTT_PROTOCOL_EN.md). Russian version: [docs/MQTT_PROTOCOL_RU.md](docs/MQTT_PROTOCOL_RU.md).

The specification defines topics and payloads, retained snapshots of discovered and saved sensors, add/remove commands, command results, measurements, the one-gateway-per-MAC rule, reconnect behavior and current Platform Core limitations. Firmware and Home Assistant integration must be implemented against this contract.

## Lovelace card

The UI lives in [esp32-card](https://github.com/lavrenovalexsandr-cmyk/esp32-card). The Xiaomi Sensor Manager must:
1. allow gateway selection;
2. show discovered and saved sensors for that gateway;
3. provide a bind-key input;
4. provide Add sensor and Remove sensor buttons;
5. call integration services instead of publishing MQTT itself.

Its visual style should match the existing ESP32 cards.

## Implementation stages

1. Agree on the MQTT contract with firmware.
2. Implement the integration foundation and multi-gateway discovery.
3. Implement discovered/saved sensor registries and HA Discovery.
4. Implement add/remove and secure bind-key forwarding.
5. Add diagnostics and offline/reconnect handling.
6. Validate multiple gateways and Area assignment in Home Assistant.

## Related projects

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)
- [ESP32 Lovelace Cards](https://github.com/lavrenovalexsandr-cmyk/esp32-card)

The primary documentation is README.md in Russian. The English version is README_EN.md.
