"""Developer Mode, needed later to install the Samstream TV app."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Developer Mode sensor."""
    async_add_entities([DeveloperModeSensor(entry.runtime_data.coordinator)])


class DeveloperModeSensor(SamstreamEntity, BinarySensorEntity):
    """On when the TV accepts sideloading from the developer host."""

    _attr_translation_key = "developer_mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "developer_mode")

    @property
    def available(self) -> bool:
        """Only known after the TV has answered once."""
        return super().available and self.coordinator.data.info is not None

    @property
    def is_on(self) -> bool | None:
        """Developer Mode flag from the TV's REST API."""
        info = self.coordinator.data.info
        return None if info is None else info.developer_mode
