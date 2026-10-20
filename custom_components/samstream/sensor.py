"""Developer host: the one machine the TV accepts app installs from."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Add the developer host sensor."""
    async_add_entities([DeveloperHostSensor(entry.runtime_data.coordinator)])


class DeveloperHostSensor(SamstreamEntity, SensorEntity):
    """IP address set in the TV's Developer Mode screen."""

    _attr_translation_key = "developer_host"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "developer_host")

    @property
    def available(self) -> bool:
        """Only known after the TV has answered once."""
        return super().available and self.coordinator.data.info is not None

    @property
    def native_value(self) -> str | None:
        """Developer host IP, None when Developer Mode is off."""
        info = self.coordinator.data.info
        return info.developer_ip if info and info.developer_mode else None
