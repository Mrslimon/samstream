"""The TV as a media player: power, volume, playback keys and apps."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from aiosamstream import SAMSTREAM_APP_ID, SamstreamConnectionError, SamstreamError
from homeassistant.components import media_source
from homeassistant.components.camera import async_get_stream_source
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    async_process_play_media_url,
)
from homeassistant.components.media_player.const import (
    MediaClass,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.json import JsonValueType

from . import SamstreamConfigEntry
from .const import DOMAIN, SOURCE_HOME
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package, resolve_package_path
from .stream_relay import async_publish_stream, tv_stream_url
from .tv_session import current_command, set_command, signal_ended, signal_playing
from .tv_settings import ensure_tv_secret

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
# Wake-on-LAN to a launchable TV usually takes 5-15 s.
WAKE_WAIT_SECONDS = 25
# The TV's REST server drops out now and then (for a few seconds after an install).
LAUNCH_ATTEMPTS = 5
LAUNCH_RETRY_SECONDS = 2
# After reopening the previous app, wait before pressing Play to resume it.
RESUME_DELAY_SECONDS = 3
# `duration` counts from the first frame; if the app never reports one (a
# stream error, an old app), the return still comes this much later.
FIRST_FRAME_WAIT_SECONDS = 30
# Media browser folder with the TV's apps.
APPS_FOLDER = "samstream://apps"


@dataclass
class _Interruption:
    """What the TV showed before Samstream took over, to go back to."""

    was_on: bool
    previous_app: str | None
    return_to_previous: bool


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
    | MediaPlayerEntityFeature.BROWSE_MEDIA
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
        self._interruption: _Interruption | None = None
        self._cancel_return: CALLBACK_TYPE | None = None
        # The camera on screen: its play command, stream, and whether a frame showed.
        self._play_seq: int | None = None
        self._stream_url: str | None = None
        self._frame_seen = False
        self._duration: float | None = None

    async def async_added_to_hass(self) -> None:
        """Listen for the TV app reporting its first frame."""
        await super().async_added_to_hass()
        entry_id = self.coordinator.config_entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_playing(entry_id), self._on_first_frame
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_ended(entry_id), self._on_ended)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Drop a pending timed return."""
        self._cancel_timed_return()
        await super().async_will_remove_from_hass()

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
        """The app on screen, as a source; Home when the TV listed all its apps."""
        data = self.coordinator.data
        if data.app_name is None and data.is_on and self.coordinator.app_source == "tv":
            return SOURCE_HOME
        return data.app_name

    @property
    def entity_picture(self) -> str | None:
        """Logo of the app on screen, if the user added one (see logos.py)."""
        app_id = self.coordinator.data.app_id
        return self.coordinator.logos.get(app_id) if app_id else None

    @property
    def source_list(self) -> list[str]:
        """Home, then the installed apps the TV told us about."""
        return [SOURCE_HOME, *sorted(self.coordinator.apps.values(), key=str.casefold)]

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
        """Launch the app with this name (Home presses the Home key)."""
        if source == SOURCE_HOME:
            await self._async_call(self.coordinator.tv.send_keys(["KEY_HOME"]))
            return
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
        """Launch an app (`app` + Tizen app ID), or play a file on the TV.

        Files are HA media library items (`media-source://…`, including TTS) or
        http(s) URLs. Samstream plays them full screen and, when the file ends,
        the TV returns to what was on before.
        """
        if media_type == MediaType.APP:
            await self.async_launch_app(media_id)
            return
        if not (media_source.is_media_source_id(media_id) or _is_http(media_id)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )
        url, mime = await self._async_media_url(media_id)
        kind = (mime or str(media_type)).split("/", 1)[0]
        audio = kind in {"audio", MediaType.MUSIC}
        extra = kwargs.get("extra") or {}
        title = extra.get("title") or _title_from(media_id)
        await self._async_take_over(
            {
                "action": "media",
                "title": title,
                "url": url,
                "kind": "audio" if audio else "video",
            },
            duration=None,
            return_to_previous=True,
        )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """TV apps (launch) and HA's media library (video and audio to play)."""
        if media_content_id == APPS_FOLDER:
            return self._browse_apps()
        library = await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith(
                ("video/", "audio/")
            ),
        )
        if media_content_id is not None:
            return library
        # Top level: the TV's apps next to the media library.
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id="",
            media_content_type="",
            title=self.coordinator.config_entry.title,
            can_play=False,
            can_expand=True,
            children=[self._browse_apps(children=False), library],
        )

    def _browse_apps(self, *, children: bool = True) -> BrowseMedia:
        apps = sorted(self.coordinator.apps.items(), key=lambda a: a[1].casefold())
        logos = self.coordinator.logos
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id=APPS_FOLDER,
            media_content_type=MediaType.APPS,
            title="Apps",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.APP,
            children=[
                BrowseMedia(
                    media_class=MediaClass.APP,
                    media_content_id=app_id,
                    media_content_type=MediaType.APP,
                    title=name,
                    can_play=True,
                    can_expand=False,
                    thumbnail=logos.get(app_id),
                )
                for app_id, name in apps
            ]
            if children
            else None,
        )

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

    async def async_play_stream(  # noqa: PLR0913 - one argument per action field
        self,
        *,
        camera: str | None = None,
        url: str | None = None,
        label: str | None = None,
        message: str | None = None,
        duration: float | None = None,
        return_to_previous: bool = True,
    ) -> None:
        """Open Samstream on the TV with a camera (the `play_stream` action).

        Remembers what was on screen (pausing that app) so `stop_stream`, or the
        end of `duration`, returns there. A second call while the camera shows
        keeps the original place to go back to.
        """
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
        stream_url = tv_stream_url(self.hass, entry, name)
        await self._async_take_over(
            {
                "action": "play",
                "stream": {"label": label or "", "url": stream_url, "type": "mse"},
                "message": message or "",
            },
            duration=duration,
            return_to_previous=return_to_previous,
            stream_url=stream_url,
        )

    async def async_show_message(  # noqa: PLR0913 - one argument per action field
        self,
        *,
        message: str = "",
        title: str = "",
        severity: str = "info",
        sound: str | dict[str, Any] | None = None,
        duration: float | None = None,
        return_to_previous: bool = True,
    ) -> None:
        """Show a full-screen message on the TV (the `show_message` action)."""
        if not message and not title:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="message_required"
            )
        sound_url = None
        if sound:
            media_id = sound["media_content_id"] if isinstance(sound, dict) else sound
            sound_url, _mime = await self._async_media_url(str(media_id))
        await self._async_take_over(
            {
                "action": "notice",
                "title": title,
                "message": message,
                "severity": severity,
                "sound": sound_url,
            },
            duration=duration,
            return_to_previous=return_to_previous,
        )

    async def _async_take_over(
        self,
        command: dict[str, Any],
        *,
        duration: float | None,
        return_to_previous: bool,
        stream_url: str | None = None,
    ) -> None:
        """Queue `command`, open Samstream over what is on screen, plan the return.

        `duration` starts when the TV reports the command on screen (first camera
        frame, notice shown, video started).
        """
        entry = self.coordinator.config_entry
        ensure_tv_secret(self.hass, entry)
        # The app pulls this when it starts (or within ~2 s if already open):
        # Samsung TVs ignore launch data for sideloaded apps.
        seq = set_command(self.hass, entry, command)
        if self._interruption is None:
            self._interruption = await self._async_remember_screen(
                pause=return_to_previous
            )
        else:
            self._interruption.return_to_previous = return_to_previous
        try:
            if not self.coordinator.data.is_on:
                await self.async_turn_on()
                await self._async_wait_until_on()
            await self._async_launch(SAMSTREAM_APP_ID)
        except HomeAssistantError:
            self._interruption = None
            raise
        # The same camera already on screen only changes its text: no new frame.
        if not (
            self._frame_seen
            and stream_url is not None
            and stream_url == self._stream_url
        ):
            self._frame_seen = False
        self._play_seq, self._stream_url, self._duration = seq, stream_url, duration
        self._cancel_timed_return()
        if duration:
            wait = 0 if self._frame_seen else FIRST_FRAME_WAIT_SECONDS
            self._schedule_return(duration + wait)

    async def _async_media_url(self, media_id: str) -> tuple[str, str | None]:
        """Return a URL the TV can fetch (signed if it is HA's) and its MIME type."""
        mime = None
        if media_source.is_media_source_id(media_id):
            try:
                play = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id
                )
            except media_source.Unresolvable as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="media_unresolvable",
                    translation_placeholders={"error": str(err)},
                ) from err
            media_id, mime = play.url, play.mime_type
        return async_process_play_media_url(self.hass, media_id), mime

    async def async_update_message(self, message: str) -> None:
        """Change the text of the camera or message on screen (`update_message`).

        The camera keeps playing. Without a camera on the TV nothing happens, so
        a slow automation (an AI description) cannot reopen a closed camera.
        """
        command = current_command(self.hass, self.coordinator.config_entry)
        if command is None or command.get("action") not in {"play", "notice"}:
            _LOGGER.debug("No camera on %s; message not shown", self.entity_id)
            return
        # Re-sent as the same play: an app that starts late still gets the camera.
        set_command(
            self.hass, self.coordinator.config_entry, {**command, "message": message}
        )

    async def async_stop_stream(self) -> None:
        """Leave the camera (the `stop_stream` action): back to what was before."""
        self._cancel_timed_return()
        self._play_seq, self._stream_url, self._frame_seen = None, None, False
        interruption, self._interruption = self._interruption, None
        returning = interruption is not None and interruption.return_to_previous
        # Look before the app sees "stop": it closes itself then.
        in_front = await self._async_samstream_in_front() if returning else True
        set_command(self.hass, self.coordinator.config_entry, {"action": "stop"})
        if interruption is None or not interruption.return_to_previous:
            await self.async_close_app(SAMSTREAM_APP_ID)
            return
        if not in_front:
            # The viewer already left (Back, another app): do not pull them back.
            return
        if not interruption.was_on:
            await self.async_turn_off()
        elif interruption.previous_app is not None:
            await self._async_launch(interruption.previous_app)
            await asyncio.sleep(RESUME_DELAY_SECONDS)
            with contextlib.suppress(SamstreamError):
                await self.coordinator.tv.send_keys(["KEY_PLAY"])
        else:
            # Home or Live TV was underneath; closing the app returns there.
            await self.async_close_app(SAMSTREAM_APP_ID)
        await self.coordinator.async_request_refresh()

    async def _async_remember_screen(self, *, pause: bool) -> _Interruption:
        """Note what is on screen now and pause it (if it is an app)."""
        if not self.coordinator.data.is_on:
            return _Interruption(
                was_on=False, previous_app=None, return_to_previous=pause
            )
        try:
            previous = await self.coordinator.async_current_app()
        except SamstreamError:
            previous = None
        if previous == SAMSTREAM_APP_ID:
            previous = None
        if previous is not None and pause:
            with contextlib.suppress(SamstreamError):
                await self.coordinator.tv.send_keys(["KEY_PAUSE"])
        return _Interruption(
            was_on=True, previous_app=previous, return_to_previous=pause
        )

    async def _async_samstream_in_front(self) -> bool:
        try:
            status = await self.coordinator.tv.app_status(SAMSTREAM_APP_ID)
        except SamstreamError:
            return True  # Unknown: act as asked.
        return status is None or status.visible

    @callback
    def _on_first_frame(self, seq: int) -> None:
        """Start `duration` now: the TV shows the camera."""
        if self._play_seq is None or seq < self._play_seq or self._frame_seen:
            return
        self._frame_seen = True
        if self._duration and self._cancel_return is not None:
            self._cancel_timed_return()
            self._schedule_return(self._duration)

    @callback
    def _on_ended(self, seq: int) -> None:
        """Go back now: a video from the media library ended."""
        if seq != self._play_seq:
            return
        self._cancel_timed_return()
        self.hass.async_create_task(self._async_timed_return(None))

    def _schedule_return(self, delay: float) -> None:
        self._cancel_return = async_call_later(
            self.hass, delay, self._async_timed_return
        )

    def _cancel_timed_return(self) -> None:
        if self._cancel_return is not None:
            self._cancel_return()
            self._cancel_return = None

    async def _async_timed_return(self, _now: datetime | None) -> None:
        self._cancel_return = None
        try:
            await self.async_stop_stream()
        except HomeAssistantError as err:
            _LOGGER.warning("Could not return from the camera: %s", err)

    async def _async_launch(self, app_id: str) -> None:
        """Open an app, retrying while the TV's REST server briefly drops out."""
        for _ in range(LAUNCH_ATTEMPTS - 1):
            try:
                await self.coordinator.tv.launch_app(app_id)
            except SamstreamConnectionError:
                await asyncio.sleep(LAUNCH_RETRY_SECONDS)
            else:
                return
        await self._async_call(self.coordinator.tv.launch_app(app_id))

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


def _is_http(media_id: str) -> bool:
    return media_id.startswith(("http://", "https://"))


def _title_from(media_id: str) -> str:
    """File name without folders, query or extension, as a fallback title."""
    name = media_id.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name
