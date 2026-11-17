# Xiaomi LYWSD03MMC MQTT Protocol

- Protocol version: **1**
- Status: agreed specification for implementation
- Scope: communication between an ESP32 gateway and Home Assistant for Xiaomi LYWSD03MMC BLE sensors

## 1. General rules

Each gateway has a stable `DEVICE_ID` provided by Platform Core. All Xiaomi topics for that gateway use its own namespace:

```
esp32/<DEVICE_ID>/xiaomi/
```

`DEVICE_ID` identifies the gateway, not a sensor MAC. Commands are always addressed to one gateway; broadcast commands are not used.

- MQTT QoS: **1** for all messages below.
- Commands and command results: **retain=false**.
- Discovered-device and registry snapshots: **retain=true**.
- Latest measurements: **retain=true**.
- JSON encoding: UTF-8.
- Every protocol JSON message contains `version: 1`.
- MAC addresses in payloads and topics are normalized to uppercase `AA:BB:CC:DD:EE:FF`.
- Receivers must ignore unknown fields. An unknown protocol version must not be processed as version 1.

### 1.1. Topics

| Direction | Topic | Retain | Purpose |
|---|---|---:|---|
| ESP → HA | `esp32/<DEVICE_ID>/xiaomi/discovered` | Yes | Current list of discovered, unsaved sensors |
| ESP → HA | `esp32/<DEVICE_ID>/xiaomi/registry` | Yes | List of sensors saved in the gateway's NVS |
| ESP → HA | `esp32/<DEVICE_ID>/xiaomi/sensor/<MAC>/state` | Yes | Latest sensor measurements |
| HA → ESP | `esp32/<DEVICE_ID>/xiaomi/command/add` | No | Add a sensor and its bind-key |
| HA → ESP | `esp32/<DEVICE_ID>/xiaomi/command/remove` | No | Remove a sensor |
| ESP → HA | `esp32/<DEVICE_ID>/xiaomi/command/result` | No | Command result |

Each gateway has its own topics. A subscription to one gateway namespace must not receive commands for another gateway.

## 2. Discovered sensors

The gateway publishes a retained snapshot of sensors detected over BLE but not present in its saved registry.

Example:

```json
{
  "version": 1,
  "sensors": [
    {
      "mac": "A4:C1:38:12:34:56",
      "rssi": -68
    }
  ]
}
```

Rules:

1. A sensor remains discovered for **5 minutes** after its last accepted advertising packet.
2. Each new advertising packet updates RSSI and refreshes the expiry.
3. Sensors saved on this gateway are excluded from `discovered`.
4. If a sensor is removed from the registry but is still being detected, it appears in `discovered` again. This is required by the UI: after removal it is **New** again; a saved sensor is marked **Save**.
5. Whenever the list changes, the gateway publishes the complete current snapshot, not incremental deltas.
6. When the list becomes empty or all entries expire, the gateway publishes a retained message with an empty `sensors` array. An empty retained payload is not used for this topic.

The list is scoped to one gateway. The same MAC may appear in the discovered lists of multiple gateways simultaneously.

## 3. Saved registry

The registry reflects sensors whose bind-keys are saved in this gateway's NVS.

Example:

```json
{
  "version": 1,
  "sensors": [
    {
      "mac": "A4:C1:38:12:34:56"
    }
  ]
}
```

Rules:

- The source of truth is NVS and the Xiaomi driver registry on the ESP32. Home Assistant does not edit the registry directly.
- The gateway publishes a complete retained snapshot when MQTT starts, after a successful add, and after a remove.
- An empty registry is published as `{"version":1,"sensors":[]}`.
- The Home Assistant integration maintains a separate current snapshot for each gateway and never merges registries.
- After removal, the sensor is excluded from `registry`; if it is still detected, it remains in or reappears in `discovered`.

## 4. Measurements

Each saved sensor has its own state topic:

```
esp32/<DEVICE_ID>/xiaomi/sensor/<MAC>/state
```

Example:

```json
{
  "version": 1,
  "temperature": 23.4,
  "humidity": 48.2,
  "battery": 87
}
```

Fields:

| Field | Type | Unit / value |
|---|---|---|
| `temperature` | number | °C |
| `humidity` | number | % |
| `battery` | integer | % |

Only measurements actually received and successfully decrypted are published. A field that is not yet known may be omitted. Values must not be replaced with zero or fabricated placeholders.

The gateway publishes an update when new valid measurements arrive. The message is retained so Home Assistant receives the latest value after reconnecting.

Home Assistant creates separate temperature, humidity and battery entities. Units and device classes are configured in HA Discovery, not duplicated in the JSON.

Sensor entity availability inherits the availability of its gateway. Version 1 does not introduce a per-sensor availability topic. Gateway availability therefore does not guarantee that an individual sensor has transmitted recently.

When a sensor is removed, the gateway deletes its retained state topic by publishing an empty retained payload and removes its HA Discovery components.

## 5. Add command

Topic:

```
esp32/<DEVICE_ID>/xiaomi/command/add
```

Example:

```json
{
  "version": 1,
  "request_id": "a81f92c4",
  "mac": "A4:C1:38:12:34:56",
  "bind_key": "0123456789ABCDEF0123456789ABCDEF"
}
```

Requirements:

- `request_id` is a non-empty string up to 64 characters. The integration generates a unique value for each operation.
- `mac` is the sensor MAC in canonical format.
- `bind_key` is exactly 32 hexadecimal characters representing 16 bytes.
- The command is sent only to the selected gateway namespace.
- The command is not retained.
- Firmware validates the fields and passes the key to the driver for storage in NVS.
- The bind-key must never be logged, echoed in a response, or published to any other topic.

A successful add updates `registry`. If the sensor is still being detected, it is removed from `discovered`.

## 6. Remove command

Topic:

```
esp32/<DEVICE_ID>/xiaomi/command/remove
```

Example:

```json
{
  "version": 1,
  "request_id": "b72f31a0",
  "mac": "A4:C1:38:12:34:56"
}
```

Removal is addressed to one specific gateway. On successful removal:

1. the sensor entry is removed from NVS/the registry;
2. an updated `registry` is published;
3. retained state and HA Discovery for the sensor are removed;
4. if the sensor is still detected, it remains in or reappears in `discovered`.

Removing a sensor that is not present returns `not_found`.

## 7. Command result

Both commands return their result on:

```
esp32/<DEVICE_ID>/xiaomi/command/result
```

Successful result example:

```json
{
  "version": 1,
  "request_id": "a81f92c4",
  "action": "add",
  "mac": "A4:C1:38:12:34:56",
  "result": "success"
}
```

Allowed `action` values: `add`, `remove`.

Allowed `result` values:

| Result | Meaning |
|---|---|
| `success` | Operation completed |
| `already_exists` | Sensor is already saved on this gateway |
| `not_found` | Sensor is not in the registry (remove) |
| `full` | Registry is full |
| `invalid_argument` | Invalid arguments or command format |
| `storage_error` | Storage read/write failure |
| `busy` | Operation temporarily unavailable because a resource is busy |
| `not_initialized` | Xiaomi component is not initialized |

The result includes the original `request_id`, `action` and normalized `mac`. It never includes the bind-key.

QoS 1 permits message redelivery. Operations must therefore be safe to retry: a repeated add returns `already_exists`; a repeated remove returns `not_found`. The integration correlates results using the gateway + request_id pair.

## 8. One gateway per sensor

A MAC address may be saved in the registry of only one gateway at a time.

- The same MAC may be discovered over BLE by multiple gateways.
- Before sending add, the integration checks retained registries of all known gateways.
- If the MAC is already saved on another gateway, the integration rejects the add and sends no command.
- The integration also reserves the MAC while an add operation is pending, preventing it from sending parallel add commands to two gateways.
- After a successful remove, the MAC may be added to another gateway.
- Firmware has no global knowledge of other gateways and does not enforce cross-gateway locking itself. This rule is coordinated by the Home Assistant integration; direct commands bypassing it are outside this guarantee.

A retained registry from an offline gateway still counts: losing connectivity does not release the MAC.

## 9. Home Assistant Discovery and identity

- Use Platform Core's standard device discovery through `platform_ha`; the Xiaomi integration does not define a separate custom discovery protocol.
- Each sensor has its own HA device and three entities: temperature, humidity and battery.
- Sensor identifiers are derived stably from the gateway identity and sensor MAC so identical MACs on different gateways cannot collide in device/entity IDs.
- Sensor entities use the gateway availability topic: `esp32/<DEVICE_ID>/availability`.
- Rooms/Areas are not sent over MQTT. Users assign Areas through Home Assistant.
- The current Platform Core `platform_ha` implementation does not emit `via_device` in device discovery. Linking a sensor to its parent gateway using `via_device` requires a separate Core enhancement; until then, the sensor remains an independent HA device.

## 10. Implementation limits

The Xiaomi driver supports a registry of up to 16 sensors per gateway. However, the current `PLATFORM_HA_MAX_ENTITIES` in Platform Core is 32. Three entities per sensor can make the HA entity limit restrictive before the driver limit is reached, especially when gateway entities are included.

This does not change the MQTT contract. Before enabling the full driver capacity, the Platform Core capacity must be addressed separately by increasing the limit or revising entity registration. The current HA limit must not be assumed to support all 16 sensors.

## 11. Reconnect and startup

After MQTT startup and every reconnect, the gateway publishes current retained snapshots for `discovered` and `registry`. Latest measurements remain available through retained state topics.

The integration treats retained snapshots as the gateway's current state. Commands must not accumulate in the broker: retain is forbidden for commands. After an MQTT disconnect, the integration must not mark an unconfirmed operation as successful; it waits for the result or reports a failure/timeout and reconciles state against the next registry snapshot.

Gateway availability is published by the universal Platform Core at `esp32/<DEVICE_ID>/availability`, retained and backed by Last Will. No Xiaomi-specific availability topic is added.

## 12. Security

- The bind-key is sent only in the add command.
- The bind-key is never stored by the Home Assistant integration or card.
- The bind-key is never included in retained messages.
- Firmware never logs the key and clears temporary buffers after use.
- Command topics should be writable only by trusted Home Assistant/clients; gateways read commands and publish their own state.
- MQTT transport uses TLS as configured in Platform Core.

## 13. Version 1 scope

Version 1 does not define OTA/Restart/Factory Reset, room management, per-sensor availability, sending bind-keys back to Home Assistant, broadcast commands, or cross-gateway locking in firmware.
