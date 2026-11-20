"""Constants for the ESP32 Xiaomi Sensor Manager integration."""

DOMAIN = "esp32_xiaomi_lywsd03"
DEVICE_IDENTIFIER_NAMESPACE = "esp32"
XIAOMI_DEVICE_IDENTIFIER_NAMESPACE = "esp32_xiaomi_lywsd03"

IDENTITY_TOPIC = "esp32/+/device/info"
AVAILABILITY_TOPIC = "esp32/+/availability"
XIAOMI_TOPICS = (
    "esp32/+/xiaomi/discovered",
    "esp32/+/xiaomi/registry",
    "esp32/+/xiaomi/command/result",
)
MEASUREMENTS_TOPIC = "esp32/+/xiaomi/sensor/+/state"

PROTOCOL_VERSION = 1
MAX_SENSORS_PER_GATEWAY = 16
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
DATA_REMOVED_SENSORS = "removed_sensors"
DATA_MEASUREMENTS = "measurements"
DATA_SENSOR_ENTITIES = "sensor_entities"
DATA_ADD_ENTITIES = "add_sensor_entities"

PANEL_URL_PATH = "esp32-xiaomi-sensors"
PANEL_WEB_COMPONENT = "esp32-xiaomi-sensor-manager"
PANEL_STATIC_URL = "/esp32_xiaomi_lywsd03/xiaomi-panel.js"

DEVICE_ID_PATTERN = r"^[0-9A-F]{12}$"
MAC_PATTERN = r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$"
BIND_KEY_PATTERN = r"^[0-9A-Fa-f]{32}$"
