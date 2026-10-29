"""Buttons: install the TV app, logos, return, and the TV's own screens (keys)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import DOMAIN
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
        [
            InstallAppButton(coordinator),
            DownloadLogosButton(coordinator),
            ReturnButton(coordinator),
            *(KeyButton(coordinator, key, code) for key, code in SCREEN_KEYS),
        ]
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


class ReturnButton(SamstreamEntity, ButtonEntity):
    """Close what Samstream shows and go back to what was on (stop_stream)."""

    _attr_translation_key = "return_to_previous"

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the button for the coordinator's TV."""
        super().__init__(coordinator, "return_to_previous")

    async def async_press(self) -> None:
        """Run `samstream.stop_stream` on this TV's media player."""
        unique_id = (self.unique_id or "").removesuffix("return_to_previous")
        media_player = er.async_get(self.hass).async_get_entity_id(
            MEDIA_PLAYER_DOMAIN, DOMAIN, unique_id + "media_player"
        )
        if media_player is None:
            return
        await self.hass.services.async_call(
            DOMAIN, "stop_stream", {"entity_id": media_player}, blocking=True
        )


# The TV's own screens. Remote keys, not local control: the TV refuses to open
# its native apps over local control ("unavailable"), and keys work on any TV.
SCREEN_KEYS = (
    ("open_guide", "KEY_GUIDE"),
    ("open_channel_list", "KEY_CH_LIST"),
    ("open_sources", "KEY_SOURCE"),
    ("open_menu", "KEY_MENU"),
    ("open_home", "KEY_HOME"),
)


class KeyButton(SamstreamEntity, ButtonEntity):
    """Open one of the TV's screens (guide, channel list, ...) with its key."""

    def __init__(self, coordinator: SamstreamCoordinator, key: str, code: str) -> None:
        """Create the button for the coordinator's TV."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._code = code

    async def async_press(self) -> None:
        """Press the key."""
        await self._async_call(self.coordinator.tv.send_keys([self._code]))
