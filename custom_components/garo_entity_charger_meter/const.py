DOMAIN = "garo_entity_charger_meter"
PLATFORMS: list[str] = ["sensor"]
DEFAULT_SCAN_INTERVAL = 15  # seconds

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IGNORE_TLS_ERRORS = "ignore_tls_errors"
CONF_ENABLE_PHASE_SENSORS = "enable_phase_sensors"
CONF_ENABLE_LINE_VOLTAGES = "enable_line_voltages"
CONF_USE_HTTP = "use_http"

SERVICE_REFRESH = "refresh"

ATTRIBUTION = "Data from GARO charger"
MANUFACTURER = "GARO"
PRODUCT_NAME = "Charger Meter"

API_PATH = "/status/energy-meter"

REDACT_KEYS = {CONF_PASSWORD, CONF_USERNAME}
