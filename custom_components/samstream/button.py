"""Button: sign the bundled Samstream app with HA's certificates and install it."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the install button."""
    async_add_entities([InstallAppButton(entry.runtime_data.coordinator)])


class InstallAppButton(SamstreamEntity, ButtonEntity):
    """Install (or reinstall) the Samstream player on the TV."""

    _attr_translation_key = "install_app"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the button for the coordinator's TV."""
        super().__init__(coordinator, "install_app")

    async def async_press(self) -> None:
        """Sign the bundled package and install it over sdb."""
        await async_install_package(self.hass, self.coordinator.config_entry, None)
