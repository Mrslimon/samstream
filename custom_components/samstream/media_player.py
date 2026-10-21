"""The TV as a media player: power, volume, playback keys and apps."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from aiosamstream import SAMSTREAM_APP_ID, SamstreamConnectionError
from homeassistant.components.camera import async_get_stream_source
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import JsonValueType

from . import SamstreamConfigEntry
from .const import DOMAIN
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package, resolve_package_path
from .stream_relay import async_publish_stream, tv_stream_url
from .tv_session import set_command
from .tv_settings import ensure_tv_secret

PARALLEL_UPDATES = 1
# Wake-on-LAN to a launchable TV usually takes 5-15 s.
WAKE_WAIT_SECONDS = 25
# The TV's REST server drops out for a few seconds after an install.
LAUNCH_ATTEMPTS = 5
LAUNCH_RETRY_SECONDS = 2

FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY_MEDIA
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
        """On or off: the TV does not report whether an app is playing."""
        return (
            MediaPlayerState.ON if self.coordinator.data.is_on else MediaPlayerState.OFF
        )

    @property
    def app_id(self) -> str | None:
        """Tizen ID of the app on screen."""
        return self.coordinator.data.app_id

    @property
    def app_name(self) -> str | None:
        """Name of the app on screen."""
        return self.coordinator.data.app_name

    @property
    def source(self) -> str | None:
        """The app on screen, as a source."""
        return self.coordinator.data.app_name

    @property
    def source_list(self) -> list[str]:
        """Installed apps the TV told us about."""
        return sorted(self.coordinator.apps.values(), key=str.casefold)

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

    async def async_select_source(self, source: str) -> None:
        """Launch the app with this name."""
        for app_id, name in self.coordinator.apps.items():
            if name == source:
                await self.async_launch_app(app_id)
                return
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_source",
            translation_placeholders={"source": source},
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """`media_content_type: app`, `media_content_id: <Tizen app ID>`."""
        if media_type != MediaType.APP:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )
        await self.async_launch_app(media_id)

    async def async_launch_app(self, app_id: str) -> None:
        """Start or bring an app to the front (also the `launch_app` action)."""
        await self._async_call(self.coordinator.tv.launch_app(app_id))
        # Apps need ~3 s to come to the front; show it now, the next poll confirms.
        self.coordinator.async_set_updated_data(
            replace(
                self.coordinator.data,
                app_id=app_id,
                app_name=self.coordinator.apps.get(app_id, app_id),
            )
        )

    async def async_close_app(self, app_id: str) -> None:
        """Close an app (the `close_app` action); the TV returns to what was before."""
        await self._async_call(self.coordinator.tv.close_app(app_id))
        if self.coordinator.data.app_id == app_id:
            self.coordinator.async_set_updated_data(
                replace(self.coordinator.data, app_id=None, app_name=None)
            )

    async def async_play_stream(
        self,
        camera: str | None = None,
        url: str | None = None,
        label: str | None = None,
        message: str | None = None,
    ) -> None:
        """Open Samstream on the TV with a camera (the `play_stream` action)."""
        source = url
        if camera:
            source = await async_get_stream_source(self.hass, camera)
            if not source:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="camera_no_stream",
                    translation_placeholders={"camera": camera},
                )
            if label is None and (state := self.hass.states.get(camera)):
                label = state.name
        if not source:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="stream_source_required"
            )
        entry = self.coordinator.config_entry
        ensure_tv_secret(self.hass, entry)
        name = await async_publish_stream(self.hass, entry, source)
        # The app pulls this when it starts (or within ~2 s if already open):
        # Samsung TVs ignore launch data for sideloaded apps.
        set_command(
            self.hass,
            entry,
            {
                "action": "play",
                "stream": {
                    "label": label or "",
                    "url": tv_stream_url(self.hass, entry, name),
                    "type": "mse",
                },
                "message": message or "",
            },
        )
        if not self.coordinator.data.is_on:
            await self.async_turn_on()
            await self._async_wait_until_on()
        await self._async_launch_samstream()

    async def async_stop_stream(self) -> None:
        """Close Samstream (the `stop_stream` action)."""
        set_command(self.hass, self.coordinator.config_entry, {"action": "stop"})
        await self.async_close_app(SAMSTREAM_APP_ID)

    async def _async_launch_samstream(self) -> None:
        """Open the app, retrying while the TV briefly does not answer."""
        for _ in range(LAUNCH_ATTEMPTS - 1):
            try:
                await self.coordinator.tv.launch_app(SAMSTREAM_APP_ID)
            except SamstreamConnectionError:
                await asyncio.sleep(LAUNCH_RETRY_SECONDS)
            else:
                return
        await self._async_call(self.coordinator.tv.launch_app(SAMSTREAM_APP_ID))

    async def _async_wait_until_on(self) -> None:
        """After waking the TV, give it time to accept the launch."""
        for _ in range(WAKE_WAIT_SECONDS):
            if await self.coordinator.tv.is_on():
                return
            await asyncio.sleep(1)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="tv_did_not_wake"
        )

    async def async_install_app(self, path: str | None = None) -> ServiceResponse:
        """Install Samstream over sdb (the `install_app` action).

        Without `path` the bundled app is signed with HA's certificates; a given
        package is re-signed when signing is set up, else installed as is.
        """
        package = resolve_package_path(self.hass, path) if path else None
        result = await async_install_package(
            self.hass, self.coordinator.config_entry, package
        )
        log: list[JsonValueType] = list(result.lines)
        return {"app_id": result.app_id, "log": log}

    async def _async_key(self, key: str) -> None:
        await self._async_call(self.coordinator.tv.send_keys([key]))
        await self.coordinator.async_request_refresh()
