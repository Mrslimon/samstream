"""Buttons: install the Samstream app; download app logos for the card."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package
from .logos import async_app_logos, async_download_logos

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the install and logo buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [InstallAppButton(coordinator), DownloadLogosButton(coordinator)]
    )


class InstallAppButton(SamstreamEntity, ButtonEntity):
    """Install (or reinstall) the Samstream player on the TV."""

    _attr_translation_key = "install_app"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the button for the coordinator's TV."""
        super().__init__(coordinator, "install_app")

    @property
    def available(self) -> bool:
        """Greyed out while an install is running, so it cannot start twice."""
        return super().available and not self.coordinator.installing

    async def async_press(self) -> None:
        """Sign the bundled package and install it over sdb."""
        await async_install_package(self.hass, self.coordinator.config_entry, None)


class DownloadLogosButton(SamstreamEntity, ButtonEntity):
    """Fetch app logos from the apps' websites into /config/www/samstream/apps."""

    _attr_translation_key = "download_logos"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the button for the coordinator's TV."""
        super().__init__(coordinator, "download_logos")

    async def async_press(self) -> None:
        """Download missing logos; the user's own files are kept."""
        coordinator = self.coordinator
        await async_download_logos(
            self.hass, coordinator.apps, async_get_clientsession(self.hass)
        )
        coordinator.logos = await async_app_logos(self.hass, coordinator.apps)
        coordinator.async_update_listeners()
