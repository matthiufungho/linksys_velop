"""Provide UI for configuring the integration."""

# region #-- imports --#
from __future__ import annotations

import logging
from typing import List

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.components import ssdp
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.components.ssdp import SsdpServiceInfo
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyvelop.device import Device
from pyvelop.exceptions import (
    MeshBadResponse,
    MeshConnectionError,
    MeshInvalidCredentials,
    MeshInvalidInput,
    MeshNodeNotPrimary,
    MeshTimeoutError,
)
from pyvelop.mesh import Mesh, Node

from . import async_logging_state
from .const import (
    CONF_API_REQUEST_TIMEOUT,
    CONF_DEVICE_TRACKERS,
    CONF_FLOW_NAME,
    CONF_LOGGING_JNAP_RESPONSE,
    CONF_LOGGING_MODE,
    CONF_LOGGING_SERIAL,
    CONF_NODE,
    CONF_SCAN_INTERVAL_DEVICE_TRACKER,
    CONF_TITLE_PLACEHOLDERS,
    DEF_API_REQUEST_TIMEOUT,
    DEF_CONSIDER_HOME,
    DEF_FLOW_NAME,
    DEF_LOGGING_JNAP_RESPONSE,
    DEF_LOGGING_MODE,
    DEF_LOGGING_SERIAL,
    DEF_SCAN_INTERVAL,
    DEF_SCAN_INTERVAL_DEVICE_TRACKER,
    DOMAIN,
    EVENT_NEW_PARENT_NODE,
    LOGGING_STATES,
    ST_IGD,
)
from .logger import Logger

# endregion

STEP_DEVICE_TRACKERS: str = "device_trackers"
STEP_INIT: str = "init"
STEP_LOGGING: str = "logging"
STEP_USER: str = "user"
STEP_TIMERS: str = "timers"


_LOGGER = logging.getLogger(__name__)


def _is_mesh_by_host(
    hass: HomeAssistant, host: str
) -> config_entries.ConfigEntry | None:
    """Check if the given host is a Mesh."""
    current_entries = hass.config_entries.async_entries(DOMAIN)
    matching_entry = [
        config_entry
        for config_entry in current_entries
        if config_entry.options.get(CONF_NODE) == host
    ]
    if matching_entry:
        return matching_entry[0]


async def _async_build_schema_with_user_input(
    step: str, user_input: dict, **kwargs
) -> vol.Schema:
    """Build the input and validation schema for the config UI.

    :param step: the step we're in for a configuration or installation of the integration
    :param user_input: the data that should be used as defaults
    :param kwargs: additional information that might be required
    :return: the schema including necessary restrictions, defaults, pre-selections etc.
    """
    schema = {}
    if step == STEP_USER:
        schema = {
            vol.Required(CONF_NODE, default=user_input.get(CONF_NODE, "")): str,
            vol.Required(CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")): str,
        }
    elif step == STEP_TIMERS:
        schema = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=user_input.get(CONF_SCAN_INTERVAL, DEF_SCAN_INTERVAL),
            ): cv.positive_int,
            vol.Required(
                CONF_SCAN_INTERVAL_DEVICE_TRACKER,
                default=user_input.get(
                    CONF_SCAN_INTERVAL_DEVICE_TRACKER, DEF_SCAN_INTERVAL_DEVICE_TRACKER
                ),
            ): cv.positive_int,
            vol.Required(
                CONF_CONSIDER_HOME,
                default=user_input.get(CONF_CONSIDER_HOME, DEF_CONSIDER_HOME),
            ): cv.positive_int,
            vol.Required(
                CONF_API_REQUEST_TIMEOUT,
                default=user_input.get(
                    CONF_API_REQUEST_TIMEOUT, DEF_API_REQUEST_TIMEOUT
                ),
            ): cv.positive_float,
        }
    elif step == STEP_DEVICE_TRACKERS:
        valid_trackers = [
            tracker
            for tracker in user_input.get(CONF_DEVICE_TRACKERS, [])
            if tracker in kwargs["multi_select_contents"].keys()
        ]
        schema = {
            vol.Optional(CONF_DEVICE_TRACKERS, default=valid_trackers): cv.multi_select(
                kwargs["multi_select_contents"]
            )
        }
    elif step == STEP_LOGGING:
        schema = {
            vol.Required(
                CONF_LOGGING_SERIAL,
                default=user_input.get(CONF_LOGGING_SERIAL, DEF_LOGGING_SERIAL),
            ): bool,
            vol.Required(
                CONF_LOGGING_JNAP_RESPONSE,
                default=user_input.get(
                    CONF_LOGGING_JNAP_RESPONSE, DEF_LOGGING_JNAP_RESPONSE
                ),
            ): bool,
            vol.Required(
                CONF_LOGGING_MODE,
                default=user_input.get(CONF_LOGGING_MODE, DEF_LOGGING_MODE),
            ): vol.In(LOGGING_STATES),
        }

    return vol.Schema(schema)


async def _async_get_devices(mesh: Mesh) -> dict:
    """Get the devices from the mesh for display purposes.

    The device unique_id (as per the Mesh) is used as the key.

    :param mesh: the Mesh object
    :return: a dictionary containing the devices to present
    """
    ret: dict = {}

    devices: List[Device] = await mesh.async_get_devices()
    for device in devices:
        for adapter in device.network:
            ret[device.unique_id] = f"{device.name} --> {adapter.get('mac')}"

    return ret


class LinksysVelopConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial installation ConfigFlow."""

    # Paths:
    # 1. user() --> login --> timers --> device_trackers --> finish
    # 2. ssdp(discovery_info) --> pick up at path 1
    # 3. unignore --> discovery_by_st --> pick up at path 2

    task_login = None  # task for the potentially slow login process
    _mesh: Mesh  # mesh object for the class

    def __init__(self):
        """Initialise."""
        self._errors: dict = {}
        self._finish: bool = False
        self._options: dict = {}
        self._log_formatter: Logger = Logger()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return LinksysOptionsFlowHandler(config_entry=config_entry)

    async def _async_task_login(self, user_input) -> None:
        """Login to the Mesh.

        Sets the instance variable if successful

        :param user_input: details of the mesh as per the config UI
        :return: None
        """
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)
        self._mesh = Mesh(**user_input, session=async_get_clientsession(hass=self.hass))
        try:
            _LOGGER.debug(self._log_formatter.format("gathering details"))
            await self._mesh.async_gather_details()
            _LOGGER.debug(self._log_formatter.format("details gathered"))
        except MeshConnectionError:
            _LOGGER.debug(self._log_formatter.format("connection error"))
            self._errors["base"] = "connection_error"
        except MeshInvalidCredentials:
            _LOGGER.debug(self._log_formatter.format("login error"))
            self._errors["base"] = "login_error"
        except MeshBadResponse:
            _LOGGER.debug(self._log_formatter.format("bad response"))
            self._errors["base"] = "login_bad_response"
        except MeshInvalidInput as err:
            _LOGGER.debug(self._log_formatter.format("invalid input"))
            _LOGGER.warning("%s", err)
            self._errors["base"] = "invalid_input"
        except MeshNodeNotPrimary:
            _LOGGER.debug(self._log_formatter.format("not primary"))
            self._errors["base"] = "node_not_primary"
        except MeshTimeoutError:
            _LOGGER.debug(self._log_formatter.format("timeout"))
            self._errors["base"] = "node_timeout"
        else:
            _LOGGER.debug(self._log_formatter.format("no exceptions"))

        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )
        _LOGGER.debug(self._log_formatter.format("exited"))

    async def async_step_device_trackers(
        self, user_input=None
    ) -> data_entry_flow.FlowResult:
        """Allow the user to select the device trackers for presence detection."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)
        if user_input is not None:
            self._errors = {}
            self._options.update(user_input)
            return await self.async_step_finish()

        devices: dict = await _async_get_devices(mesh=self._mesh)

        return self.async_show_form(
            step_id=STEP_DEVICE_TRACKERS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_DEVICE_TRACKERS, self._options, multi_select_contents=devices
            ),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_finish(self) -> data_entry_flow.FlowResult:
        """Finalise the configuration entry."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        _title = (
            self.context.get(CONF_TITLE_PLACEHOLDERS, {}).get(CONF_FLOW_NAME)
            or DEF_FLOW_NAME
        )
        return self.async_create_entry(title=_title, data={}, options=self._options)

    async def async_step_login(self, user_input=None) -> data_entry_flow.FlowResult:
        """Initiate the login task.

        Shows the login task progress and then moves onto the next step, stays on the user step or
        aborts the process on unknown errors.

        :param user_input: details entered by the user
        :return: the necessary FlowResult
        """
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)
        if not self.task_login:
            _LOGGER.debug(self._log_formatter.format("creating login task"))
            details: dict = {
                "node": self._options.get(CONF_NODE),
                "password": self._options.get(CONF_PASSWORD),
                "request_timeout": DEF_API_REQUEST_TIMEOUT,
            }
            self.task_login = self.hass.async_create_task(
                self._async_task_login(user_input=details)
            )
            return self.async_show_progress(
                step_id="login", progress_action="task_login"
            )

        try:
            _LOGGER.debug(self._log_formatter.format("running login task"))
            await self.task_login
            _LOGGER.debug(self._log_formatter.format("returned from login task"))
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug(self._log_formatter.format("exception: %s"), err)
            return self.async_abort(reason="abort_login")

        _LOGGER.debug(self._log_formatter.format("_errors: %s"), self._errors)
        if self._errors:
            return self.async_show_progress_done(next_step_id=STEP_USER)

        return self.async_show_progress_done(next_step_id=STEP_TIMERS)

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> data_entry_flow.FlowResult:
        """Allow the Mesh primary node to be discovered via SSDP."""
        _LOGGER.debug(
            self._log_formatter.format("entered, discovery_info: %s"), discovery_info
        )

        # region #-- get the important info --#
        _host = discovery_info.ssdp_headers.get("_host", "")
        _manufacturer = discovery_info.upnp.get("manufacturer", "")
        _model = discovery_info.upnp.get("modelNumber", "")
        _model_description = discovery_info.upnp.get("modelDescription", "")
        _serial = discovery_info.upnp.get("serialNumber", "")
        # endregion

        # region #-- check for a valid Velop device --#
        if "velop" not in _model_description.lower():
            _LOGGER.debug(self._log_formatter.format("not a Velop model"))
            return self.async_abort(reason="not_velop")
        # endregion

        # region #-- try and update the config entry if it exists and doesn't have a unique_id --#
        # This region assumes that the host is unique for the Mesh (it should be but isn't guaranteed)
        # It will match on host and then update the config entry with the serial number, then abort
        update_unique_id: bool = False
        matching_entry = _is_mesh_by_host(hass=self.hass, host=_host)
        if matching_entry:
            if not matching_entry.unique_id:  # no unique_id even though the host exists
                _LOGGER.debug(
                    self._log_formatter.format("no unique_id in the config entry")
                )
                update_unique_id = True
            elif matching_entry.unique_id != _serial:  # parent node changed?
                _LOGGER.debug(
                    self._log_formatter.format("assuming the primary node has changed")
                )
                self.hass.bus.async_fire(
                    event_type=EVENT_NEW_PARENT_NODE,
                    event_data={
                        "host": _host,
                        "manufacturer": _manufacturer,
                        "model": _model,
                        "description": _model_description,
                        "serial": _serial,
                    },
                )
                update_unique_id = True

        if update_unique_id:
            _LOGGER.debug(self._log_formatter.format("updating unique_id"))
            if self.hass.config_entries.async_update_entry(
                entry=matching_entry, unique_id=_serial
            ):
                return self.async_abort(reason="already_configured")

        # endregion

        # region #-- set a unique_id, update details if device has changed IP --#
        _LOGGER.debug(self._log_formatter.format("setting unique_id"))
        await self.async_set_unique_id(_serial)
        self._abort_if_unique_id_configured(updates={CONF_NODE: _host})
        # endregion

        self.context[CONF_TITLE_PLACEHOLDERS] = {
            CONF_FLOW_NAME: _host
        }  # set the name of the flow

        self._options[CONF_NODE] = _host
        return await self.async_step_user()

    async def async_step_timers(self, user_input=None) -> data_entry_flow.FlowResult:
        """Allow the user to set the relevant timers for the integration."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)
        if user_input is not None:
            self._errors = {}
            self._options[CONF_API_REQUEST_TIMEOUT] = DEF_API_REQUEST_TIMEOUT
            self._options.update(user_input)
            return await self.async_step_device_trackers()

        # region #-- handle the unique_id now --#
        if not self.unique_id:
            _LOGGER.debug(self._log_formatter.format("no unique_id"))
            # region #-- get the unique_id --#
            unique_id: str | None = None
            if self._mesh:
                nodes: List[Node] = self._mesh.nodes
                for node in nodes:
                    if node.type == "primary":
                        unique_id = node.serial
            # end region

            # region #-- do we have matching host? --#
            # didn't always have unique_id so let's look for it by host and set it if we can then abort
            matching_entry = _is_mesh_by_host(
                hass=self.hass, host=self._options.get(CONF_NODE)
            )
            if matching_entry:
                if not matching_entry.unique_id:
                    _LOGGER.debug(
                        self._log_formatter.format("updating config entry unique_id")
                    )
                    self.hass.config_entries.async_update_entry(
                        entry=matching_entry, unique_id=unique_id
                    )
                return self.async_abort(reason="already_configured")
            else:
                _LOGGER.debug(self._log_formatter.format("setting unique_id"))
                await self.async_set_unique_id(unique_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
            # endregion
        # endregion

        return self.async_show_form(
            step_id=STEP_TIMERS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_TIMERS, self._options
            ),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_unignore(self, user_input=None) -> data_entry_flow.FlowResult:
        """Rediscover the devices if the config entry is being unignored."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)

        # region #-- get the original unique_id --#
        unique_id = user_input.get("unique_id")
        await self.async_set_unique_id(unique_id)
        # endregion

        # region #-- discover the necessary devices --#
        devices: List[SsdpServiceInfo] = await ssdp.async_get_discovery_info_by_st(
            self.hass,
            ST_IGD,
        )
        # endregion

        # region #-- try and find this device --#
        device_info = [
            device
            for device in devices
            if device.upnp.get("serialNumber", "") == unique_id
        ]

        if not device_info:
            _LOGGER.debug(self._log_formatter.format("device not found"))
            return self.async_abort(reason="not_found")
        # endregion

        return await self.async_step_ssdp(device_info[0])

    async def async_step_user(self, user_input=None) -> data_entry_flow.FlowResult:
        """Handle a flow initiated by the user."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)

        if user_input is not None:
            self.task_login = None
            self._errors = {}
            self._options.update(user_input)
            return await self.async_step_login()

        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=await _async_build_schema_with_user_input(
                STEP_USER, self._options
            ),
            errors=self._errors,
            last_step=False,
        )


class LinksysOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options from the configuration of the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Intialise."""
        super().__init__()
        self._config_entry = config_entry
        self._errors: dict = {}
        self._options: dict = dict(config_entry.options)
        self._log_formatter: Logger = Logger()

    async def async_step_device_trackers(
        self, user_input=None
    ) -> data_entry_flow.FlowResult:
        """Manage the device trackers."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)

        if user_input is not None:
            # region #-- remove any device trackers that are no longer needed --#
            entity_registry: er.EntityRegistry = er.async_get(hass=self.hass)
            config_entry_entities: List[
                er.RegistryEntry
            ] = er.async_entries_for_config_entry(
                registry=entity_registry, config_entry_id=self._config_entry.entry_id
            )
            device_tracker_entities: List[er.RegistryEntry] = [
                device_tracker
                for device_tracker in config_entry_entities
                if device_tracker.unique_id.startswith(
                    f"{self._config_entry.entry_id}::device_tracker::"
                )
            ]

            for device_tracker in device_tracker_entities:
                uid: str = device_tracker.unique_id.split("::")[-1]
                if uid not in user_input.get(CONF_DEVICE_TRACKERS):
                    _LOGGER.debug(
                        self._log_formatter.format(
                            "removing the device tracker entity for %s"
                        ),
                        device_tracker.name or device_tracker.original_name,
                    )
                    entity_registry.async_remove(entity_id=device_tracker.entity_id)
            # endregion

            self._options.update(user_input)
            return self.async_step_logging()

        mesh = Mesh(
            node=self._config_entry.options[CONF_NODE],
            password=self._config_entry.options[CONF_PASSWORD],
            session=async_get_clientsession(hass=self.hass),
        )
        devices: dict = await _async_get_devices(mesh=mesh)

        return self.async_show_form(
            step_id=STEP_DEVICE_TRACKERS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_DEVICE_TRACKERS, self._options, multi_select_contents=devices
            ),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_init(self, user_input=None) -> data_entry_flow.FlowResult:
        """First Step."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)
        return self.async_show_menu(
            step_id=STEP_INIT,
            menu_options=[STEP_TIMERS, STEP_DEVICE_TRACKERS, STEP_LOGGING],
        )

    async def async_step_logging(self, user_input=None) -> data_entry_flow.FlowResult:
        """Manage settings for logging."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)

        if user_input is not None:
            self._options.update(user_input)
            if self._options.get(CONF_LOGGING_MODE, DEF_LOGGING_MODE) == "off":
                await async_logging_state(
                    config_entry=self._config_entry,
                    hass=self.hass,
                    log_formatter=self._log_formatter,
                    state=False,
                )
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id=STEP_LOGGING,
            data_schema=await _async_build_schema_with_user_input(
                STEP_LOGGING, self._options
            ),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_timers(self, user_input=None) -> data_entry_flow.FlowResult:
        """Manage the timer options available for the integration."""
        _LOGGER.debug(self._log_formatter.format("entered, user_input: %s"), user_input)

        if user_input is not None:
            # TODO: This can be removed after a length of time but it does no harm
            # region #-- tidy up the config after a misconfig on setting up the integration
            self._options.pop("CONF_API_REQUEST_TIMEOUT", None)
            # endregion

            if CONF_API_REQUEST_TIMEOUT not in self._options:
                self._options[CONF_API_REQUEST_TIMEOUT] = DEF_API_REQUEST_TIMEOUT
            self._options.update(user_input)
            return await self.async_step_device_trackers()

        return self.async_show_form(
            step_id=STEP_TIMERS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_TIMERS, self._options
            ),
            errors=self._errors,
            last_step=False,
        )
