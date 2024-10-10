import logging

# Will auto-update based on GitHub release tag
VERSION = "v0.3.1"

CONF_YAML = "juicepassproxy.yaml"

LOGFILE = "juicepassproxy.log"
LOG_FORMAT = "%(asctime)-20s %(levelname)-9s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOGLEVEL = logging.INFO
DAYS_TO_KEEP_LOGS = 14

# Defaults
DEFAULT_ENELX_SERVER = "juicenet-udp-prod3-usa.enelx.com"
DEFAULT_ENELX_PORT = "8047"
DEFAULT_LOCAL_IP = "127.0.0.1"
DEFAULT_ENELX_IP = "54.161.147.91"
DEFAULT_MQTT_HOST = "127.0.0.1"
DEFAULT_MQTT_PORT = "1883"
DEFAULT_MQTT_DISCOVERY_PREFIX = "homeassistant"
DEFAULT_DEVICE_NAME = "JuiceBox"
DEFAULT_TELNET_PORT = "2000"
DEFAULT_TELNET_TIMEOUT = "30"

# How many times to fully restart JPP before exiting
MAX_JPP_LOOP = 10

# Will stop JuiceboxMITM or JuiceboxUDPC Updater if there are more than MAX_ERROR_COUNT handled exceptions within ERROR_LOOKBACK_MIN minutes.
MAX_ERROR_COUNT = 10
ERROR_LOOKBACK_MIN = 60

# How many times to retry connections or sending attempts before failing
MAX_RETRY_ATTEMPT = 3

# How many seconds before timing out a UDPC Update
UDPC_UPDATE_CHECK_TIMEOUT = 60

# How many seconds before timing out handling a MITM Message
MITM_HANDLER_TIMEOUT = 10

# How many seconds to wait to receive a MITM Message before timing out
MITM_RECV_TIMEOUT = 120

# How many seconds before timing out sending a MITM Message
MITM_SEND_DATA_TIMEOUT = 10

EXTERNAL_DNS = "1.1.1.1"
