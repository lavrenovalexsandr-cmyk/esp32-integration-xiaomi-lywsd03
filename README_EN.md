# ESP32 Home Assistant Integration — Xiaomi LYWSD03MMC

A dedicated Home Assistant integration for ESP32 gateways with Xiaomi LYWSD03MMC BLE sensors.

> Status: MQTT v1 is agreed and implemented in firmware. This repository contains the specification and documentation; the Home Assistant Python integration is being developed in branch `feature/xiaomi-ha-integration-v1`.

## Purpose and responsibility boundaries

This integration handles Xiaomi-specific operations and coordination across multiple ESP32 gateways. Generic ESP32 management (OTA, Restart and Factory Reset) remains in the universal `esp32_ota` integration; base gateway identity belongs to Platform Core and the shared MQTT contract.

Responsibilities:

- **Firmware / Platform Core:** BLE discovery, bind-key storage in NVS, MQTT v1, retained snapshots and measurements, and Home Assistant MQTT Discovery for sensors.
- **Universal `esp32_ota` integration:** OTA and generic device-control commands; it also uses the shared gateway device entry but is not required by the Xiaomi integration.
- **Shared MQTT contract / Platform Core:** stable gateway identity and its base information.
- **This Xiaomi integration:** MQTT snapshot handling, per-gateway state, global enforcement of the one-MAC/one-gateway rule, add/remove services and secure bind-key forwarding.
- **Lovelace card:** gateway/sensor selection and calls to this integration's services. The card does not publish MQTT directly or store bind-keys.

The Xiaomi integration must not create duplicate gateway devices, sensor devices or sensor entities. Firmware publishes sensor devices and their three entities through Platform Core's standard MQTT Discovery.

## Shared ESP32 gateway identity

The Xiaomi integration is independent of `esp32_ota`: it must not import its code or require it to be installed.

To merge information from different ESP32 integrations into one Home Assistant Device Registry entry, use the shared gateway identifier:

```python
identifiers={("esp32", device_id)}
```

Here, `esp32` is the platform-wide namespace and `device_id` is the stable ID from MQTT identity. The gateway name and model must come from the same MQTT identity fields (`name` and `model`) so integrations expose consistent device information.

**Xiaomi integration implementation task:** obtain gateway MQTT identity independently and use `("esp32", device_id)` when registering/enriching the gateway device. Do not use `("esp32_ota", device_id)` or rely on `esp32_ota` being installed. Xiaomi services continue to accept the stable `device_id`.

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

The Xiaomi integration obtains gateway MQTT identity independently and uses the shared Device Registry identifier `("esp32", device_id)`. If `esp32_ota` is installed, both integrations enrich the same gateway entry rather than creating separate devices. Firmware uses Platform Core MQTT Discovery to create a separate HA device for each Xiaomi sensor and three entities: temperature, humidity and battery. Unknown measurements remain `unknown` until the sensor reports them.

The current Platform Core implementation does not emit `via_device`, so no parent relationship between sensor and gateway is created in the device registry. The Xiaomi integration must not invent a parallel relationship mechanism.

Areas are not sent over MQTT or stored in firmware. Users assign Areas through native Home Assistant functionality.

## Security

- The bind-key is sent only in the MQTT add command.
- It is never stored in config entries, options, registries, diagnostics, events or Home Assistant states.
- It is never included in logs, errors or service confirmations.
- Validate the MAC and key representation before publishing.
- Address each command only to the selected gateway.
- MQTT commands use `retain=false`.
- Do not keep the key in long-lived integration or card state after submission.

## MQTT contract

MQTT v1 is agreed and implemented by the firmware. Specifications:

- [MQTT protocol v1 — RU](docs/MQTT_PROTOCOL_RU.md)
- [MQTT protocol v1 — EN](docs/MQTT_PROTOCOL_EN.md)

The contract defines topics, payloads, retained snapshots, add/remove commands, results, measurements, reconnect behavior, security and the Platform Core HA entity-registry limit. The integration must follow both the specification and the actual firmware behavior.

## Lovelace card

The UI lives in [esp32-card](https://github.com/lavrenovalexsandr-cmyk/esp32-card). The Xiaomi Sensor Manager must:

1. allow selection of an ESP32 gateway known to the Xiaomi integration through MQTT identity, regardless of whether `esp32_ota` is installed;
2. show discovered and saved sensors for the selected gateway;
3. mark saved sensors as **Save** and new sensors as **New**;
4. provide a bind-key field only for adding;
5. allow removal of a saved sensor from the same card;
6. call `esp32_xiaomi_lywsd03.add_sensor` and `esp32_xiaomi_lywsd03.remove_sensor`.

After removal, a sensor remains in the combined list if it is still discovered; only its status changes from **Save** to **New**.

## Implementation stages

1. Implement the HA integration foundation and MQTT v1 subscriptions.
2. Implement per-gateway snapshot state and reconnect recovery.
3. Implement secure add/remove services and command-result correlation.
4. Implement cross-gateway MAC locking using retained registries of known gateways.
5. Implement the Xiaomi Sensor Manager card.
6. Verify multiple gateways, offline/reconnect, QoS 1 redelivery and Areas.

## Related projects

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [Universal ESP32 integration](https://github.com/lavrenovalexsandr-cmyk/esp32-integration-core)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)
- [ESP32 Lovelace Cards](https://github.com/lavrenovalexsandr-cmyk/esp32-card)

The primary documentation is README.md in Russian. The English version is README_EN.md.
