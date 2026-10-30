"""A local OCF cloud: the TV dials it over TLS (CoAP over TCP) and we read its state.

Once onboarding has pointed a TV's `/CoapCloudConfResURI` `cis` at this server
(and installed our CA and a cloud-UUID ACL entry), the TV signs up, signs in
and then answers the cloud's reads of `/sec/tv/*` (input, app, volume, power,
...), which it refuses on the local DTLS channel. See
docs/ocf-local-protocol.md section 14.

Only TVs that were allowed with `OcfCloud.allow` are served: sign-up and
sign-in must carry that TV's device id and access token (compared in constant
time); anything else gets 4.01 and the connection is closed. The TV drops and
re-dials the connection every few seconds, so each TV is a `CloudDevice` that
outlives its connections and keeps the last state.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from aiosamstream.exceptions import OcfError, OcfNotConnectedError

from . import cbor
from .coap_tcp import (
    ABORT,
    CBOR_FORMAT,
    CHANGED,
    CONTENT,
    CONTENT_FORMAT,
    CSM,
    CSM_MAX_MESSAGE_SIZE,
    GET,
    OBSERVE,
    PING,
    PONG,
    POST,
    RELEASE,
    UNAUTHORIZED,
    URI_QUERY,
    VALID,
    CoapError,
    FrameReader,
    Message,
    code_text,
    encode,
    is_request,
    is_success,
    path_options,
    uint,
)
from .state import (
    AUDIO,
    DEVICE_COMMAND,
    INPUT_SOURCE,
    LAUNCH_APP,
    MEDIA_OUTPUT,
    PICTURE_MODE,
    SOUND_MODE,
    STATE_RESOURCES,
    SWITCH,
    SWITCH_ART,
    VIRTUAL_REMOTE,
    OcfTvState,
    apply,
)

if TYPE_CHECKING:
    import ssl

_LOGGER = logging.getLogger(__name__)

SIGN_UP = "/oic/account"
SIGN_IN = "/oic/account/session"
TOKEN_REFRESH = "/oic/account/tokenrefresh"
PUBLISH = "/oic/rd"
KEEP_ALIVE = "/oic/ping"

AUTH_DEADLINE = 15.0  # a connection must sign in within this, or it is closed
IDLE_PING = 20.0  # send a ping after this much silence; the TV never closes for it
READ_INTERVAL = 5.0  # re-read the state at most this often across reconnects
REQUEST_TIMEOUT = 10.0
MAX_CONNECTIONS = 8
MAX_PENDING = 64
# Large enough for the biggest replies (/oic/res); at 1152 the Frame dropped
# the connection instead of answering it.
_CSM_SIZE = 1 << 16
# Long-lived: with 3600 or -1 the TV refreshed its token at every sign-in, and a
# refresh makes it sign out and dial again (a reconnect every second).
_TOKEN_EXPIRY = 365 * 24 * 3600

Listener = Callable[["CloudDevice"], None]


def _decode(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return cbor.loads(payload)
    except cbor.CborError:
        return None


def _field(body: Any, key: str) -> str:
    value = body.get(key) if isinstance(body, dict) else None
    return value if isinstance(value, str) else ""


# Not read by `read_all`: security, account and discovery plumbing.
_NOT_READ = ("/oic/sec/", "/oic/account", "/oic/rd", "/oic/res")
# Resources a Samsung TV listed in /oic/res (QN800C), for when the index cannot be
# read. Without logs, camera frames, provisioning and security resources.
KNOWN_HREFS: tuple[str, ...] = (
    "/oic/d",
    "/oic/p",
    "/sec/languagelist",
    "/autoreconnect/ap",
    "/sec/tv/switch/binary",
    "/sec/tv/contentinfo",
    "/sec/tv/remotecontrol",
    "/sec/tv/virtualremote",
    "/sec/tv/audio",
    "/sec/tv/mediaInput",
    "/sec/tv/mode/picture",
    "/sec/tv/mode/sound",
    "/sec/tv/deviceinfo",
    "/sec/tv/inputsource",
    "/sec/tv/inputsourcelist",
    "/sec/tv/channel",
    "/sec/tv/launchapp",
    "/sec/tv/launchnativeapp",
    "/sec/tv/ime",
    "/sec/tv/searchonweb",
    "/sec/tv/uicontrol",
    "/sec/tv/showmenu",
    "/sec/tv/optioncontrol",
    "/sec/tv/searchall",
    "/sec/tv/appdata/ambientapp",
    "/sec/tv/appdata/oobe",
    "/sec/tv/appdata/ssoservice",
    "/sec/tv/appdata/ub",
    "/sec/tv/appdata/contentsapp",
    "/sec/tv/appdata/aodBrowser",
    "/sec/tv/appdata/ambient-ua-agent",
    "/sec/tv/appdata/mobilebff",
    "/sec/tv/appdata/remote-server",
    "/sec/tv/appdata/mledmultiview",
    "/sec/tv/appdata/lighthomeapp",
    "/sec/tv/appdata/ezcalapp",
    "/sec/tv/appdata/stmap",
    "/sec/tv/appdata/csftservice",
    "/sec/tv/appdata/tlog-ua-agent",
    "/sec/tv/onsupport",
    "/capability/custom.ocfResourceVersion/main/0",
    "/sec/tv/msoinfo",
    "/sec/tv/virtualgamepad/info",
    "/sec/tv/tvonwithmobile/enable",
    "/sec/tv/iotHub",
    "/sec/tv/batteryinfo",
    "/sec/tv/plugin/first_launch",
    "/devicelog/connectioninfo",
    "/capability/sec.diagnosticsInformation/main/0",
    "/sec/tv/thingstatus",
    "/capability/sec.wifiConfiguration/main/0",
    "/capability/samsungim.fixedFindNode/main/0",
    "/capability/samsungim.findNodeGeolocation/main/0",
    "/sec/tv/tapview",
    "/sec/tv/switch/ambient",
    "/content/renderer",
    "/capability/bixbyCommand/main/0",
    "/sec/mde",
    "/sec/tv/category/tv",
    "/sec/tv/display/orientation",
    "/sec/tv/support/features",
    "/irblasterRemoteControl",
    "/irblasterRemoteDevice",
    "/energy/consumption/vs/0",
    "/energy/demandResponseLoadControl/vs/0",
    "/capability/custom.energyType/main/0",
    "/sound/detection/vs/0",
    "/sensor/state/vs/0",
    "/light/sensor/brightness/vs/0",
    "/capability/motion/vs/0",
    "/childdevices/lifecycle",
    "/sec/tv/connectioncontrol/info",
    "/sec/tv/camera/status",
    "/sec/tv/camera/context",
    "/sec/tv/ambient/info",
    "/sec/tv/light/control",
    "/sec/tv/automation/light/control",
    "/sec/tv/mediaOutput",
    "/sec/tv/switch/art",
    "/sec/tv/qsymphony",
    "/sec/tv/networkinfo",
    "/edgeclient/operation/vs/0",
    "/edgeclient/info/vs/0",
)


def _links(index: Any) -> list[dict[str, Any]]:
    """Flatten an `/oic/res` body (bare links, or baseline entries with `links`)."""
    out: list[dict[str, Any]] = []
    for item in index if isinstance(index, list) else [index]:
        if not isinstance(item, dict):
            continue
        nested = item.get("links")
        if isinstance(nested, list):
            out.extend(link for link in nested if isinstance(link, dict))
        elif "href" in item:
            out.append(item)
    return out


class CloudDevice:
    """One allowed TV: its last known state and its current connection, if any."""

    def __init__(
        self, token: str, notify: Listener, device_id: str | None = None
    ) -> None:
        """Remember the token the TV must present; its id is learned at sign-up."""
        self.device_id = device_id
        self._token = token
        self._notify = notify
        self.state = OcfTvState()
        self.host: str | None = None
        self.last_seen: float | None = None
        self._session: _Session | None = None
        self._connected = asyncio.Event()
        self._last_read = 0.0
        # Answers to the TV's own requests, by path: (CoAP code, body). For
        # finding what the TV expects of its cloud; unset paths get the defaults.
        self.replies: dict[str, tuple[int, Any]] = {}
        # Whether sign-in starts our OBSERVE reads of the state resources.
        self.observe_state = True

    @property
    def connected(self) -> bool:
        """Whether the TV holds a signed-in connection right now."""
        return self._session is not None

    def drop(self) -> None:
        """Close the TV's connection; it dials again and re-syncs."""
        if self._session is not None:
            self._session.close()

    def token_matches(self, token: str) -> bool:
        """Constant-time check of the token the TV presented."""
        return hmac.compare_digest(token.encode(), self._token.encode())

    def _attach(self, session: _Session) -> None:
        if self._session is not None and self._session is not session:
            self._session.close()
        self._session = session
        self.host = session.peer
        self.last_seen = time.monotonic()
        self._connected.set()
        self._notify(self)

    def _detach(self, session: _Session) -> None:
        if self._session is session:
            self._session = None
            self._connected.clear()
            self._notify(self)

    def _update(self, href: str, body: Any) -> None:
        self.last_seen = time.monotonic()
        state = apply(self.state, href, body)
        if state != self.state:
            self.state = state
            self._notify(self)

    def _should_read(self) -> bool:
        now = time.monotonic()
        if now - self._last_read < READ_INTERVAL:
            return False
        self._last_read = now
        return True

    async def request(
        self,
        code: int,
        href: str,
        body: Any = None,
        *,
        timeout: float = REQUEST_TIMEOUT,  # noqa: ASYNC109
    ) -> tuple[int, Any]:
        """Send one request down the TV's connection: (response code, body).

        Waits for the TV to (re)connect within `timeout`, as it re-dials every
        few seconds.
        """
        try:
            async with asyncio.timeout(timeout):
                await self._connected.wait()
                session = self._session
                if session is None:
                    raise OcfNotConnectedError(self.device_id or "TV")
                reply = await session.request(code, href, body)
        except TimeoutError as err:
            msg = f"no answer from {self.device_id} for {href}"
            raise OcfNotConnectedError(msg) from err
        return reply.code, _decode(reply.payload)

    async def push(
        self,
        path: str,
        body: Any,
        *,
        timeout: float = REQUEST_TIMEOUT,  # noqa: ASYNC109
    ) -> list[str]:
        """Notify the TV on its own subscription to `path`; return what it holds.

        Waits for a connection that has subscribed (the TV re-dials often).
        """
        try:
            async with asyncio.timeout(timeout):
                while True:
                    await self._connected.wait()
                    session = self._session
                    if session is not None and session.push(path, body):
                        return sorted(session.subscriptions)
                    await asyncio.sleep(0.2)
        except TimeoutError as err:
            msg = f"{self.device_id} has no subscription to {path}"
            raise OcfNotConnectedError(msg) from err

    async def read_all(
        self,
        *,
        timeout: float = 3.0,  # noqa: ASYNC109
        reconnect_wait: float = 30.0,
    ) -> dict[str, Any]:
        """Read every resource the TV offers, for diagnostics and model discovery.

        The resources known from other models come first, then the TV's own
        index (`/oic/res`) and what only it lists. One at a time; the TV re-dials
        now and then, so a read cut short is tried once more after it is back,
        and only a TV that stays away ends the read. Security, account and
        discovery resources are skipped; one that cannot be read records why.
        """
        resources: dict[str, Any] = {}
        dropped: list[str] = []

        async def read(href: str) -> bool:
            return await self._read_one(
                href, resources, dropped, timeout, reconnect_wait
            )

        def finish(
            index: str, links: list[dict[str, Any]], more: list[str]
        ) -> dict[str, Any]:
            return {
                "index": index,
                "links": [
                    {key: link.get(key) for key in ("href", "rt", "if")}
                    for link in links
                ],
                "only_in_index": more,
                "dropped_after": dropped,
                "resources": resources,
            }

        for href in KNOWN_HREFS:
            if not await read(href):
                return finish("not read: the TV went away", [], [])
        going = await read("/oic/res")
        index = resources.pop("/oic/res")
        failed = isinstance(index, dict) and "error" in index
        links = [] if failed else _links(index)
        more = sorted(
            {
                ref
                for link in links
                if isinstance(ref := link.get("href"), str)
                and not ref.startswith(_NOT_READ)
            }
            - set(resources)
        )
        for href in more if going else ():
            if not await read(href):
                break
        return finish(index["error"] if failed else "ok", links, more)

    async def _read_one(
        self,
        href: str,
        resources: dict[str, Any],
        dropped: list[str],
        timeout: float,  # noqa: ASYNC109
        reconnect_wait: float,
    ) -> bool:
        """Store one resource for `read_all`; False when the TV did not come back."""
        for _attempt in range(2):
            try:
                code, body = await self.request(GET, href, timeout=timeout)
            except OcfError as err:
                resources[href] = {"error": str(err)}
                if self.connected:
                    return True
                dropped.append(href)
                if not await self.wait_connected(reconnect_wait):
                    return False
                continue
            resources[href] = body if is_success(code) else {"error": code_text(code)}
            return True
        return True

    async def wait_connected(self, wait: float) -> bool:
        """Wait for the TV to (re)connect; False if it does not within `wait`.

        A TV re-dials the cloud every so often, so a moment without a connection
        is normal.
        """
        try:
            async with asyncio.timeout(wait):
                await self._connected.wait()
        except TimeoutError:
            return False
        return True

    async def get(self, href: str) -> Any:
        """Read a resource; raise `OcfError` unless it answers 2.xx."""
        code, body = await self.request(GET, href)
        if not is_success(code):
            msg = f"{href} answered {code_text(code)}"
            raise OcfError(msg)
        self._update(href, body)
        return body

    async def post(self, href: str, body: dict[str, Any]) -> int:
        """Send a command and return its response code.

        The code is returned, not raised: Samsung's actuators often answer 4.00
        even though they carried the command out.
        """
        code, _ = await self.request(POST, href, body)
        return code

    async def set_power(self, *, on: bool) -> int:
        """Turn the screen on or off (`oic.r.switch.binary`)."""
        return await self.post(SWITCH, {"value": on})

    async def set_volume(self, level: int) -> int:
        """Absolute volume, 0-100."""
        return await self.post(AUDIO, {"volume": max(0, min(100, level))})

    async def set_mute(self, *, muted: bool) -> int:
        """Mute or unmute."""
        return await self.post(AUDIO, {"mute": muted})

    async def select_input(self, source_id: str) -> int:
        """Switch to an input by its id (`dtv`, `HDMI1`, ...) from `input_sources`."""
        return await self.post(
            INPUT_SOURCE, {"x.com.samsung.tv.currentMode": source_id}
        )

    async def set_picture_mode(self, mode_id: str) -> int:
        """Picture mode by id, from `picture_modes`."""
        return await self.post(PICTURE_MODE, {"x.com.samsung.tv.currentMode": mode_id})

    async def set_sound_mode(self, mode_id: str) -> int:
        """Sound mode by id, from `sound_modes`."""
        return await self.post(SOUND_MODE, {"x.com.samsung.tv.currentMode": mode_id})

    async def set_sound_output(self, output_id: str) -> int:
        """Sound output (TV speaker, soundbar, ...) by id, from `sound_outputs`."""
        return await self.post(MEDIA_OUTPUT, {"curMediaOutput": output_id})

    async def send_key(self, key: str) -> int:
        """Press a remote key such as `KEY_HOME`."""
        return await self.post(VIRTUAL_REMOTE, {"x.com.samsung.control.remote": key})

    async def launch_app(self, app_id: str) -> int:
        """Open an app by its Tizen id."""
        return await self.post(LAUNCH_APP, {"x.com.samsung.launchapp.appId": app_id})

    async def art_mode_on(self) -> int:
        """Frame: go to Art Mode (leaving it is the power key)."""
        return await self.post(SWITCH_ART, {"x.com.samsung.tv.requestor": "samstream"})

    async def restart_agent(self) -> None:
        """Restart the TV's SmartThings service, which re-dials the cloud.

        The TV then asks on screen whether to allow the reconnect, so only on
        request (Configure). It restarts before answering: a lost connection
        is success.
        """
        with contextlib.suppress(OcfNotConnectedError):
            await self.post(
                DEVICE_COMMAND, {"x.com.samsung.devicelog.command": "restartThing"}
            )


class _Session:
    """One TLS connection from a TV."""

    def __init__(
        self,
        cloud: OcfCloud,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._cloud = cloud
        self._reader = reader
        self._writer = writer
        peer = writer.get_extra_info("peername")
        self.peer: str = peer[0] if peer else "?"
        self._frames = FrameReader()
        self._pending: dict[bytes, asyncio.Future[Message]] = {}
        self._observed: dict[bytes, str] = {}
        # The TV's own OBSERVE requests to us, by path (e.g. /service/observe).
        self.subscriptions: dict[str, bytes] = {}
        self._observe_seq = 1
        self.device: CloudDevice | None = None
        self._opened = time.monotonic()

    def close(self) -> None:
        self._writer.close()

    def _send(self, message: Message) -> None:
        _LOGGER.debug(
            "OCF cloud: -> %s %s %s %s",
            self.peer,
            code_text(message.code),
            message.path or message.token.hex(),
            len(message.payload),
        )
        if not self._writer.is_closing():
            self._writer.write(encode(message))

    def _reply(
        self, request: Message, code: int, body: Any = None, *, observe: bool = False
    ) -> None:
        options: list[tuple[int, bytes]] = []
        if observe:
            options.append((OBSERVE, uint(self._observe_seq)))
            self._observe_seq += 1
        payload = b""
        if body is not None:
            options.append((CONTENT_FORMAT, bytes([CBOR_FORMAT])))
            payload = cbor.dumps(body)
        self._send(Message(code, request.token, tuple(options), payload))

    def push(self, path: str, body: Any) -> bool:
        """Send a notification on one of the TV's own subscriptions."""
        token = self.subscriptions.get(path)
        if token is None:
            return False
        self._reply(Message(CONTENT, token), CONTENT, body, observe=True)
        return True

    async def request(self, code: int, href: str, body: Any = None) -> Message:
        if len(self._pending) >= MAX_PENDING:
            msg = "too many requests in flight"
            raise OcfError(msg)
        token = os.urandom(4)
        options = path_options(href)
        payload = b""
        if body is not None:
            options.append((CONTENT_FORMAT, bytes([CBOR_FORMAT])))
            payload = cbor.dumps(body)
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        self._pending[token] = future
        try:
            self._send(Message(code, token, tuple(options), payload))
            return await future
        finally:
            self._pending.pop(token, None)

    def _observe_state(self) -> None:
        """Register OBSERVE on the state resources; the first reply is the value."""
        for href in STATE_RESOURCES:
            token = os.urandom(4)
            self._observed[token] = href
            options = [(OBSERVE, b""), *path_options(href)]
            self._send(Message(GET, token, tuple(options)))

    def _authorise(self, request: Message, body: Any, token_key: str) -> bool:
        device = self._cloud.match(_field(body, "di"), _field(body, token_key))
        if device is None:
            _LOGGER.warning("OCF cloud: refused a device from %s", self.peer)
            self._reply(request, UNAUTHORIZED)
            self._writer.close()
            return False
        self.device = device
        return True

    def _on_request(self, request: Message) -> None:
        path = request.path
        body = _decode(request.payload)
        if path in (SIGN_UP, SIGN_IN, TOKEN_REFRESH):
            self._on_account(request, path, body)
            return
        if self.device is None:
            self._reply(request, UNAUTHORIZED)
            return
        # What the TV asks of its cloud (never the account paths: tokens).
        _LOGGER.debug(
            "OCF cloud: %s asks %s %s?%s%s %s",
            self.peer,
            request.code,
            path,
            "&".join(q.decode(errors="replace") for q in request.values(URI_QUERY)),
            " (observe)" if request.has(OBSERVE) else "",
            str(body)[:600],
        )
        if request.code == GET and request.has(OBSERVE):
            self.subscriptions[path] = request.token
        if path in self.device.replies:
            code, answer = self.device.replies[path]
            observe = request.code == GET and request.has(OBSERVE)
            self._reply(request, code, answer, observe=observe)
        elif request.code == GET:
            # The TV's own sync GETs must be answered 2.05 (2.04 makes it drop us).
            self._reply(request, CONTENT, {}, observe=request.has(OBSERVE))
        elif path == KEEP_ALIVE:
            # 2.03 with no body, as IoTivity answers; 2.04 {} made the TV hang up
            # right after it set its keep-alive interval.
            self._reply(request, VALID)
        elif path == PUBLISH:
            self._reply(request, CHANGED, body if isinstance(body, dict) else {})
        else:
            self._reply(request, CHANGED, {})

    def _on_account(self, request: Message, path: str, body: Any) -> None:
        """Sign-up, sign-in and token refresh: the only paths served before sign-in."""
        _LOGGER.debug(
            "OCF cloud: %s account %s keys=%s",
            self.peer,
            path,
            sorted(body) if isinstance(body, dict) else type(body).__name__,
        )
        if path == SIGN_UP:
            if self._authorise(request, body, "accesstoken"):
                self._reply(request, CHANGED, self._cloud.sign_up_reply(body))
        elif path == SIGN_IN:
            if self._authorise(request, body, "accesstoken") and self.device:
                self._reply(request, CHANGED, {"expiresin": _TOKEN_EXPIRY})
                self.device._attach(self)  # noqa: SLF001
                if self.device.observe_state and self.device._should_read():  # noqa: SLF001
                    self._observe_state()
        elif self._authorise(request, body, "refreshtoken"):  # token refresh
            token = _field(body, "refreshtoken")
            self._reply(
                request,
                CHANGED,
                {
                    "accesstoken": token,
                    "refreshtoken": token,
                    "tokentype": "bearer",
                    "expiresin": _TOKEN_EXPIRY,
                },
            )

    def _on_response(self, message: Message) -> None:
        future = self._pending.get(message.token)
        if future is not None:
            if not future.done():
                future.set_result(message)
            return
        href = self._observed.get(message.token)
        if href and self.device and is_success(message.code):
            self.device._update(href, _decode(message.payload))  # noqa: SLF001

    def _dispatch(self, message: Message) -> None:
        if not is_request(message.code):
            _LOGGER.debug(
                "OCF cloud: <- %s %s %s options=%s %s",
                self.peer,
                code_text(message.code),
                message.token.hex(),
                [(n, v[:40]) for n, v in message.options],
                _decode(message.payload) if message.payload else "",
            )
        if message.code == PING:
            self._send(Message(PONG, message.token))
        elif message.code in (CSM, PONG):
            pass
        elif message.code in (RELEASE, ABORT):
            self._writer.close()
        elif is_request(message.code):
            self._on_request(message)
        elif message.code >= 0x40:  # noqa: PLR2004
            self._on_response(message)

    async def _receive(self) -> None:
        deadline = time.monotonic() + AUTH_DEADLINE
        while not self._writer.is_closing():
            if self.device is None and time.monotonic() > deadline:
                return
            try:
                async with asyncio.timeout(IDLE_PING):
                    chunk = await self._reader.read(8192)
            except TimeoutError:
                self._send(Message(PING, os.urandom(2)))
                continue
            if not chunk:
                return
            for message in self._frames.feed(chunk):
                self._dispatch(message)
            await self._writer.drain()

    async def run(self) -> None:
        size = (CSM_MAX_MESSAGE_SIZE, uint(_CSM_SIZE))
        self._send(Message(CSM, b"", (size,)))
        try:
            await self._receive()
        except CoapError as err:
            _LOGGER.debug("OCF cloud: dropping %s: %s", self.peer, err)
        except (ConnectionError, OSError) as err:
            _LOGGER.debug("OCF cloud: %s went away: %s", self.peer, err)
        finally:
            _LOGGER.debug(
                "OCF cloud: %s connection ended after %.1f s",
                self.peer,
                time.monotonic() - self._opened,
            )
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(OcfNotConnectedError(self.peer))
            if self.device is not None:
                self.device._detach(self)  # noqa: SLF001
            self._writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._writer.wait_closed()


class OcfCloud:
    """The cloud server; `allow` each TV, then `start`."""

    def __init__(
        self,
        ssl_context: ssl.SSLContext,
        *,
        cloud_uuid: str,
        ca_der: bytes,
        cis: str,
        listener: Listener | None = None,
    ) -> None:
        """`cis` is the address written to the TV, e.g. `coaps+tcp://10.0.0.2:5684`."""
        self._ssl = ssl_context
        self.cloud_uuid = cloud_uuid
        self._ca_der = ca_der
        self.cis = cis
        self._listener = listener
        self.devices: dict[str, CloudDevice] = {}  # by the caller's key
        self._server: asyncio.Server | None = None
        self._sessions: set[_Session] = set()

    def allow(self, key: str, token: str, device_id: str | None = None) -> CloudDevice:
        """Serve a TV under `key` (e.g. a config entry id).

        `token` is the access token onboarding wrote to the TV (`at`). The TV's
        OCF device id is learned at its first sign-up unless given.
        """
        if not token:
            msg = "an access token is required"
            raise ValueError(msg)
        self.forget(key)
        device = CloudDevice(token, self._notify, device_id)
        self.devices[key] = device
        return device

    def match(self, device_id: str, token: str) -> CloudDevice | None:
        """Find the allowed TV presenting this token; bind its id on first contact."""
        if not device_id:
            return None
        found = None
        for device in self.devices.values():  # every token is compared (timing)
            if device.token_matches(token):
                found = device
        if found is None:
            return None
        if found.device_id is None:
            if any(d.device_id == device_id for d in self.devices.values()):
                return None  # this TV already belongs to another key
            found.device_id = device_id
        return found if found.device_id == device_id else None

    def forget(self, key: str) -> None:
        """Stop serving a TV and drop its connection."""
        device = self.devices.pop(key, None)
        if device is not None and device._session is not None:  # noqa: SLF001
            device._session.close()  # noqa: SLF001

    def _notify(self, device: CloudDevice) -> None:
        if self._listener is not None:
            self._listener(device)

    def sign_up_reply(self, body: Any) -> dict[str, Any]:
        """Build the sign-up answer, shaped like IoTivity's AccountManager.

        The TV stalls without `redirecturi`, `certificate` and `sid`.
        """
        token = _field(body, "accesstoken")
        return {
            "accesstoken": token,
            "refreshtoken": token,
            "tokentype": "bearer",
            "expiresin": _TOKEN_EXPIRY,
            "uid": _field(body, "uid") or "samstream",
            "redirecturi": self.cis,
            "certificate": self._ca_der,
            "sid": self.cloud_uuid,
        }

    @property
    def port(self) -> int | None:
        """The bound port (useful with port 0 in tests)."""
        if self._server is None or not self._server.sockets:
            return None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self, port: int, host: str | None = None) -> None:
        """Listen; raises `OSError` if the port is taken."""
        self._server = await asyncio.start_server(
            self._handle, host, port, ssl=self._ssl, ssl_handshake_timeout=10
        )

    async def stop(self) -> None:
        """Close the listener and every connection."""
        if self._server is not None:
            self._server.close()
            for session in list(self._sessions):
                session.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if len(self._sessions) >= MAX_CONNECTIONS:
            writer.close()
            return
        session = _Session(self, reader, writer)
        self._sessions.add(session)
        try:
            await session.run()
        finally:
            self._sessions.discard(session)
