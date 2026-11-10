"""The TV as a media player: power, volume, playback keys and apps."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from aiosamstream import (
    SAMSTREAM_APP_ID,
    OcfError,
    SamstreamConnectionError,
    SamstreamError,
    youtube_id,
)
from aiosamstream.ocf import OcfTvState
from aiosamstream.ocf.coap_tcp import GET, POST, code_text, code_value
from homeassistant.components import media_source
from homeassistant.components.camera import async_get_stream_source
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    async_process_play_media_url,
)
from homeassistant.components.media_player.const import (
    MediaClass,
    MediaPlayerDeviceClass,
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
from .art_gallery import CONTENT_ID, upload_url
from .art_gallery import describe as describe_art
from .const import (
    CONF_FRAME_POWER,
    CONF_RESUME,
    CONF_TV_CORNER,
    DEFAULT_TV_CORNER,
    DOMAIN,
    SOURCE_HOME,
    SOURCE_KEYS,
)
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import (
    async_install_package,
    async_uninstall_package,
    resolve_package_path,
)
from .keys import normalize_key
from .stream_relay import async_publish_stream, tv_mjpeg_url, tv_stream_url
from .tv_session import (
    current_command,
    set_command,
    signal_closed,
    signal_ended,
    signal_playing,
    signal_source,
)
from .tv_settings import ensure_tv_secret

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1
# Wake-on-LAN to a launchable TV usually takes 5-15 s.
WAKE_WAIT_SECONDS = 25
# While waiting, Wake-on-LAN is sent again this often.
WOL_REPEAT_SECONDS = 8
# Standby shows within a few seconds of the Power key.
OFF_WAIT_SECONDS = 6
# The TV's REST server drops out now and then (for a few seconds after an install).
LAUNCH_ATTEMPTS = 5
LAUNCH_RETRY_SECONDS = 2
# After reopening the previous app, wait before pressing Play to resume it.
RESUME_DELAY_SECONDS = 3
# `duration` counts from the first frame; if the app never reports one (a
# stream error, an old app), the return still comes this much later.
FIRST_FRAME_WAIT_SECONDS = 30
# Local control: how long to wait for the TV to re-dial the cloud.
RECONNECT_WAIT_SECONDS = 30
# Media browser folder with the TV's apps.
APPS_FOLDER = "samstream://apps"
ART_FOLDER = "samstream://art"
ART_TYPE = "samstream_art"  # play_media type: show a Frame artwork by content id


@dataclass
class _Interruption:
    """What the TV showed before Samstream took over, to go back to."""

    was_on: bool
    previous_app: str | None
    return_to_previous: bool
    # Press Play when going back: False when the app was already paused.
    resume: bool = True
    # The input under Samstream, as the TV app reported it ("TV1", "HDMI2").
    tv_source: str | None = None


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


def _art_folder() -> BrowseMedia:
    return BrowseMedia(
        media_class=MediaClass.DIRECTORY,
        media_content_id=ART_FOLDER,
        media_content_type=ART_TYPE,
        title="Art",
        can_play=False,
        can_expand=True,
        children_media_class=MediaClass.IMAGE,
    )


class SamstreamMediaPlayer(SamstreamEntity, MediaPlayerEntity):
    """Main entity of the TV device."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = FEATURES

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the media player for the coordinator's TV."""
        super().__init__(coordinator, "media_player")
        self._interruption: _Interruption | None = None
        # App (or "" for none) on screen when we last sent Pause; None after Play.
        self._paused_app: str | None = None
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
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_closed(entry_id), self._on_closed
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_source(entry_id), self._on_tv_source
            )
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
        """The app on screen, as a source; Home when the TV listed all its apps.

        With local control the TV names its input itself (Live TV, HDMI 2),
        which the remote-key guess cannot tell apart.
        """
        data = self.coordinator.data
        if (input_name := _ocf_input_name(data.ocf)) is not None:
            return input_name
        if data.app_name is None and data.is_on and self.coordinator.app_source == "tv":
            return SOURCE_HOME
        return data.app_name

    @property
    def media_content_type(self) -> MediaType | None:
        """A channel while Live TV is on (local control), an app otherwise."""
        ocf = self.coordinator.data.ocf
        if _on_channel(ocf):
            return MediaType.CHANNEL
        return MediaType.APP if self.coordinator.data.app_id else None

    @property
    def media_title(self) -> str | None:
        """The programme on Live TV, or the app's own title (local control)."""
        ocf = self.coordinator.data.ocf
        if ocf is None or ocf.content_input == "webapp":
            return None
        return ocf.content_title

    @property
    def media_channel(self) -> str | None:
        """Channel name (or number) on Live TV, as the TV reports it."""
        ocf = self.coordinator.data.ocf
        if ocf is None or not _on_channel(ocf):
            return None
        return ocf.channel_name or ocf.channel_number

    @property
    def entity_picture(self) -> str | None:
        """Logo of the app on screen, if the user added one (see logos.py)."""
        app_id = self.coordinator.data.app_id
        return self.coordinator.logos.get(app_id) if app_id else None

    @property
    def source_list(self) -> list[str]:
        """Home, the inputs (the TV's own list with local control), then the apps."""
        apps = sorted(self.coordinator.apps.values(), key=str.casefold)
        ocf = self.coordinator.data.ocf
        if ocf is not None and ocf.input_sources:
            return [SOURCE_HOME, *(name for _id, name in ocf.input_sources), *apps]
        return [*SOURCE_KEYS, *apps]

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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Mark Frames, so the card offers its Art section."""
        return {"frame_tv": True} if self._frame else None

    @property
    def _frame(self) -> bool:
        info = self.coordinator.data.info
        return bool(info and info.frame_tv)

    def _power_off(self) -> Any:
        """Power key press for "off": a Frame goes to Art Mode unless set to off."""
        full = self._frame and (
            self.coordinator.config_entry.options.get(CONF_FRAME_POWER, "art") == "off"
        )
        return self.coordinator.tv.power_off(full=full)

    async def async_turn_off(self) -> None:
        """Standby (a Frame: Art Mode, or fully off when set so)."""
        await self._async_call(self._power_off())
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
        self._paused_app = None

    async def async_media_pause(self) -> None:
        """Pause key."""
        await self._async_key("KEY_PAUSE")
        self._paused_app = self.coordinator.data.app_id or ""

    async def async_media_play_pause(self) -> None:
        """Toggle: the TV does not report playback, so undo our own last key.

        The first press pauses; the next one plays, unless the app on screen
        changed in between (then it pauses again).
        """
        if self._paused_app == (self.coordinator.data.app_id or ""):
            await self.async_media_play()
        else:
            await self.async_media_pause()

    async def async_media_stop(self) -> None:
        """Stop key."""
        await self._async_key("KEY_STOP")

    async def async_select_source(self, source: str) -> None:
        """Launch the app with this name; switch input by id (local control) or key."""
        ocf, device = self.coordinator.data.ocf, self.coordinator.ocf_device
        if ocf is not None and device is not None and source != SOURCE_HOME:
            for source_id, name in ocf.input_sources:
                if name == source:
                    await self._async_call(_sent(device.select_input(source_id)))
                    return
        if key := SOURCE_KEYS.get(source):
            await self._async_call(self.coordinator.tv.send_keys([key]))
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
        """Launch an app, show Frame artwork, or play a file on the TV.

        `app` + Tizen app ID launches it; `samstream_art` + content ID shows that
        artwork on a Frame (the media browser's Art folder).

        Files are HA media library items (`media-source://…`, including TTS) or
        http(s) URLs. Samstream plays them full screen and, when the file ends,
        the TV returns to what was on before.
        """
        if media_type == MediaType.APP:
            await self.async_launch_app(media_id)
            return
        if media_type == ART_TYPE and CONTENT_ID.match(media_id):
            await self.async_select_art(media_id)
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
        """TV apps (launch), Frame artwork (show) and HA's media library."""
        if media_content_id == APPS_FOLDER:
            return self._browse_apps()
        if media_content_id == ART_FOLDER:
            return await self._async_browse_art()
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
            children=[
                self._browse_apps(children=False),
                *([_art_folder()] if self._frame else []),
                library,
            ],
        )

    async def _async_browse_art(self) -> BrowseMedia:
        """Browse the Frame's stored artwork as a thumbnail grid; play shows one."""
        listing = await self.async_list_art()
        items: list[dict[str, Any]] = listing["art"]  # type: ignore[assignment,index]
        folder = _art_folder()
        folder.children = [
            BrowseMedia(
                media_class=MediaClass.IMAGE,
                media_content_id=item["content_id"],
                media_content_type=ART_TYPE,
                title=item["content_id"],
                can_play=True,
                can_expand=False,
                thumbnail=item["thumbnail"],
            )
            for item in items
        ]
        return folder

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
        camera: str,
        label: str | None = None,
        message: str | None = None,
        duration: float | None = None,
        return_to_previous: bool = True,
        tv_corner: str = "off",
    ) -> None:
        """Open Samstream on the TV with a camera (the `play_stream` action).

        Camera entities only, not a free-form URL: a raw stream URL field
        would let any non-admin caller point Home Assistant's ffmpeg at an
        arbitrary host, which a camera entity's own access control already
        prevents.

        Remembers what was on screen (pausing that app) so `stop_stream`, or the
        end of `duration`, returns there. A second call while the camera shows
        keeps the original place to go back to.
        """
        source = await async_get_stream_source(self.hass, camera)
        if not source:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="camera_no_stream",
                translation_placeholders={"camera": camera},
            )
        if label is None and (state := self.hass.states.get(camera)):
            label = state.name
        entry = self.coordinator.config_entry
        ensure_tv_secret(self.hass, entry)
        name = await async_publish_stream(self.hass, entry, source)
        stream_url = tv_stream_url(self.hass, entry, name)
        stream: dict[str, Any] = {
            "label": label or "",
            "url": stream_url,
            "type": "mse",
        }
        corner = await self._async_corner(tv_corner)
        if corner is not None:
            # Pictures, not video: the TV's picture needs the video layer.
            stream["mjpeg_url"] = tv_mjpeg_url(self.hass, entry, name)
        await self._async_take_over(
            {
                "action": "play",
                "stream": stream,
                "message": message or "",
                # Live TV / HDMI keeps playing in this corner (TV Window API).
                "tv_corner": corner,
            },
            duration=duration,
            return_to_previous=return_to_previous,
            stream_url=stream_url,
        )

    async def _async_corner(self, requested: str) -> str | None:
        """Corner for the TV's own picture, or None for the normal camera.

        Only over Live TV, an HDMI input or Home (no app in front), or a TV that
        is off: the TV window shows the TV's input, so over an app it would
        replace that app with Live TV.
        """
        if requested == "off":
            return None
        corner = (
            self.coordinator.config_entry.options.get(CONF_TV_CORNER, DEFAULT_TV_CORNER)
            if requested == "on"
            else requested
        )
        if self._interruption is not None:
            previous = self._interruption.previous_app
        elif not self.coordinator.data.is_on:
            return corner
        else:
            try:
                previous = await self.coordinator.async_current_app()
            except SamstreamError:
                return None  # Unknown: the normal camera is always safe.
        if previous not in (None, SAMSTREAM_APP_ID):
            _LOGGER.debug(
                "%s shows %s: camera without the corner", self.entity_id, previous
            )
            return None
        return corner

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
                # Show it as on now, not at the next poll.
                await self.coordinator.async_request_refresh()
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
            # Close Samstream first: switching apps while turning off can
            # swallow the Power key.
            with contextlib.suppress(HomeAssistantError):
                await self.async_close_app(SAMSTREAM_APP_ID)
            await self._async_turn_off_verified()
        elif interruption.previous_app is not None:
            await self._async_launch(interruption.previous_app)
            if interruption.resume:
                await asyncio.sleep(RESUME_DELAY_SECONDS)
                with contextlib.suppress(SamstreamError):
                    await self.coordinator.tv.send_keys(["KEY_PLAY"])
        else:
            # Home or Live TV was underneath: closing the app returns to Home,
            # so press the input's key when the TV app reported it.
            await self.async_close_app(SAMSTREAM_APP_ID)
            if key := source_key(interruption.tv_source):
                with contextlib.suppress(SamstreamError):
                    await self.coordinator.tv.send_keys([key])
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
        # The TV does not report playback; a pause sent through HA (card,
        # automation) is the one thing known. Paused stays paused afterwards.
        paused = previous is not None and self._paused_app == previous
        resume = (
            previous is not None
            and not paused
            and self.coordinator.config_entry.options.get(CONF_RESUME, True)
        )
        if resume and pause:
            with contextlib.suppress(SamstreamError):
                await self.coordinator.tv.send_keys(["KEY_PAUSE"])
        return _Interruption(
            was_on=True,
            previous_app=previous,
            return_to_previous=pause,
            resume=resume,
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

    @callback
    def _on_tv_source(self, seq: int, source: str) -> None:
        """Remember the input under Samstream (corner mode) to return to it."""
        if seq == self._play_seq and self._interruption is not None:
            self._interruption.tv_source = source

    @callback
    def _on_closed(self, seq: int) -> None:
        """Resume the app underneath: the viewer pressed Back on the TV."""
        if seq != self._play_seq or self._interruption is None:
            return
        interruption, self._interruption = self._interruption, None
        self._cancel_timed_return()
        self._play_seq, self._stream_url, self._frame_seen = None, None, False
        if interruption.previous_app and interruption.resume:
            self.hass.async_create_task(self._async_resume_after_back())

    async def _async_resume_after_back(self) -> None:
        await asyncio.sleep(RESUME_DELAY_SECONDS)
        with contextlib.suppress(SamstreamError):
            await self.coordinator.tv.send_keys(["KEY_PLAY"])
        await self.coordinator.async_request_refresh()

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
        coordinator = self.coordinator
        mac = coordinator.config_entry.data.get(CONF_MAC)
        for second in range(WAKE_WAIT_SECONDS):
            if await coordinator.tv.is_on():
                return
            if mac and second and second % WOL_REPEAT_SECONDS == 0:
                # A missed wake-up: Wake-on-LAN again (never turns it off).
                with contextlib.suppress(SamstreamError, OSError):
                    await coordinator.tv.wake_on_lan(mac, coordinator.wol_target)
            await asyncio.sleep(1)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="tv_did_not_wake"
        )

    async def _async_turn_off_verified(self) -> None:
        """Back to standby (Samstream woke the TV); check it, retry once."""
        tv = self.coordinator.tv
        if self._frame:
            # A Frame reports "on" in Art Mode too: a retry would flip it back.
            await self._async_call(self._power_off())
            return
        for _attempt in range(2):
            await self._async_call(tv.power_off())
            for _ in range(OFF_WAIT_SECONDS):
                await asyncio.sleep(1)
                if not await tv.is_on():
                    self.coordinator.async_set_updated_data(
                        replace(self.coordinator.data, is_on=False)
                    )
                    return
        _LOGGER.warning("%s did not go back to standby", self.entity_id)

    def _require_frame(self) -> None:
        if not self._frame:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_frame"
            )

    async def async_select_art(self, content_id: str, matte: str | None = None) -> None:
        """Show one stored artwork on a Frame (the `select_art` action).

        `matte` (`none` or `<style>_<colour>`) changes its border first.
        """
        self._require_frame()
        await self._async_call(self.coordinator.tv.art_select(content_id, matte=matte))
        await self.coordinator.async_request_refresh()

    async def async_list_art(self, category: str | None = None) -> ServiceResponse:
        """Return a Frame's stored artwork with thumbnail links (`list_art`).

        Each item has its `content_id` (for `select_art`) and a signed
        `thumbnail` link valid for a day, so a dashboard can show a picker.
        `mattes` lists the borders the TV offers (styles, colours as RGB) and
        `upload_url` is where the card POSTs a cropped picture.
        """
        self._require_frame()
        tv = self.coordinator.tv

        async def _listing() -> tuple[list[dict[str, Any]], str | None, Any]:
            async with tv.art() as art:
                items = await art.available(category)
                return items, await art.current(), await art.mattes()

        items, current, (styles, colours) = await self._async_call(_listing())
        entry_id = self.coordinator.config_entry.entry_id
        return {
            "current": current,
            "art": describe_art(self.hass, entry_id, items),  # type: ignore[dict-item]
            "mattes": {
                "styles": styles,
                "colours": {name: list(rgb) for name, rgb in colours.items()},
            },
            "upload_url": upload_url(entry_id),
        }

    async def async_upload_art(
        self, path: str, *, show: bool = False
    ) -> ServiceResponse:
        """Upload an image to a Frame's "My Photos" (the `upload_art` action).

        `path` is an image file in the HA config dir. The new artwork's id is
        returned so it can be shown later; `show: true` switches to it at once.
        The user can also pick it from Art Mode on the TV.
        """
        self._require_frame()
        resolved = await resolve_package_path(self.hass, path)
        suffix = resolved.suffix.lower().lstrip(".")
        file_type = "jpg" if suffix in ("jpg", "jpeg") else "png"
        try:
            image = await self.hass.async_add_executor_job(resolved.read_bytes)
        except OSError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="art_file_unreadable",
                translation_placeholders={"path": path, "error": str(err)},
            ) from err
        content_id = await self._async_call(
            self.coordinator.tv.art_upload(image, file_type=file_type, show=show)
        )
        if show:
            await self.coordinator.async_request_refresh()
        return {"content_id": content_id}

    async def async_install_app(self, path: str | None = None) -> ServiceResponse:
        """Install Samstream over sdb (the `install_app` action).

        Without `path` the bundled app is signed with HA's certificates; a given
        package is re-signed when signing is set up, else installed as is.
        """
        package = await resolve_package_path(self.hass, path) if path else None
        result = await async_install_package(
            self.hass, self.coordinator.config_entry, package
        )
        log: list[JsonValueType] = list(result.lines)
        return {"app_id": result.app_id, "log": log}

    async def async_uninstall_app(self) -> ServiceResponse:
        """Remove both Samstream apps from the TV (the `uninstall_app` action)."""
        removed = await async_uninstall_package(
            self.hass, self.coordinator.config_entry
        )
        removed_ids: list[JsonValueType] = list(removed)
        return {"removed": removed_ids}

    async def async_local_control_request(
        self, *, method: str, resource: str, body: dict[str, Any] | None = None
    ) -> ServiceResponse:
        """Read or write one local-control resource (`local_control_request`)."""
        device = self.coordinator.ocf_device
        if device is None or not await device.wait_connected(RECONNECT_WAIT_SECONDS):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="local_control_unavailable"
            )
        try:
            if method == "get":
                code, answer = await device.request(GET, resource)
            elif method == "reply":
                # Set (or with no body, clear) our answer to the TV's own
                # request for `resource`: body = {"code": "2.05", "body": ...}.
                if resource == "/samstream/drop":  # make the TV sign in again
                    device.drop()
                elif resource == "/samstream/observe_state":  # experiment switch
                    device.observe_state = bool((body or {}).get("body", True))
                elif body is None:
                    device.replies.pop(resource, None)
                else:
                    device.replies[resource] = (
                        code_value(str(body.get("code", "2.05"))),
                        body.get("body"),
                    )
                replies: list[JsonValueType] = [*sorted(device.replies)]
                return {"code": "set", "body": {"replies": replies}}
            elif method == "push":
                # Notify the TV on its own subscription (e.g. /service/observe).
                held = await device.push(resource, body or {})
                subscriptions: list[JsonValueType] = list(held)
                return {"code": "pushed", "body": {"subscriptions": subscriptions}}
            else:
                code, answer = await device.request(POST, resource, body or {})
        except OcfError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        return {"code": code_text(code), "body": _json_safe(answer)}

    async def async_send_text(self, *, text: str, done: bool = True) -> None:
        """Type into the TV's on-screen keyboard (the `send_text` action)."""
        await self._async_call(self.coordinator.tv.send_text(text, done=done))

    async def async_send_keys(
        self, *, keys: list[str], repeats: int = 1, delay: float = 0.4, hold: float = 0
    ) -> None:
        """Press remote keys in order (the `send_keys` action)."""
        await self._async_call(
            self.coordinator.tv.send_keys(
                [normalize_key(key) for key in keys],
                repeats=repeats,
                delay=delay,
                hold=hold,
            )
        )

    async def async_hold_key(self, key: str, seconds: float) -> None:
        """Press and hold a remote key (the `hold_key` action)."""
        await self._async_call(
            self.coordinator.tv.send_keys([normalize_key(key)], hold=seconds)
        )

    async def async_pointer(
        self, move_x: int = 0, move_y: int = 0, click: str | None = None
    ) -> None:
        """Move the TV's pointer and/or click (the `pointer` action)."""
        tv = self.coordinator.tv
        if move_x or move_y:
            await self._async_call(tv.move_pointer(move_x, move_y))
        if click:
            await self._async_call(tv.click(click))

    async def async_open_url(self, *, url: str) -> None:
        """Open a link on the TV (the `open_url` action).

        A YouTube link opens the YouTube app on that video; any other URL opens
        the TV's web browser. Samstream opens the app from the inside (Tizen app
        control), because the TV ignores a remote launch that carries a URL.
        """
        video = youtube_id(url)
        if not video and not url.lower().startswith(("http://", "https://")):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="url_required"
            )
        if not self.coordinator.data.is_on:
            await self.async_turn_on()
            await self._async_wait_until_on()
            await self.coordinator.async_request_refresh()
        # Casting leaves Samstream behind another app: no camera return to keep.
        self._cancel_timed_return()
        self._interruption = None
        if video:
            # YouTube plays a chosen video over the Lounge protocol (HA-side);
            # the Samstream app is not involved.
            await self._async_call(self.coordinator.tv.cast_youtube(video))
            return
        # Any other URL opens in the TV browser, launched by the Samstream app
        # (Tizen app-control), because the TV ignores a remote launch with a URL.
        entry = self.coordinator.config_entry
        ensure_tv_secret(self.hass, entry)
        set_command(self.hass, entry, {"action": "open", "url": url})
        await self._async_launch(SAMSTREAM_APP_ID)

    async def async_art_mode(self) -> None:
        """Toggle Art Mode on a Frame TV (the `art_mode` action).

        The power key flips the Frame between normal TV and Art Mode without
        turning it fully off. Selecting the artwork needs SmartThings and is not
        possible over the local channel on newer Frames.
        """
        await self._async_call(self.coordinator.tv.toggle_art_mode())
        await self.coordinator.async_request_refresh()

    async def _async_key(self, key: str) -> None:
        await self._async_call(self.coordinator.tv.send_keys([key]))
        await self.coordinator.async_request_refresh()


def _ocf_input_name(ocf: OcfTvState | None) -> str | None:
    """Display name of the input on screen, None while an app is in front."""
    if ocf is None or not ocf.input_source or ocf.content_input in (None, "webapp"):
        return None
    for source_id, name in ocf.input_sources:
        if source_id == ocf.input_source:
            return name
    return ocf.input_source


def _on_channel(ocf: OcfTvState | None) -> bool:
    return (
        ocf is not None
        and ocf.content_input not in (None, "webapp")
        and bool(ocf.channel_name or ocf.channel_number)
    )


async def _sent(command: Awaitable[int]) -> None:
    """Send an OCF write; the TV acts even when it answers an error code."""
    await command


def _json_safe(value: Any) -> JsonValueType:
    """CBOR answers may hold bytes; a service response must be JSON."""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _is_http(media_id: str) -> bool:
    return media_id.startswith(("http://", "https://"))


def _title_from(media_id: str) -> str:
    """File name without folders, query or extension, as a fallback title."""
    name = media_id.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def source_key(source: str | None) -> str | None:
    """Remote key for an input the TV app reported ("TV1" -> KEY_TV)."""
    if not source:
        return None
    if source.startswith("TV"):
        return "KEY_TV"
    if source.startswith("HDMI") and source[4:].isdigit():
        return f"KEY_HDMI{source[4:]}"
    return None
