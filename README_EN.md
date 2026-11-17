# ESP32 Home Assistant Integration — Xiaomi LYWSD03MMC

A dedicated Home Assistant integration for ESP32 gateways with Xiaomi LYWSD03MMC BLE sensors.

> Status: the integration is being migrated to an architecture where the Xiaomi HA integration owns sensor devices and measurement entities. End-to-end verification requires Home Assistant, an MQTT broker and ESP32 firmware.

## HACS installation

1. Open **HACS → Integrations**.
2. Open the top-right menu and select **Custom repositories**.
3. Add `lavrenovalexsandr-cmyk/esp32-integration-xiaomi-lywsd03` with category **Integration**.
4. Find and install **ESP32 Xiaomi LYWSD03MMC**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration** and add **ESP32 Xiaomi LYWSD03MMC**.

Configure the standard Home Assistant **MQTT** integration separately and make sure the broker is connected to the ESP32 gateways. This integration reuses the configured MQTT connection; it does not need broker credentials in its own config flow.

A GitHub Release is not required for installation as a Custom repository: if there are no releases, HACS uses the short hash of the latest commit as the version. For regular versioned updates, publishing a GitHub Release with a tag aligned with `manifest.json` is recommended. You can also test manually by copying `custom_components/esp32_xiaomi_lywsd03` into `config/custom_components/`.

## Home Assistant entities and manager panel

The integration creates a separate Home Assistant device for every saved Xiaomi LYWSD03MMC, with three measurement entities: temperature, humidity and battery. Each sensor device is linked to its ESP32 gateway parent through `via_device`.

The **Xiaomi Sensor Manager** panel is part of this repository and appears in the Home Assistant sidebar after the integration is configured. It is admin-only. No separate Lovelace card or second HACS repository is required.

## Purpose and responsibility boundaries

This integration handles Xiaomi-specific operations and coordination across multiple ESP32 gateways. Generic ESP32 management (OTA, Restart and Factory Reset) remains in the universal `esp32_ota` integration; base gateway identity belongs to Platform Core and the shared MQTT contract.

Responsibilities:

- **Firmware:** BLE discovery, bind-key storage in NVS, registry, commands and command results, retained snapshots and retained MQTT measurements.
- **Platform Core:** shared ESP32 identity and availability, MQTT, and Discovery only for generic gateway entities. Xiaomi entities are not created through Platform Core Discovery.
- **Universal `esp32_ota` integration:** OTA and generic device-control commands; it also uses the shared gateway device entry but is not required by the Xiaomi integration.
- **Shared MQTT contract / Platform Core:** stable gateway identity and its base information.
- **This Xiaomi integration:** MQTT snapshots and measurements, per-gateway state, the one-MAC/one-gateway rule, add/remove services, secure bind-key forwarding, HA device/sensor lifecycle and the manager panel.
- **Xiaomi Sensor Manager panel:** gateway/sensor selection, `New`/`Save` status, add and remove operations through integration services. The panel does not publish MQTT directly or store bind-keys.

## Shared ESP32 gateway identity

The Xiaomi integration is independent of `esp32_ota`: it must not import its code or require it to be installed.

To merge information from different ESP32 integrations into one Home Assistant Device Registry entry, use the shared gateway identifier:

```python
identifiers={("esp32", device_id)}
```

Here, `esp32` is the platform-wide namespace and `device_id` is the stable ID from MQTT identity. The gateway name and model must come from the same MQTT identity fields (`name` and `model`) so integrations expose consistent device information.

**Implementation:** the integration obtains gateway MQTT identity independently and uses `("esp32", device_id)` when registering/enriching the gateway device. It does not use `("esp32_ota", device_id)` or rely on `esp32_ota` being installed. Xiaomi services accept the stable `device_id`.

## Features

- Support multiple ESP32 gateways.
- Receive retained `discovered` and `registry` snapshots separately for each gateway.
- Add and remove sensor services.
- Check that a MAC is not already saved or being added on another known gateway.
- Correlate command results by gateway device ID + `request_id`.
- Handle offline/reconnect and resynchronize from retained snapshots.
- Forward bind-keys securely without storing them in Home Assistant.

## Integration domain and services

Integration/service domain: `esp32_xiaomi_lywsd03`.

Services:

- `esp32_xiaomi_lywsd03.add_sensor`
- `esp32_xiaomi_lywsd03.remove_sensor`

Fields for `add_sensor`:

- `device_id` — stable ID of the selected ESP32 gateway from MQTT identity;
- `mac` — sensor MAC in `AA:BB:CC:DD:EE:FF` format;
- `bind_key` — exactly 32 hexadecimal characters (16 bytes).

Fields for `remove_sensor`:

- `device_id` — stable ID of the selected ESP32 gateway;
- `mac` — sensor MAC.

The service uses the stable `device_id` from MQTT identity. It matches the ID used by `esp32_ota` services, but the Xiaomi integration does not depend on that integration being installed. The gateway ID is not the sensor MAC.

## Sensor state

The UI combines two independent retained snapshots for the selected gateway:

- **New** — MAC is present in `discovered` and absent from `registry`;
- **Save** — MAC is present in `registry`.

After a successful removal, the sensor is removed from `registry`. If the gateway continues receiving its BLE advertisements, it appears in `discovered` again as **New**. Removed sensors must not be artificially hidden from the discovered list.

Snapshots are always kept separately by gateway device ID. A MAC may be discovered by multiple gateways, but it may be saved on only one gateway at a time.

## Home Assistant devices and Areas

The Xiaomi integration obtains gateway MQTT identity independently and uses the shared Device Registry identifier `("esp32", device_id)`. If `esp32_ota` is installed, both integrations enrich the same gateway entry rather than creating separate devices. The Xiaomi integration creates a child HA device for each MAC in the retained `registry`, with three entities: temperature, humidity and battery. The child `device_info` sets `via_device` to the shared ESP32 identifier `("esp32", device_id)`. When a MAC disappears from the registry, the integration removes its sensor entities and device. Unknown measurements remain `unknown` until the sensor reports them.

The integration subscribes to `esp32/+/xiaomi/sensor/+/state`. Retained measurements may arrive before the registry snapshot or gateway identity; the implementation must cache them and apply them once the required information is available. Sensor availability follows the gateway availability.

Areas are not sent over MQTT or stored in firmware. Users assign Areas through native Home Assistant functionality.

## Security

- The bind-key is sent only in the MQTT add command.
- It is never stored in config entries, options, registries, diagnostics, events or Home Assistant states.
- It is never included in logs, errors or service confirmations.
- Validate the MAC and key representation before publishing.
- Address each command only to the selected gateway.
- MQTT commands use `retain=false`.
- Do not keep the key in long-lived integration or panel state after submission.

## MQTT contract

MQTT v1 is agreed and implemented by the firmware. Specifications:

- [MQTT protocol v1 — RU](docs/MQTT_PROTOCOL_RU.md)
- [MQTT protocol v1 — EN](docs/MQTT_PROTOCOL_EN.md)

The contract defines topics, payloads, retained snapshots, add/remove commands, results, measurements, reconnect behavior and security. Xiaomi entities are created by the HA integration, not by firmware MQTT Discovery. The integration must follow both the specification and the actual firmware behavior.

## Xiaomi Sensor Manager panel

The panel is included in this integration repository, registered as a Home Assistant custom panel and restricted to administrators. It must:

1. allow selection of an ESP32 gateway known to the Xiaomi integration through MQTT identity, regardless of whether `esp32_ota` is installed;
2. show discovered and saved sensors for the selected gateway;
3. mark saved sensors as **Save** and new sensors as **New**;
4. provide a bind-key field only for adding;
5. allow removal of a saved sensor from the same panel;
6. call `esp32_xiaomi_lywsd03.add_sensor` and `esp32_xiaomi_lywsd03.remove_sensor`.

The panel reads state through the integration's WebSocket API and calls its services. It does not communicate with the MQTT broker directly.

After removal, a sensor remains in the combined list if it is still discovered; only its status changes from **Save** to **New**.

## Implementation stages

1. HA integration foundation, config flow and MQTT v1 subscriptions — implemented.
2. Per-gateway snapshot state and recovery from retained snapshots — implemented.
3. Add/remove services, validation, command-result correlation and cross-gateway MAC locking — implemented.
4. WebSocket state API and events for the Xiaomi Sensor Manager — implemented.
5. HA sensor entities and child devices from retained registry — implemented; runtime verification in Home Assistant is pending.
6. Xiaomi Sensor Manager panel bundled with the integration — implemented; runtime verification in Home Assistant is pending.
7. Runtime verification with multiple gateways, offline/reconnect, QoS 1 redelivery, dynamic entity removal and Areas remains.

## Related projects

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [Universal ESP32 integration](https://github.com/lavrenovalexsandr-cmyk/esp32-integration-core)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)
- [ESP32 Lovelace Cards](https://github.com/lavrenovalexsandr-cmyk/esp32-card)

The primary documentation is README.md in Russian. The English version is README_EN.md.
