"""Developer Mode and the Samstream TV app: what installing the player needs."""

from __future__ import annotations

from aiosamstream import SAMSTREAM_APP_ID
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
    """Add the Developer Mode and Samstream app sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [DeveloperModeSensor(coordinator), SamstreamAppSensor(coordinator)]
    )


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


class SamstreamAppSensor(SamstreamEntity, BinarySensorEntity):
    """On when the Samstream player is installed on the TV."""

    _attr_translation_key = "samstream_app"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "samstream_app")

    @property
    def available(self) -> bool:
        """Known once the TV has been on and its apps were scanned."""
        return super().available and self.coordinator.apps_scanned

    @property
    def is_on(self) -> bool:
        """Installed according to the last app scan."""
        return SAMSTREAM_APP_ID in self.coordinator.apps

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Installed version, compared with the bundled one in milestone 7b."""
        return {"version": self.coordinator.app_versions.get(SAMSTREAM_APP_ID)}
