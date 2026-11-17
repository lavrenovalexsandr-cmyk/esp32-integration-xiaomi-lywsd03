"""Constants for the ESP32 Xiaomi LYWSD03MMC integration."""

DOMAIN = "esp32_xiaomi_lywsd03"
NAME = "ESP32 Xiaomi LYWSD03MMC"
VERSION = 1

DEVICE_IDENTIFIER_NAMESPACE = "esp32"
IDENTITY_TOPIC = "esp32/+/device/info"
AVAILABILITY_TOPIC = "esp32/+/availability"
DISCOVERED_TOPIC = "esp32/+/xiaomi/discovered"
REGISTRY_TOPIC = "esp32/+/xiaomi/registry"
COMMAND_RESULT_TOPIC = "esp32/+/xiaomi/command/result"

ADD_SERVICE = "add_sensor"
REMOVE_SERVICE = "remove_sensor"
PLATFORMS = ["sensor"]

DEVICE_ID_RE = r"^[0-9A-F]{12}$"
MAC_RE = r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$"
BIND_KEY_RE = r"^[0-9A-Fa-f]{32}$"
REQUEST_TIMEOUT = 30
