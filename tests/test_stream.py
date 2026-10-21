"""play_stream / stop_stream and the go2rtc WebSocket relay to the TV."""

import json
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web
from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.const import CONF_TV_SECRET, DOMAIN
from custom_components.samstream.stream_relay import stream_name
from custom_components.samstream.tv_session import session_answer

# The fake go2rtc is a real local aiohttp server.
pytestmark = pytest.mark.enable_socket

TV = "media_player.65_neo_qled_8k"
RTSP = "rtsp://user:pass@192.168.1.6:554/Streaming/channels/101"


class FakeGo2rtc:
    """Records stream registrations; answers go2rtc's MSE WebSocket handshake."""

    def __init__(self) -> None:
        self.streams: dict[str, str] = {}

    async def put_stream(self, request: web.Request) -> web.Response:
        self.streams[request.query["name"]] = request.query["src"]
        return web.Response(status=200)

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            if message.type is aiohttp.WSMsgType.TEXT:
                offer = json.loads(message.data)
                assert offer["type"] == "mse"
                await socket.send_str(json.dumps({"type": "mse", "value": "video/mp4"}))
                await socket.send_bytes(b"fmp4-init-" + request.query["src"].encode())
        return socket


@pytest.fixture
async def go2rtc(hass: HomeAssistant, aiohttp_server: Any) -> AsyncIterator[FakeGo2rtc]:
    fake = FakeGo2rtc()
    app = web.Application()
    app.router.add_put("/api/streams", fake.put_stream)
    app.router.add_get("/api/ws", fake.ws)
    server = await aiohttp_server(app)
    session = aiohttp.ClientSession()
    hass.data["go2rtc"] = SimpleNamespace(
        url=str(server.make_url("/")), session=session
    )
    yield fake
    await session.close()


@pytest.fixture(autouse=True)
async def internal_url(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )


def launched_payload(hass: HomeAssistant, tv: MagicMock) -> dict[str, Any]:
    """The command queued for the app, after a plain REST launch."""
    tv.launch_app.assert_awaited_with(SAMSTREAM_APP_ID)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    command = session_answer(hass, entry, 0)["command"]
    assert command is not None
    return command


@pytest.mark.usefixtures("go2rtc")
async def test_play_camera(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
    go2rtc: FakeGo2rtc,
) -> None:
    hass.states.async_set("camera.door", "idle", {"friendly_name": "Front door"})
    with patch(
        "custom_components.samstream.media_player.async_get_stream_source",
        AsyncMock(return_value=RTSP),
    ):
        await hass.services.async_call(
            DOMAIN,
            "play_stream",
            {"entity_id": TV, "camera": "camera.door", "message": "شخص عند الباب"},
            blocking=True,
        )

    name = stream_name(RTSP)
    assert go2rtc.streams == {name: RTSP}
    payload = launched_payload(hass, mock_tv)
    secret = setup_entry.data[CONF_TV_SECRET]
    assert payload == {
        "action": "play",
        "stream": {
            "label": "Front door",
            "url": f"ws://192.168.1.5:8123/api/samstream/tv/{secret}/stream/{name}",
            "type": "mse",
        },
        "message": "شخص عند الباب",
    }
    # No credentials in what the TV receives.
    assert "pass" not in json.dumps(payload)


@pytest.mark.usefixtures("setup_entry", "go2rtc")
async def test_play_url_and_wake_tv(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(
        type(coordinator.data)(is_on=False, info=coordinator.data.info)
    )
    mock_tv.is_on = AsyncMock(side_effect=[False, True])
    with patch("custom_components.samstream.media_player.asyncio.sleep", AsyncMock()):
        await hass.services.async_call(
            DOMAIN,
            "play_stream",
            {"entity_id": TV, "url": RTSP, "label": "Gate"},
            blocking=True,
        )

    mock_tv.power_on.assert_awaited_once()
    assert launched_payload(hass, mock_tv)["stream"]["label"] == "Gate"


@pytest.mark.usefixtures("setup_entry", "go2rtc")
async def test_tv_does_not_wake(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(
        type(coordinator.data)(is_on=False, info=coordinator.data.info)
    )
    mock_tv.is_on = AsyncMock(return_value=False)
    with (
        patch("custom_components.samstream.media_player.asyncio.sleep", AsyncMock()),
        pytest.raises(HomeAssistantError) as err,
    ):
        await hass.services.async_call(
            DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP}, blocking=True
        )
    assert err.value.translation_key == "tv_did_not_wake"
    mock_tv.launch_app.assert_not_awaited()


@pytest.mark.usefixtures("setup_entry", "go2rtc")
async def test_play_needs_a_source(hass: HomeAssistant) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "play_stream", {"entity_id": TV}, blocking=True
        )
    assert err.value.translation_key == "stream_source_required"


@pytest.mark.usefixtures("setup_entry", "go2rtc")
async def test_camera_without_stream(hass: HomeAssistant) -> None:
    with (
        patch(
            "custom_components.samstream.media_player.async_get_stream_source",
            AsyncMock(return_value=None),
        ),
        pytest.raises(ServiceValidationError) as err,
    ):
        await hass.services.async_call(
            DOMAIN,
            "play_stream",
            {"entity_id": TV, "camera": "camera.none"},
            blocking=True,
        )
    assert err.value.translation_key == "camera_no_stream"


@pytest.mark.usefixtures("setup_entry")
async def test_go2rtc_missing(hass: HomeAssistant) -> None:
    hass.data.pop("go2rtc", None)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP}, blocking=True
        )
    assert err.value.translation_key == "go2rtc_unavailable"


@pytest.mark.usefixtures("setup_entry", "go2rtc")
async def test_stop_stream(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await hass.services.async_call(
        DOMAIN, "stop_stream", {"entity_id": TV}, blocking=True
    )
    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_relay(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
    go2rtc: FakeGo2rtc,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await hass.services.async_call(
        DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP}, blocking=True
    )
    path = launched_payload(hass, mock_tv)["stream"]["url"].split("8123", 1)[1]
    client = await hass_client_no_auth()

    async with client.ws_connect(path) as socket:
        await socket.send_str(json.dumps({"type": "mse", "value": "avc1.640029"}))
        hello = await socket.receive_json(timeout=5)
        data = await socket.receive_bytes(timeout=5)

    assert hello == {"type": "mse", "value": "video/mp4"}
    assert data == b"fmp4-init-" + stream_name(RTSP).encode()


async def test_relay_rejects_wrong_secret_and_unknown_stream(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
    go2rtc: FakeGo2rtc,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await hass.services.async_call(
        DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP}, blocking=True
    )
    secret = setup_entry.data[CONF_TV_SECRET]
    client = await hass_client_no_auth()
    name = stream_name(RTSP)

    wrong = await client.get(f"/api/samstream/tv/nope/stream/{name}")
    assert wrong.status == 404
    unknown = await client.get(f"/api/samstream/tv/{secret}/stream/samstream_other")
    assert unknown.status == 404


async def test_session_view(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
    go2rtc: FakeGo2rtc,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "play_stream",
        {"entity_id": TV, "url": RTSP, "label": "Gate"},
        blocking=True,
    )
    secret = setup_entry.data[CONF_TV_SECRET]
    client = await hass_client_no_auth()

    first = await (
        await client.get(f"/api/samstream/tv/{secret}/session?since=0")
    ).json()
    assert first["settings"] == {"language": "auto", "theme": "light"}
    assert first["command"]["action"] == "play"
    assert first["command"]["stream"]["label"] == "Gate"

    seen = await (
        await client.get(f"/api/samstream/tv/{secret}/session?since={first['seq']}")
    ).json()
    assert seen["command"] is None

    await hass.services.async_call(
        DOMAIN, "stop_stream", {"entity_id": TV}, blocking=True
    )
    stop = await (
        await client.get(f"/api/samstream/tv/{secret}/session?since={first['seq']}")
    ).json()
    assert stop["command"] == {"action": "stop"}
    assert stop["seq"] == first["seq"] + 1

    assert (await client.get("/api/samstream/tv/nope/session")).status == 404


async def test_old_command_expires(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
    go2rtc: FakeGo2rtc,
) -> None:
    await hass.services.async_call(
        DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP}, blocking=True
    )
    later = time.monotonic() + 600
    with patch(
        "custom_components.samstream.tv_session.time.monotonic", return_value=later
    ):
        assert session_answer(hass, setup_entry, 0)["command"] is None
