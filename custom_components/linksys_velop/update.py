"""Update entities for nodes"""

# region #-- imports --#
from __future__ import annotations

import dataclasses
import logging
from abc import ABC
from typing import List

from homeassistant.components.update import (
    DOMAIN as ENTITY_DOMAIN,
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify
from pyvelop.mesh import Mesh
from pyvelop.node import Node

from . import (
    entity_cleanup,
    LinksysVelopNodeEntity,
)
from .const import (
    CONF_COORDINATOR,
    DOMAIN,
    ENTITY_SLUG,
)

# endregion

_LOGGER = logging.getLogger(__name__)


# region #-- update entity descriptions --#
@dataclasses.dataclass
class OptionalLinksysVelopDescription:
    """Represent the optional attributes of the update description."""


@dataclasses.dataclass
class RequiredLinksysVelopDescription:
    """Represent the required attributes of the update description."""


@dataclasses.dataclass
class LinksysVelopUpdateDescription(
    OptionalLinksysVelopDescription,
    UpdateEntityDescription,
    RequiredLinksysVelopDescription
):
    """Describes update entity"""
# endregion


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensors from a config entry"""

    coordinator = hass.data[DOMAIN][config_entry.entry_id][CONF_COORDINATOR]
    mesh: Mesh = coordinator.data

    update_entities: List[LinksysVelopNodeUpdate] = []

    # region #-- node sensors --#
    node: Node
    for node in mesh.nodes:
        update_entities.extend([
            LinksysVelopNodeUpdate(
                config_entry=config_entry,
                coordinator=coordinator,
                node=node,
                description=LinksysVelopUpdateDescription(
                    device_class=UpdateDeviceClass.FIRMWARE,
                    key="",
                    name="Update",
                )
            ),
        ])
    # endregion

    async_add_entities(update_entities)

    sensors_to_remove: List = []
    if sensors_to_remove:
        entity_cleanup(config_entry=config_entry, entities=sensors_to_remove, hass=hass)


class LinksysVelopNodeUpdate(LinksysVelopNodeEntity, UpdateEntity, ABC):
    """Representation of an update entity for a node"""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        node: Node,
        config_entry: ConfigEntry,
        description: LinksysVelopUpdateDescription
    ) -> None:
        """Constructor"""

        self._node_id: str = node.unique_id
        super().__init__(config_entry=config_entry, coordinator=coordinator)

        self.entity_description: LinksysVelopUpdateDescription = description

        self._attr_name = f"{ENTITY_SLUG} {self._node.name}: {self.entity_description.name}"
        self._attr_unique_id = f"{self._node.unique_id}::" \
                               f"{ENTITY_DOMAIN.lower()}::" \
                               f"{slugify(self.entity_description.name)}"

    @property
    def current_version(self) -> str | None:
        """Get the current version"""

        return self._node.firmware.get("version", None)

    @property
    def latest_version(self) -> str | None:
        """Get the latest version"""

        return self._node.firmware.get("latest_version", None)
