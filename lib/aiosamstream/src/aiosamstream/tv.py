"""Samsung TV control: pairing, device info, power, remote keys and apps."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from collections.abc import Iterable, Sequence

import aiohttp
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.command import SamsungTVCommand
from samsungtvws.exceptions import (
    ConnectionFailure,
    HttpApiError,
    ResponseError,
    UnauthorizedError,
)
from samsungtvws.remote import ChannelEmitCommand, RemoteControlCommand, SendRemoteKey
from websockets.exceptions import WebSocketException

from .art import ArtConnection
from .const import CLIENT_NAME, REST_PORT, WS_PORT_SECURE
from .exceptions import (
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamError,
    SamstreamTimeoutError,
)
from .lounge import play_youtube
from .models import AppStatus, DeviceInfo
from .upnp import RenderingControl
from .wol import DEFAULT_TARGET, send_magic_packet

DEFAULT_TIMEOUT = 10.0
# Long enough for someone to walk to the TV and press "Allow".
PAIRING_TIMEOUT = 60.0
# The TV drops key presses sent back to back.
KEY_DELAY = 0.3
# The TV's REST server answers empty bodies when hit with many parallel requests.
REST_CONCURRENCY = 3
REST_RETRY_DELAY = 0.3

_CONNECTION_ERRORS = (ConnectionFailure, OSError, WebSocketException, TimeoutError)


# A long press of Power: how a Frame's remote turns it fully off.
FULL_OFF_HOLD_SECONDS = 3.0


class SamsungTV:
    """One Samsung TV, addressed by host, sharing the caller's aiohttp session."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        token: str | None = None,
        name: str = CLIENT_NAME,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Create a client; nothing is sent until a method is awaited."""
        self.host = host
        self._session = session
        self._token = token
        self._name = name
        self._timeout = timeout
        self.rendering = RenderingControl(host, session)
        self._remote: SamsungTVWSAsyncRemote | None = None
        self._remote_lock = asyncio.Lock()
        self._rest_slots = asyncio.Semaphore(REST_CONCURRENCY)

    @property
    def token(self) -> str | None:
        """Pairing token; persist it so the TV only asks once."""
        return self._token

    async def device_info(self) -> DeviceInfo:
        """Read model, network and Developer Mode details (no pairing needed)."""
        try:
            data = await self._rest().rest_device_info()
        except (HttpApiError, TimeoutError) as err:
            msg = f"Cannot reach {self.host}:{REST_PORT}"
            raise SamstreamConnectionError(msg) from err
        return DeviceInfo.from_api(data)

    async def app_status(self, app_id: str) -> AppStatus | None:
        """Status of one app; None when it is not installed."""
        async with self._rest_slots:
            for attempt in range(2):
                try:
                    data = await self._rest().rest_app_status(app_id)
                    break
                except ResponseError as err:
                    if attempt:
                        msg = f"{self.host} gave no usable answer about {app_id}"
                        raise SamstreamConnectionError(msg) from err
                    await asyncio.sleep(REST_RETRY_DELAY)
                except (HttpApiError, TimeoutError) as err:
                    msg = f"Cannot reach {self.host}:{REST_PORT}"
                    raise SamstreamConnectionError(msg) from err
        if not isinstance(data, dict) or "id" not in data:
            return None  # {"code": 404, ...}
        return AppStatus.from_api(app_id, data)

    async def installed_apps(self, app_ids: Iterable[str]) -> list[AppStatus]:
        """Return which of `app_ids` are installed (a few requests at a time).

        An app the TV keeps failing to answer about is left out rather than
        failing the whole scan.
        """
        results = await asyncio.gather(
            *(self.app_status(i) for i in dict.fromkeys(app_ids)),
            return_exceptions=True,
        )
        if results and all(isinstance(r, BaseException) for r in results):
            msg = f"Cannot read apps from {self.host}"
            raise SamstreamConnectionError(msg) from results[0]  # type: ignore[misc]
        return [r for r in results if isinstance(r, AppStatus)]

    async def foreground_app(self, app_ids: Iterable[str]) -> AppStatus | None:
        """Return the app on screen among `app_ids`; None for home or live TV."""
        for status in await self.installed_apps(app_ids):
            if status.visible:
                return status
        return None

    async def launch_app(self, app_id: str, *, meta_tag: str | None = None) -> None:
        """Start (or bring to front) an app.

        REST cannot pass data, so a `meta_tag` (e.g. the Samstream stream payload)
        goes as a DEEP_LINK over the remote channel, where the app reads it from
        its launch request.
        """
        if meta_tag is not None:
            await self._send_commands(
                [ChannelEmitCommand.launch_app(app_id, "DEEP_LINK", meta_tag)]
            )
            return
        try:
            # Typed as a dict upstream, but the TV answers a bare `true`.
            started: object = await self._rest().rest_app_run(app_id)
        except (HttpApiError, TimeoutError) as err:
            msg = f"Cannot reach {self.host}:{REST_PORT}"
            raise SamstreamConnectionError(msg) from err
        if started is not True:
            # Some native apps refuse REST launches; the remote channel works.
            await self._send_commands(
                [ChannelEmitCommand.launch_app(app_id, "NATIVE_LAUNCH")]
            )

    async def cast_youtube(self, video_id: str) -> None:
        """Play a YouTube video on the TV's YouTube app (DIAL launch + Lounge)."""
        await play_youtube(self.host, self._session, video_id, timeout=self._timeout)

    async def close_app(self, app_id: str) -> None:
        """Close an app; the TV returns to what was on screen before it."""
        try:
            await self._rest().rest_app_close(app_id)
        except (HttpApiError, TimeoutError) as err:
            msg = f"Cannot reach {self.host}:{REST_PORT}"
            raise SamstreamConnectionError(msg) from err

    async def pair(self, accept_within: float = PAIRING_TIMEOUT) -> str | None:
        """Open the remote channel, triggering the "Allow" popup if not yet trusted.

        Returns the token to persist; None on TVs that do not use token auth.
        A stored token is sent along, so a trusted client connects silently.
        """
        remote = self._new_remote()
        try:
            async with asyncio.timeout(accept_within):
                await remote.open()
        except UnauthorizedError as err:
            msg = "The TV denied access"
            raise SamstreamAuthError(msg) from err
        except TimeoutError as err:
            msg = f"No answer from {self.host} within {accept_within:.0f}s"
            raise SamstreamTimeoutError(msg) from err
        except _CONNECTION_ERRORS as err:
            msg = f"Cannot open the remote channel on {self.host}:{WS_PORT_SECURE}"
            raise SamstreamConnectionError(msg) from err
        finally:
            await remote.close()

        self._token = remote.token
        return self._token

    async def is_on(self) -> bool:
        """Report whether the screen is on; standby and unreachable count as off."""
        try:
            info = await self.device_info()
        except SamstreamConnectionError:
            return False
        # Pre-2018 TVs report no PowerState and only answer while on.
        return info.power_on is not False

    async def send_keys(
        self,
        keys: Sequence[str],
        *,
        repeats: int = 1,
        delay: float = KEY_DELAY,
        hold: float = 0.0,
    ) -> None:
        """Press remote keys (e.g. KEY_VOLUP) over one kept-open connection."""
        commands: list[SamsungTVCommand] = []
        for _ in range(repeats):
            for key in keys:
                if hold > 0:
                    commands.extend(SendRemoteKey.hold(key, hold))
                else:
                    commands.append(SendRemoteKey.click(key))
        await self._send_commands(commands, delay=delay)

    async def send_text(self, text: str, *, done: bool = True) -> None:
        """Type into the text field that has the on-screen keyboard open.

        Any language (sent as UTF-8). `done` closes the keyboard afterwards, as
        the keyboard's Done key would.
        """
        # The payloads of samsungtvws 2.8's SendInputString / SendInputEnd, built
        # here so older samsungtvws (HA ships 2.7) works too.
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        commands: list[SamsungTVCommand] = [
            RemoteControlCommand(
                {
                    "Cmd": encoded,
                    "DataOfCmd": "base64",
                    "TypeOfRemote": "SendInputString",
                }
            )
        ]
        if done:
            commands.append(RemoteControlCommand({"TypeOfRemote": "SendInputEnd"}))
        await self._send_commands(commands, delay=0)

    async def move_pointer(self, dx: int, dy: int) -> None:
        """Move the TV's pointer by (dx, dy) screen pixels (apps with a pointer)."""
        await self._send_commands(
            [
                RemoteControlCommand(
                    {
                        "Cmd": "Move",
                        "Position": {"x": dx, "y": dy, "Time": "0"},
                        "TypeOfRemote": "ProcessMouseDevice",
                    }
                )
            ],
            delay=0,
        )

    async def click(self, button: str = "left") -> None:
        """Click with the TV's pointer: `left` or `right`."""
        cmd = {"left": "LeftClick", "right": "RightClick"}[button]
        await self._send_commands(
            [RemoteControlCommand({"Cmd": cmd, "TypeOfRemote": "ProcessMouseDevice"})],
            delay=0,
        )

    async def _send_commands(
        self, commands: Sequence[SamsungTVCommand], *, delay: float = KEY_DELAY
    ) -> None:
        async with self._remote_lock:
            # The TV closes idle connections, so a failed send gets one fresh retry.
            for attempt in range(2):
                try:
                    remote = await self._connected_remote()
                    await remote.send_commands(commands, key_press_delay=delay)
                except UnauthorizedError as err:
                    await self._drop_remote()
                    msg = "The TV no longer accepts the pairing token"
                    raise SamstreamAuthError(msg) from err
                except _CONNECTION_ERRORS as err:
                    await self._drop_remote()
                    if attempt:
                        msg = f"Cannot send commands to {self.host}"
                        raise SamstreamConnectionError(msg) from err
                else:
                    return

    async def power_off(self, *, full: bool = False) -> None:
        """Put the TV in standby (a Frame: Art Mode, or fully off with `full`).

        A Frame's remote switches it fully off with a long press of Power.
        """
        if full:
            await self.send_keys(["KEY_POWER"], hold=FULL_OFF_HOLD_SECONDS)
        else:
            await self.send_keys(["KEY_POWER"])

    async def power_on(self, mac: str | None, wol_target: str = DEFAULT_TARGET) -> None:
        """Wake the TV: KEY_POWER from network standby, Wake-on-LAN otherwise."""
        try:
            info = await self.device_info()
        except SamstreamConnectionError:
            info = None
        if info is not None:
            if info.power_on is not False:
                return
            # 2018+ TVs keep the network up in standby and wake on KEY_POWER,
            # but ignore it now and then (e.g. just after going to standby).
            # Wake-on-LAN never turns a TV off, so it is a safe second try.
            await self.send_keys(["KEY_POWER"])
            if mac:
                await send_magic_packet(mac, target=wol_target)
            return
        if not mac:
            msg = "The TV is off and its MAC address is unknown, cannot wake it"
            raise SamstreamError(msg)
        await send_magic_packet(mac, target=wol_target)

    async def wake_on_lan(self, mac: str, wol_target: str = DEFAULT_TARGET) -> None:
        """Send only a Wake-on-LAN packet (safe to repeat; never turns it off)."""
        await send_magic_packet(mac, target=wol_target)

    def art(self) -> ArtConnection:
        """Return an art-app channel (Frame TVs); use `async with tv.art()`."""
        return ArtConnection(
            self.host,
            self._session,
            token=self._token,
            name=self._name,
            timeout=self._timeout,
        )

    async def get_art_mode(self) -> bool:
        """Report whether Art Mode is on now (Frame TVs)."""
        async with self.art() as art:
            return await art.get_art_mode()

    async def set_art_mode(self, *, on: bool, artwork: str | None = None) -> None:
        """Turn Art Mode on/off, optionally selecting `artwork` (a content id)."""
        async with self.art() as art:
            if artwork is not None:
                await art.select(artwork, show=on)
                if not on:
                    await art.set_art_mode(on=False)
            else:
                await art.set_art_mode(on=on)

    async def art_list(self) -> list[dict[str, object]]:
        """Return the stored artwork (each item has a `content_id`)."""
        async with self.art() as art:
            return await art.available()

    async def art_select(self, content_id: str, *, matte: str | None = None) -> None:
        """Show stored artwork `content_id` on a Frame (Art Mode comes on).

        `matte` first changes its border (`none` or `<style>_<colour>`).
        """
        async with self.art() as art:
            if matte is not None:
                await art.change_matte(content_id, matte)
            await art.select(content_id, show=True)

    async def art_thumbnails(
        self, content_ids: list[str]
    ) -> dict[str, tuple[bytes, str]]:
        """Thumbnails of stored artwork, by content id (see `ArtConnection`)."""
        async with self.art() as art:
            return await art.thumbnails(content_ids)

    async def art_upload(
        self,
        image: bytes,
        *,
        file_type: str = "png",
        show: bool = False,
        matte: str = "none",
    ) -> str | None:
        """Upload an image to the Frame's "My Photos"; optionally show it.

        Returns the new artwork's `content_id` (reusable with `set_art_mode`).
        """
        async with self.art() as art:
            content_id = await art.upload(image, file_type=file_type, matte=matte)
            if show and content_id:
                await art.select(content_id, show=True)
            return content_id

    async def toggle_art_mode(self) -> None:
        """Flip a Frame TV between normal TV and Art Mode (the power key).

        The art-app channel is unreliable on newer Frame firmware (2024 sets
        ignore it entirely), but the power key flips TV <-> Art dependably and
        never fully powers the Frame off, so it is the portable control.
        """
        await self.send_keys(["KEY_POWER"])

    async def close(self) -> None:
        """Close the kept-open remote connection."""
        async with self._remote_lock:
            await self._drop_remote()

    def _rest(self) -> SamsungTVAsyncRest:
        return SamsungTVAsyncRest(
            self.host, session=self._session, port=REST_PORT, timeout=self._timeout
        )

    def _new_remote(self) -> SamsungTVWSAsyncRemote:
        return SamsungTVWSAsyncRemote(
            host=self.host,
            port=WS_PORT_SECURE,
            token=self._token,
            name=self._name,
            timeout=self._timeout,
        )

    async def _connected_remote(self) -> SamsungTVWSAsyncRemote:
        if self._remote is None or not self._remote.is_alive():
            await self._drop_remote()
            remote = self._new_remote()
            await remote.open()
            self._remote = remote
            self._token = remote.token or self._token
        return self._remote

    async def _drop_remote(self) -> None:
        remote, self._remote = self._remote, None
        if remote is not None:
            with contextlib.suppress(*_CONNECTION_ERRORS):  # already gone
                await remote.close()
