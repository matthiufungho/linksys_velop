"""Constants for Linksys Velop."""

# region #-- imports --#
from typing import Dict, List, Optional

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN

try:
    from homeassistant.components.update import DOMAIN as UPDATE_DOMAIN
except ImportError:
    UPDATE_DOMAIN = None

# endregion

DOMAIN: str = "linksys_velop"
ENTITY_SLUG: str = "Velop"

CONF_API_REQUEST_TIMEOUT: str = "api_request_timeout"
CONF_COORDINATOR: str = "coordinator"
CONF_COORDINATOR_MESH: str = "mesh"
CONF_DEVICE_TRACKERS: str = "tracked"
CONF_ENTRY_RELOAD: str = "reloading"
CONF_FLOW_NAME: str = "name"
CONF_LOGGING_JNAP_RESPONSE: str = "logging_jnap_response"
CONF_LOGGING_MODE: str = "logging_mode"
CONF_LOGGING_SERIAL: str = "logging_serial"
CONF_NODE: str = "node"
CONF_NODE_IMAGES: str = "node_images"
CONF_SCAN_INTERVAL_DEVICE_TRACKER: str = "scan_interval_device_tracker"
CONF_SERVICES_HANDLER: str = "services_handler"
CONF_TITLE_PLACEHOLDERS: str = "title_placeholders"
CONF_UNSUB_UPDATE_LISTENER: str = "unsub_update_listener"

DEF_API_REQUEST_TIMEOUT: int = 10
DEF_CONSIDER_HOME: int = 180
DEF_FLOW_NAME: str = "Linksys Velop Mesh"
DEF_LOGGING_JNAP_RESPONSE: bool = False
DEF_LOGGING_MODE: str = "off"
DEF_LOGGING_SERIAL: bool = False
DEF_SCAN_INTERVAL: int = 60
DEF_SCAN_INTERVAL_DEVICE_TRACKER: int = 10

EVENT_NEW_PARENT_NODE: str = f"{DOMAIN}_new_primary_node"

LOGGING_STATES: Dict[str, str] = {  # order defines order of options on screen
    "off": "Off",
    "single": "Single poll",
}

PLATFORMS: List[Optional[str]] = [
    BINARY_SENSOR_DOMAIN,
    BUTTON_DOMAIN,
    DEVICE_TRACKER_DOMAIN,
    SELECT_DOMAIN,
    SENSOR_DOMAIN,
    SWITCH_DOMAIN,
    UPDATE_DOMAIN,
]

SIGNAL_UPDATE_DEVICE_TRACKER: str = "update_device_tracker"
SIGNAL_UPDATE_SPEEDTEST_RESULTS: str = "update_speedtest_results"
SIGNAL_UPDATE_SPEEDTEST_STATUS: str = "update_speedtest_status"

ST_IGD: str = "urn:schemas-upnp-org:device:InternetGatewayDevice:2"
