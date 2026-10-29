"""The local OCF cloud: codecs, certificates, state, and a fake TV over TLS."""

import asyncio
import json
import ssl
from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiosamstream import OcfError, OcfNotConnectedError
from aiosamstream.ocf import (
    CloudDevice,
    OcfCloud,
    OcfTvState,
    cbor,
    cloud,
    generate_identity,
    issue_server_certificate,
    load_identity,
    server_ssl_context,
)
from aiosamstream.ocf.coap_tcp import (
    CHANGED,
    CONTENT,
    CSM,
    GET,
    OBSERVE,
    PING,
    PONG,
    POST,
    UNAUTHORIZED,
    CoapError,
    FrameReader,
    Message,
    encode,
    path_options,
)
from aiosamstream.ocf.state import AUDIO, CONTENT_INFO, INPUT_SOURCE, apply

pytestmark = pytest.mark.enable_socket

TV = "x.com.samsung.tv."
DEVICE_ID = "a63c3d4d-5237-a426-7130-9d7e14d09624"
TOKEN = "per-tv-secret"
IDENTITY = generate_identity()

# Bodies as the QN800C sent them through the local cloud.
BODIES: dict[str, dict[str, Any]] = {
    CONTENT_INFO: {
        f"{TV}input": "webapp",
        f"{TV}title": "YouTube",
        f"{TV}subtitle": "9Ur5IzDKqV.TizenYouTube",
    },
    INPUT_SOURCE: {
        f"{TV}supportedModes": [
            {f"{TV}name": "TV", f"{TV}id": "dtv"},
            {f"{TV}name": "HDMI 1", f"{TV}id": "HDMI1"},
        ],
        f"{TV}currentMode": "dtv",
    },
    AUDIO: {"volume": 19, "mute": False},
    "/sec/tv/switch/binary": {"value": True},
    "/sec/tv/channel": {f"{TV}channelNumber": "154", f"{TV}channelName": "Al-Majd3"},
    "/sec/tv/mode/sound": {
        f"{TV}supportedModes": [{f"{TV}name": "عادي", f"{TV}id": "modeStandard"}],
        f"{TV}currentMode": "modeStandard",
    },
    "/sec/tv/networkinfo": {"rssi": 3, "ch": 36},
}


# --- codecs ----------------------------------------------------------------


def test_cbor_round_trip() -> None:
    value = {
        "a": [1, -5, 300, 70000, 2**40],
        "b": b"\x00\x01",
        "t": "عادي",
        "x": None,
        "y": True,
        "f": 1.5,
    }
    assert cbor.loads(cbor.dumps(value)) == value


def test_cbor_rejects_hostile_input() -> None:
    with pytest.raises(cbor.CborError):
        cbor.loads(b"\x81" * 100 + b"\x00")  # nested past MAX_DEPTH
    with pytest.raises(cbor.CborError):
        cbor.loads(b"\x5a\xff\xff\xff\xff")  # 4 GB byte string, 0 bytes present
    assert cbor.loads(b"\x62\xff\xfe") == "��"  # bad UTF-8 is replaced


def test_frame_round_trip_and_split_reads() -> None:
    message = Message(
        POST,
        b"\x01\x02\x03\x04",
        (*path_options("/sec/tv/audio?if=oic.if.a"), (OBSERVE, b"")),
        cbor.dumps({"volume": 3} | {f"k{i}": "v" * 20 for i in range(30)}),
    )
    raw = encode(message)
    reader = FrameReader()
    assert reader.feed(raw[:3]) == []
    [decoded] = reader.feed(raw[3:] + encode(Message(PING, b"\x09")))[:1]
    assert decoded.path == "/sec/tv/audio"
    assert decoded.values(15) == [b"if=oic.if.a"]
    assert decoded.has(OBSERVE)
    assert cbor.loads(decoded.payload)["volume"] == 3


def test_frame_limits() -> None:
    with pytest.raises(CoapError):
        FrameReader(max_frame=100).feed(encode(Message(POST, b"", (), b"x" * 200)))
    with pytest.raises(CoapError):
        FrameReader().feed(b"\x0f\x01")  # token length 15


# --- state -------------------------------------------------------------------


def test_state_from_bodies() -> None:
    state = OcfTvState()
    for href, body in BODIES.items():
        state = apply(state, href, body)
    assert state.power is True
    assert (state.volume, state.muted) == (19, False)
    assert state.input_source == "dtv"
    assert state.input_sources == (("dtv", "TV"), ("HDMI1", "HDMI 1"))
    assert (state.content_input, state.content_title) == ("webapp", "YouTube")
    assert state.app_id == "9Ur5IzDKqV.TizenYouTube"
    assert (state.channel_number, state.channel_name) == ("154", "Al-Majd3")
    assert state.sound_modes == (("modeStandard", "عادي"),)
    assert (state.wifi_rssi, state.wifi_channel) == (3, 36)
    # Live TV: the subtitle is programme text, not an app id.
    live = apply(state, CONTENT_INFO, {f"{TV}input": "dtv", f"{TV}subtitle": "News"})
    assert live.app_id is None
    assert apply(state, AUDIO, "garbage") is state
    assert apply(state, "/oic/d", {"n": "TV"}) is state


# --- certificates --------------------------------------------------------------


def test_identity_import_checks_the_key() -> None:
    again = load_identity(IDENTITY.ca_der, IDENTITY.ca_key_pem, IDENTITY.cloud_uuid)
    assert again.ca_der == IDENTITY.ca_der
    other = generate_identity()
    with pytest.raises(ValueError, match="does not match"):
        load_identity(IDENTITY.ca_cert_pem, other.ca_key_pem, IDENTITY.cloud_uuid)
    with pytest.raises(ValueError, match="badly formed"):
        load_identity(IDENTITY.ca_cert_pem, IDENTITY.ca_key_pem, "not-a-uuid")


# --- the cloud, with a fake TV over TLS ---------------------------------------


class FakeTV:
    """Dials the cloud like the TV: sign up, sign in, answer reads and commands."""

    def __init__(self, port: int, token: str = TOKEN) -> None:
        self.port = port
        self.token = token
        self.commands: list[tuple[str, Any]] = []
        self.observed: list[str] = []
        self.sign_up: dict[str, Any] = {}
        self.closed = asyncio.Event()
        self.reply_to_posts = True

    async def connect(self) -> None:
        context = ssl.create_default_context(cadata=IDENTITY.ca_der)
        context.check_hostname = False  # the TV checks the chain, not the name
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", self.port, ssl=context
        )
        self.frames = FrameReader()
        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        self.task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        while chunk := await self.reader.read(65536):
            for message in self.frames.feed(chunk):
                await self._on(message)
        self.closed.set()

    async def _on(self, message: Message) -> None:
        if message.code in (CSM, PONG):
            return
        if message.code >= 0x40:
            await self.inbox.put(message)
            return
        if message.code == GET:
            self.observed.append(message.path)
            body = BODIES.get(message.path)
            if body is None:
                self.send(Message(0x84, message.token))  # 4.04
            else:
                self.send(Message(CONTENT, message.token, (), cbor.dumps(body)))
        elif message.code == POST:
            self.commands.append((message.path, cbor.loads(message.payload)))
            if self.reply_to_posts:
                self.send(Message(0x80, message.token))  # 4.00, as Samsung does

    def send(self, message: Message) -> None:
        self.writer.write(encode(message))

    async def call(self, path: str, body: dict[str, Any]) -> Message:
        self.send(Message(POST, b"\x07", tuple(path_options(path)), cbor.dumps(body)))
        return await asyncio.wait_for(self.inbox.get(), 5)

    async def sign_in(self) -> None:
        reply = await self.call(
            "/oic/account",
            {
                "di": DEVICE_ID,
                "accesstoken": self.token,
                "uid": "u",
                "authprovider": "x",
            },
        )
        assert reply.code == CHANGED
        self.sign_up = cbor.loads(reply.payload)
        reply = await self.call(
            "/oic/account/session",
            {"di": DEVICE_ID, "accesstoken": self.token, "login": True},
        )
        assert reply.code == CHANGED

    async def close(self) -> None:
        self.writer.close()
        self.task.cancel()


@pytest.fixture
async def ocf_cloud() -> AsyncIterator[tuple[OcfCloud, CloudDevice, list[CloudDevice]]]:
    chain, key = issue_server_certificate(IDENTITY, "127.0.0.1")
    updates: list[CloudDevice] = []
    server = OcfCloud(
        await asyncio.to_thread(server_ssl_context, chain, key),
        cloud_uuid=IDENTITY.cloud_uuid,
        ca_der=IDENTITY.ca_der,
        cis="coaps+tcp://127.0.0.1:5684",
        listener=updates.append,
    )
    device = server.allow("entry", TOKEN)
    await server.start(0, "127.0.0.1")
    yield server, device, updates
    await server.stop()


async def _until(check: Any) -> None:
    async with asyncio.timeout(5):
        while not check():  # noqa: ASYNC110 - polling state the server owns
            await asyncio.sleep(0.01)


async def test_tv_signs_in_and_reports_state(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, device, updates = ocf_cloud
    assert server.port
    tv = FakeTV(server.port)
    await tv.connect()
    await tv.sign_in()
    assert tv.sign_up["sid"] == IDENTITY.cloud_uuid
    assert tv.sign_up["certificate"] == IDENTITY.ca_der
    assert tv.sign_up["redirecturi"] == "coaps+tcp://127.0.0.1:5684"
    await _until(lambda: device.state.volume == 19 and device.state.power)
    assert device.connected
    assert device.host == "127.0.0.1"
    assert device.state.app_id == "9Ur5IzDKqV.TizenYouTube"
    assert set(tv.observed) == set(cloud.STATE_RESOURCES)
    assert updates

    # Commands go down the TV's connection; 4.00 is returned, not raised.
    assert await device.set_volume(150) == 0x80
    await device.set_mute(muted=True)
    await device.select_input("HDMI1")
    await device.send_key("KEY_HOME")
    assert tv.commands == [
        (AUDIO, {"volume": 100}),
        (AUDIO, {"mute": True}),
        (INPUT_SOURCE, {f"{TV}currentMode": "HDMI1"}),
        ("/sec/tv/virtualremote", {"x.com.samsung.control.remote": "KEY_HOME"}),
    ]
    assert (await device.get(AUDIO))["volume"] == 19
    with pytest.raises(OcfError):
        await device.get("/sec/tv/missing")
    await tv.close()
    await _until(lambda: not device.connected)


async def test_unknown_token_is_refused(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, device, _ = ocf_cloud
    assert server.port
    tv = FakeTV(server.port, token="wrong")
    await tv.connect()
    reply = await tv.call("/oic/account", {"di": DEVICE_ID, "accesstoken": "wrong"})
    assert reply.code == UNAUTHORIZED
    await asyncio.wait_for(tv.closed.wait(), 5)
    assert not device.connected


async def test_requests_before_sign_in_are_refused(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, _, _ = ocf_cloud
    assert server.port
    tv = FakeTV(server.port)
    await tv.connect()
    reply = await tv.call("/oic/rd", {"links": []})
    assert reply.code == UNAUTHORIZED
    await tv.close()


async def test_request_without_tv_times_out(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    _, device, _ = ocf_cloud
    with pytest.raises(OcfNotConnectedError):
        await device.request(GET, AUDIO, timeout=0.05)


# --- edge cases ------------------------------------------------------------------


def test_cbor_edge_cases() -> None:
    assert cbor.loads(bytes.fromhex("f93e00")) == 1.5  # half float
    assert cbor.loads(bytes.fromhex("fa3fc00000")) == 1.5  # single float
    assert cbor.loads(bytes.fromhex("f7")) is None  # undefined
    assert cbor.loads(bytes.fromhex("9f0102ff")) == [1, 2]  # indefinite array
    assert cbor.loads(bytes.fromhex("bf6161 01ff".replace(" ", ""))) == {"a": 1}
    assert cbor.loads(bytes.fromhex("7f61616162ff")) == "ab"  # indefinite text
    assert cbor.loads(bytes.fromhex("5f41014102ff")) == b"\x01\x02"
    assert cbor.loads(bytes.fromhex("c11a514b67b0")) == 1363896240  # tagged
    for bad in ("1c", "f8", "df", "9fff"[:2], "a1"):
        with pytest.raises(cbor.CborError):
            cbor.loads(bytes.fromhex(bad))
    with pytest.raises(cbor.CborError):
        cbor.dumps(object())


def test_large_frames_and_options() -> None:
    for size in (20, 400, 70000):
        message = Message(POST, b"\x01", ((11, b"p" * 300), (2000, b"v")), b"x" * size)
        [decoded] = FrameReader().feed(encode(message))
        assert decoded.payload == message.payload
        assert decoded.values(2000) == [b"v"]
    with pytest.raises(CoapError):
        encode(Message(POST, b"123456789"))
    with pytest.raises(CoapError):
        FrameReader().feed(bytes([0x30, POST, 0xF0, 0, 0]))  # reserved nibble 15
    with pytest.raises(CoapError):
        FrameReader().feed(bytes([0x20, POST, 0x15, 0]))  # option runs past frame
    reader = FrameReader()
    assert reader.feed(bytes([0xD0])) == []  # extended length not in yet
    assert reader.feed(b"") == []


def test_certificate_for_a_host_name() -> None:
    chain, key = issue_server_certificate(IDENTITY, "ha.local")
    assert b"BEGIN CERTIFICATE" in chain
    assert b"PRIVATE KEY" in key


async def test_session_extras(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, device, _ = ocf_cloud
    assert server.port
    tv = FakeTV(server.port)
    await tv.connect()
    await tv.sign_in()
    reply = await tv.call(
        "/oic/account/tokenrefresh", {"di": DEVICE_ID, "refreshtoken": TOKEN}
    )
    assert cbor.loads(reply.payload)["accesstoken"] == TOKEN
    reply = await tv.call("/oic/rd", {"links": [{"href": "/oic/d"}]})
    assert cbor.loads(reply.payload) == {"links": [{"href": "/oic/d"}]}
    reply = await tv.call("/oic/ping", {"in": 8})
    assert reply.code == CHANGED
    # The TV's own sync GET (with Observe) is answered 2.05 with a sequence number.
    tv.send(Message(GET, b"\x08", ((OBSERVE, b""), *path_options("/service/observe"))))
    reply = await asyncio.wait_for(tv.inbox.get(), 5)
    assert (reply.code, reply.has(OBSERVE)) == (CONTENT, True)
    tv.send(Message(PING, b"\x09"))
    await _until(lambda: device.state.volume == 19)
    await device.set_power(on=False)
    await device.set_picture_mode("modeMovie")
    await device.set_sound_mode("modeAmplify")
    await device.launch_app("111299001912")
    assert [path for path, _ in tv.commands] == [
        "/sec/tv/switch/binary",
        "/sec/tv/mode/picture",
        "/sec/tv/mode/sound",
        "/sec/tv/launchapp",
    ]
    # An observe notification later on updates the state.
    token = next(t for t, h in _observed(server).items() if h == AUDIO)
    tv.send(Message(CONTENT, token, (), cbor.dumps({"volume": 7, "mute": True})))
    await _until(lambda: device.state.volume == 7)
    assert device.state.muted is True
    # A second connection from the same TV replaces the first.
    second = FakeTV(server.port)
    await second.connect()
    await second.sign_in()
    await asyncio.wait_for(tv.closed.wait(), 5)
    assert device.connected
    assert device.device_id == DEVICE_ID  # learned at sign-up
    server.forget("entry")
    await asyncio.wait_for(second.closed.wait(), 5)
    assert "entry" not in server.devices


def _observed(server: OcfCloud) -> dict[bytes, str]:
    [session] = [s for s in server._sessions if s.device]  # noqa: SLF001
    return session._observed  # noqa: SLF001


async def test_release_and_pending_requests(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, device, _ = ocf_cloud
    assert server.port
    tv = FakeTV(server.port)
    await tv.connect()
    await tv.sign_in()
    tv.reply_to_posts = False
    pending = asyncio.create_task(device.post(AUDIO, {"mute": True}))
    await _until(lambda: tv.commands)
    tv.send(Message(0xE4, b""))  # Release: the cloud closes the connection
    with pytest.raises(OcfNotConnectedError):
        await pending
    await asyncio.wait_for(tv.closed.wait(), 5)


async def test_connection_cap_and_allow_checks(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = ocf_cloud
    assert server.port
    with pytest.raises(ValueError, match="access token"):
        server.allow("other", "")
    # Another TV with the same token cannot take over a bound one.
    server.devices["entry"].device_id = DEVICE_ID
    assert server.match("ffffffff-0000-0000-0000-000000000000", TOKEN) is None
    assert server.match("", TOKEN) is None
    other = server.allow("other", "second-token")
    assert server.match(DEVICE_ID, "second-token") is None  # id bound elsewhere
    assert other.device_id is None
    monkeypatch.setattr(cloud, "MAX_CONNECTIONS", 0)
    tv = FakeTV(server.port)
    await tv.connect()
    await asyncio.wait_for(tv.closed.wait(), 5)


async def test_silent_connection_is_closed(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = ocf_cloud
    assert server.port
    monkeypatch.setattr(cloud, "AUTH_DEADLINE", 0.05)
    monkeypatch.setattr(cloud, "IDLE_PING", 0.02)
    tv = FakeTV(server.port)
    await tv.connect()
    await asyncio.wait_for(tv.closed.wait(), 5)


async def test_garbage_frame_drops_the_connection(
    ocf_cloud: tuple[OcfCloud, CloudDevice, list[CloudDevice]],
) -> None:
    server, _, _ = ocf_cloud
    assert server.port
    tv = FakeTV(server.port)
    await tv.connect()
    tv.writer.write(b"\x0f\x01")  # token length 15
    await asyncio.wait_for(tv.closed.wait(), 5)


def test_sensor_resources() -> None:
    from aiosamstream.ocf import state as s  # noqa: PLC0415

    log = {
        "ap_rssi": -66,
        "ap_freq": 5180,
        "ap_protocol": "802.11ac",
        "ap_disconnect_count": 0,
    }
    state = OcfTvState()
    for href, body in {
        s.CONNECTION_INFO: {"x.com.samsung.devicelog.connectioninfo": json.dumps(log)},
        s.LIGHT_SENSOR: {"brightness.level": 1, "brightness.lux": 12},
        s.SOUND_DETECTION: {
            "x.com.samsung.vd.soundDetected": "dogBarking",
            "x.com.samsung.vd.supportedSoundTypes": ["noSound", "dogBarking"],
        },
        s.CAMERA: {"disableReason": "cameraDisconnect"},
        s.ENERGY: {"energySavingOperation": False},
        s.BATTERY: {"rt": ["x"], "x.com.samsung.tv.batteryLevel": 80},
    }.items():
        state = apply(state, href, body)
    assert (state.wifi_dbm, state.wifi_frequency) == (-66, 5180)
    assert state.wifi_protocol == "802.11ac"
    assert state.wifi_disconnects == 0
    assert (state.illuminance, state.brightness_level) == (12.0, 1)
    assert state.sound_detected == "dogBarking"
    assert state.sound_types == ("noSound", "dogBarking")
    assert state.camera_connected is False
    assert state.energy_saving is False
    assert state.remote_battery == 80
    # Malformed bodies change nothing they do not own.
    assert (
        apply(state, s.CONNECTION_INFO, {"x.com.samsung.devicelog.connectioninfo": "{"})
        == state
    )
    assert apply(state, s.BATTERY, {"level": 300}) == state
    assert apply(state, s.CAMERA, {}).camera_connected is None


def test_links_flattens_both_res_shapes() -> None:
    from aiosamstream.ocf.cloud import _links  # noqa: PLC0415

    bare = [{"href": "/sec/tv/audio", "rt": ["x.com.samsung.tv.audio"]}, "junk"]
    baseline = [{"di": "x", "links": [{"href": "/a"}, {"href": "/b"}, 3]}]
    assert [link["href"] for link in _links(bare)] == ["/sec/tv/audio"]
    assert [link["href"] for link in _links(baseline)] == ["/a", "/b"]
    assert _links(None) == []


def _reading_device(
    answers: dict[str, Any], *, drops_at: str | None = None
) -> tuple[CloudDevice, list[str]]:
    """A device whose requests answer from `answers`; `drops_at` ends the session."""
    device = CloudDevice("token", lambda _d: None)
    device._session = object()  # type: ignore[assignment]  # noqa: SLF001
    asked: list[str] = []

    async def request(_code: int, href: str, **_kw: Any) -> tuple[int, Any]:
        asked.append(href)
        if href == drops_at:
            device._session = None  # noqa: SLF001
            msg = "192.168.1.22"
            raise OcfNotConnectedError(msg)
        if href in answers:
            return CONTENT, answers[href]
        return 0x80, None  # 4.00

    device.request = request  # type: ignore[method-assign]
    return device, asked


async def test_read_all_known_resources_then_the_index() -> None:
    from aiosamstream.ocf.cloud import KNOWN_HREFS  # noqa: PLC0415

    device, asked = _reading_device(
        {
            "/capability/motion/vs/0": {"motion": "inactive"},
            "/oic/res": [{"href": "/extra"}, {"href": "/oic/sec/cred"}],
            "/extra": {"x": 1},
        }
    )
    result = await device.read_all()
    assert asked[: len(KNOWN_HREFS)] == list(KNOWN_HREFS)
    assert asked[len(KNOWN_HREFS) :] == ["/oic/res", "/extra"]  # never /oic/sec/
    assert result["index"] == "ok"
    assert result["only_in_index"] == ["/extra"]
    assert result["resources"]["/capability/motion/vs/0"] == {"motion": "inactive"}
    assert result["resources"]["/oic/d"] == {"error": "4.00"}


async def test_read_all_waits_for_the_tv_to_dial_back() -> None:
    device, asked = _reading_device(
        {"/capability/motion/vs/0": {"motion": "active"}, "/oic/d": {"n": "TV"}},
        drops_at="/oic/d",
    )
    session = device._session  # noqa: SLF001

    async def back_after_a_moment(_wait: float) -> bool:
        device._session = session  # noqa: SLF001
        return True

    device.wait_connected = back_after_a_moment  # type: ignore[method-assign]
    result = await device.read_all()
    # Cut short once, read again after the TV came back, then the rest.
    assert asked[:2] == ["/oic/d", "/oic/d"]
    assert result["dropped_after"] == ["/oic/d", "/oic/d"]
    assert result["resources"]["/capability/motion/vs/0"] == {"motion": "active"}


async def test_read_all_stops_when_the_tv_stays_away() -> None:
    device, asked = _reading_device({}, drops_at="/oic/d")
    result = await device.read_all(reconnect_wait=0.01)
    assert asked == ["/oic/d"]
    assert result["index"] == "not read: the TV went away"
    assert result["resources"]["/oic/d"] == {"error": "192.168.1.22"}


def test_motion_from_any_motion_key() -> None:
    from aiosamstream.ocf import state as s  # noqa: PLC0415

    state = OcfTvState()
    assert apply(state, s.MOTION, {"rt": ["x"], "if": ["y"]}) == state  # Frame, idle
    assert apply(state, s.MOTION, {"motion": "active"}).motion is True
    assert (
        apply(state, s.MOTION, {"x.com.samsung.vd.motion": "inactive"}).motion is False
    )
    assert apply(state, s.MOTION, {"motionDetected": True}).motion is True
    sensors = {
        "x.com.samsung.vd.sensorType": [
            {"name": "Light", "enabled": False},
            {"name": "CameraMotion", "enabled": True},
        ]
    }
    assert apply(state, s.SENSOR_STATES, sensors).motion_sensor_enabled is True


def test_art_mode_orientation_and_accessibility() -> None:
    from aiosamstream.ocf import state as s  # noqa: PLC0415

    state = OcfTvState()
    assert state.art_mode is None
    art = {"x.com.samsung.tv.input": "webapp", "x.com.samsung.tv.subtitle": "art"}
    assert apply(state, CONTENT_INFO, art).art_mode is True
    hub = {**art, "x.com.samsung.tv.subtitle": "com.samsung.tv.csfs"}
    assert apply(state, CONTENT_INFO, hub).art_mode is False
    assert (
        apply(state, s.ORIENTATION, {"orientation": 1, "status": -1}).orientation == 1
    )
    menu = {
        "x.com.samsung.tv.accessibility": [
            {"menuid": "grayscale", "value": "1"},
            {"menuid": "highcontrast", "value": "0"},
            "junk",
        ]
    }
    read = apply(state, s.SHOW_MENU, menu)
    assert read.accessibility_on("grayscale") is True
    assert read.accessibility_on("highcontrast") is False
    assert read.accessibility_on("voiceguide_on") is None
