# ESP32 Xiaomi Sensor Manager

A dedicated Home Assistant integration for ESP32 gateways with Xiaomi LYWSD03MMC BLE sensors.

> Status: the architecture in which the Xiaomi integration owns sensor devices and measurement entities is implemented. End-to-end verification requires Home Assistant, an MQTT broker and ESP32 firmware.

## HACS installation

1. Add `lavrenovalexsandr-cmyk/esp32-integration-manager` in **HACS → Integrations → Custom repositories**, install **ESP32 Manager**, and add it through **Settings → Devices & services → Add integration**.
2. Add `lavrenovalexsandr-cmyk/esp32-integration-xiaomi-sensor-manager` to HACS and install **ESP32 Xiaomi Sensor Manager**.
3. Restart Home Assistant if HACS requests it.
4. Add **ESP32 Xiaomi Sensor Manager** through **Settings → Devices & services → Add integration**.

Configure the standard Home Assistant **MQTT** integration separately and make sure the broker is connected to the ESP32 gateways. The Xiaomi integration reuses the configured MQTT connection; it does not need broker credentials in its own config flow.

A GitHub Release is not required for installation as a Custom repository: if there are no releases, HACS uses the short hash of the latest commit as the version. For regular versioned updates, publishing a GitHub Release with a tag aligned with `manifest.json` is recommended. You can also test manually by copying `custom_components/esp32_xiaomi_lywsd03` into `config/custom_components/`.

## Home Assistant entities and manager panel

The integration creates a separate Home Assistant device for every saved Xiaomi LYWSD03MMC, with three measurement entities: temperature, humidity and battery. Each sensor device is linked to its ESP32 gateway parent through `via_device`.

The **Xiaomi Sensor Manager** panel is part of this repository and appears in the Home Assistant sidebar after the integration is configured. It is admin-only. No separate Lovelace card or second HACS repository is required.

## Purpose and responsibility boundaries

This integration handles Xiaomi-specific operations and coordination across multiple ESP32 gateways. Generic ESP32 management (OTA, Restart and Factory Reset), gateway discovery, identity, profile, availability and the shared device registry belong to ESP32 Manager.

Responsibilities:

- **Firmware:** BLE discovery, bind-key storage in NVS, registry, commands and command results, retained snapshots and retained MQTT measurements.
- **ESP32 Manager (`esp32_ota`):** the sole source of common gateway information; discovery, identity, profile, availability, shared Device Registry entry, public API and lifecycle events; OTA and generic system commands.
- **Platform Core:** stable hardware identity, common MQTT contracts and firmware platform mechanisms.
- **This Xiaomi integration:** Xiaomi snapshots and measurements only, per-gateway domain state, the one-MAC/one-gateway rule, add/remove services, secure bind-key forwarding, creation/removal of child Xiaomi devices and sensors, and the manager panel.
- **Xiaomi Sensor Manager panel:** gateway and sensor selection, `New`/`Save` status, and add/remove operations through integration services. The panel does not publish MQTT directly or store bind-keys.

## Shared ESP32 gateway identity

Xiaomi Sensor Manager declares `esp32_ota` as a required dependency in `manifest.json`. ESP32 Manager creates the shared physical-device entry with identifier:

```python
identifiers={("esp32", device_id)}
```

The Xiaomi integration does not subscribe to common MQTT identity, profile or availability topics, does not create the gateway entry in Device Registry, and does not maintain its own copy of common metadata. At startup it obtains device snapshots through the public API `hass.data["esp32_ota"]["api"]`, then updates its runtime projection from the `esp32_ota_device_added` and `esp32_ota_device_updated` events.

The integration uses `get_devices()` and `get_device(device_id)` from the API. For cascading removal, Xiaomi Sensor Manager registers its own async cleanup handler through `register_remove_handler`. It continues to process only Xiaomi product topics: discovered, registry, command/result and sensor measurements.

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

- `device_id` — stable ID of the selected ESP32 gateway from the MQTT identity managed by ESP32 Manager;
- `mac` — sensor MAC in `AA:BB:CC:DD:EE:FF` format;
- `bind_key` — exactly 32 hexadecimal characters (16 bytes).

Fields for `remove_sensor`:

- `device_id` — stable ID of the selected ESP32 gateway;
- `mac` — sensor MAC.

The service uses the stable `device_id` from ESP32 Manager. It matches the ID used by `esp32_ota` services; the gateway ID is not the sensor MAC.

## Sensor state

The UI combines two independent retained snapshots for the selected gateway:

- **New** — MAC is present in `discovered` and absent from `registry`;
- **Save** — MAC is present in `registry`.

After a removal request, the sensor is immediately removed from XSM's local state and Home Assistant, and its MAC is stored in a persistent tombstone. This prevents an old retained `registry` snapshot from restoring the sensor before the gateway confirms cleanup. If the gateway is available, XSM also sends the remove command in the background; gateway confirmation does not block local removal. If the gateway is offline or the command is not confirmed, local removal remains completed and the tombstone continues to protect the state from stale snapshots. The tombstone is cleared after the gateway publishes a `registry` snapshot without that MAC. If the sensor is still detected over BLE, it appears again as **New**.

Snapshots are always kept separately by gateway device ID. A MAC may be discovered by multiple gateways, but it may be saved on only one gateway at a time.

## Home Assistant devices and Areas

ESP32 Manager creates the shared gateway device entry. Xiaomi Sensor Manager creates a child HA device for each MAC in the retained `registry`, with three entities: temperature, humidity and battery. The child `device_info` sets `via_device` to the shared ESP32 identifier `("esp32", device_id)`. When a MAC is removed from the registry, the integration removes its sensor entities and child device. Unknown measurements remain `unknown` until the sensor reports them.

The integration subscribes to `esp32/+/xiaomi/sensor/+/state`. Product messages are processed only for gateways already known to ESP32 Manager. Manager handles common identity/profile/availability. Sensor availability follows the central gateway availability and profile validity.

When a gateway is fully removed, ESP32 Manager calls the cleanup handler registered by Xiaomi Sensor Manager. XSM removes all child Xiaomi devices and entities, retained measurements associated with that gateway, runtime cache, pending commands and persistent tombstones for that gateway. Retained Xiaomi snapshots and measurements for that gateway are cleared; data for other ESP32 devices is not affected.

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

1. allow selection of an ESP32 gateway known to the central ESP32 Manager registry;
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
4. WebSocket state API and events for ESP32 Xiaomi Sensor Manager — implemented.
5. HA sensor entities and child devices from retained registry — implemented; runtime verification in Home Assistant is pending.
6. Xiaomi Sensor Manager panel bundled with the integration — implemented; runtime verification in Home Assistant is pending.
7. Runtime verification with multiple gateways, offline/reconnect, QoS 1 redelivery, dynamic entity removal and Areas remains.

## Related projects

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [Universal ESP32 integration](https://github.com/lavrenovalexsandr-cmyk/esp32-integration-manager)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)

The primary documentation is README.md in Russian. The English version is README_EN.md.
