"""Constants for the ESP32 Xiaomi LYWSD03MMC integration."""

DOMAIN = "esp32_xiaomi_lywsd03"
DEVICE_IDENTIFIER_NAMESPACE = "esp32"

IDENTITY_TOPIC = "esp32/+/device/info"
AVAILABILITY_TOPIC = "esp32/+/availability"
XIAOMI_TOPIC = "esp32/+/xiaomi/+"

PROTOCOL_VERSION = 1
COMMAND_TIMEOUT = 30
MAX_REQUEST_ID_LENGTH = 64

SERVICE_ADD_SENSOR = "add_sensor"
SERVICE_REMOVE_SENSOR = "remove_sensor"

EVENT_STATE_UPDATED = f"{DOMAIN}_state_updated"
EVENT_COMMAND_RESULT = f"{DOMAIN}_command_result"

DATA_GATEWAYS = "gateways"
DATA_UNSUB = "unsub"
DATA_PENDING = "pending"
DATA_PENDING_ADDS = "pending_adds"

DEVICE_ID_PATTERN = r"^[0-9A-F]{12}$"
MAC_PATTERN = r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$"
BIND_KEY_PATTERN = r"^[0-9A-Fa-f]{32}$"
