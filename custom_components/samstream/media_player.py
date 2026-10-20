"""The TV as a media player: power, volume and playback keys."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 1

FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the TV media player."""
    async_add_entities([SamstreamMediaPlayer(entry.runtime_data.coordinator)])


class SamstreamMediaPlayer(SamstreamEntity, MediaPlayerEntity):
    """Main entity of the TV device."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = FEATURES

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the media player for the coordinator's TV."""
        super().__init__(coordinator, "media_player")

    @property
    def state(self) -> MediaPlayerState:
        """On or off; the current app arrives in milestone 6."""
        return (
            MediaPlayerState.ON if self.coordinator.data.is_on else MediaPlayerState.OFF
        )

    @property
    def volume_level(self) -> float | None:
        """Volume as 0..1."""
        volume = self.coordinator.data.volume
        return None if volume is None else volume / 100

    @property
    def is_volume_muted(self) -> bool | None:
        """Mute state from UPnP."""
        return self.coordinator.data.muted

    async def async_turn_on(self) -> None:
        """Wake from standby, or Wake-on-LAN when the TV is unreachable."""
        coordinator = self.coordinator
        await self._async_call(
            coordinator.tv.power_on(
                coordinator.config_entry.data.get(CONF_MAC), coordinator.wol_target
            )
        )
        await coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Standby."""
        await self._async_call(self.coordinator.tv.power_off())
        # The TV keeps answering for a few seconds while it shuts down.
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, is_on=False, volume=None, muted=None)
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Exact volume through UPnP."""
        level = round(volume * 100)
        await self._async_call(self.coordinator.tv.rendering.set_volume(level))
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, volume=level)
        )

    async def async_mute_volume(self, mute: bool) -> None:  # noqa: FBT001
        """Mute through UPnP (KEY_MUTE only toggles)."""
        await self._async_call(self.coordinator.tv.rendering.set_mute(mute=mute))
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, muted=mute)
        )

    async def async_volume_up(self) -> None:
        """Volume key, so the TV shows its own volume bar."""
        await self._async_key("KEY_VOLUP")

    async def async_volume_down(self) -> None:
        """Volume key, so the TV shows its own volume bar."""
        await self._async_key("KEY_VOLDOWN")

    async def async_media_play(self) -> None:
        """Play key."""
        await self._async_key("KEY_PLAY")

    async def async_media_pause(self) -> None:
        """Pause key."""
        await self._async_key("KEY_PAUSE")

    async def async_media_stop(self) -> None:
        """Stop key."""
        await self._async_key("KEY_STOP")

    async def _async_key(self, key: str) -> None:
        await self._async_call(self.coordinator.tv.send_keys([key]))
        await self.coordinator.async_request_refresh()
