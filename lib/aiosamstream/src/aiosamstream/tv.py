"""Samsung TV control: pairing, device info, power, remote keys and apps."""

from __future__ import annotations

import asyncio
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
from samsungtvws.remote import ChannelEmitCommand, SendRemoteKey
from websockets.exceptions import WebSocketException

from .const import CLIENT_NAME, REST_PORT, WS_PORT_SECURE
from .exceptions import (
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamError,
    SamstreamTimeoutError,
)
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

    async def power_off(self) -> None:
        """Put the TV in standby."""
        await self.send_keys(["KEY_POWER"])

    async def power_on(self, mac: str | None, wol_target: str = DEFAULT_TARGET) -> None:
        """Wake the TV: KEY_POWER from network standby, Wake-on-LAN otherwise."""
        try:
            info = await self.device_info()
        except SamstreamConnectionError:
            info = None
        if info is not None:
            if info.power_on is False:
                # 2018+ TVs keep the network up in standby and wake on KEY_POWER.
                await self.send_keys(["KEY_POWER"])
            return
        if not mac:
            msg = "The TV is off and its MAC address is unknown, cannot wake it"
            raise SamstreamError(msg)
        await send_magic_packet(mac, target=wol_target)

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
