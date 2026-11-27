"""The native notifier client: signing, health, posting, key stamping."""

import hashlib
import hmac
import io
import re
import zipfile
from pathlib import Path

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.samstream.const import (
    CORNER_SIZES,
    CORNERS,
    MAX_CORNER_SECONDS,
    TEXT_POSITIONS,
    TEXT_SIZES,
)
from custom_components.samstream.notifier import (
    CAMERA_FIELDS,
    NOTIFIER_KEY_FILE,
    async_camera_message,
    async_close_camera,
    async_notifier_alive,
    async_post_native,
    async_show_camera,
    signed_camera_url,
    signed_notify_url,
    stamp_notifier_key,
)

HOST = "192.168.1.11"
SECRET = "the-per-tv-secret"


def test_signed_url_carries_a_verifiable_hmac() -> None:
    """The signature covers ts, nonce, title, content, icon and image."""
    url = signed_notify_url(
        HOST, SECRET, "Doorbell", "Someone is here", icon="alert", now=1000
    )
    q = url.query
    assert url.host == HOST
    assert url.port == 8181
    assert url.path == "/notify"
    assert q["ts"] == "1000"
    assert q["icon"] == "alert"
    message = (
        f"{q['ts']}\n{q['nonce']}\n{q['title']}\n{q['content']}\n"
        f"{q['icon']}\n{q['image']}"
    ).encode()
    expected = hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()
    assert q["sig"] == expected


def test_each_url_uses_a_fresh_nonce() -> None:
    """Two posts of the same text get different nonces (no replay by HA)."""
    a = signed_notify_url(HOST, SECRET, "t", "c", now=1000)
    b = signed_notify_url(HOST, SECRET, "t", "c", now=1000)
    assert a.query["nonce"] != b.query["nonce"]


def test_stamp_notifier_key_writes_the_shared_key() -> None:
    """Stamping adds res/shared.key with the secret, keeping other files."""
    src = io.BytesIO()
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("author-signature.xml", "<x/>")
        z.writestr(NOTIFIER_KEY_FILE, "stale")
    stamped = stamp_notifier_key(src.getvalue(), SECRET)
    with zipfile.ZipFile(io.BytesIO(stamped)) as z:
        assert z.read(NOTIFIER_KEY_FILE).decode() == SECRET
        assert z.read("author-signature.xml").decode() == "<x/>"
        # The key appears once, not duplicated.
        assert z.namelist().count(NOTIFIER_KEY_FILE) == 1


async def test_health_check(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}:8181/health", text="ok")
    assert await async_notifier_alive(hass, HOST) is True


async def test_health_check_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}:8181/health", status=404)
    assert await async_notifier_alive(hass, HOST) is False


async def test_post_native_ok(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"http://{HOST}:8181/notify", text='{"ok":true}')
    assert await async_post_native(hass, HOST, SECRET, "Hi", "There") is True
    sent = aioclient_mock.mock_calls[0][1]
    assert sent.query["title"] == "Hi"
    assert "sig" in sent.query


async def test_post_native_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 (bad/missing signature) is a soft miss, not an error."""
    aioclient_mock.get(f"http://{HOST}:8181/notify", status=401)
    assert await async_post_native(hass, HOST, SECRET, "Hi", "There") is False


async def test_post_native_unreachable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """No server at all: still never raises, returns False to fall back."""
    aioclient_mock.get(
        f"http://{HOST}:8181/notify", exc=aiohttp.ClientConnectionError()
    )
    assert await async_post_native(hass, HOST, SECRET, "Hi", "There") is False


VIEW = {
    "corner": "top_right",
    "size": "medium",
    "seconds": "30",
    "url": "http://192.168.1.5:8123/api/samstream/tv/s/mjpeg/n?size=medium",
    "title": "الباب",
    "message": "A parcel & a courier + more",
    "text_position": "bottom",
    "text_size": "normal",
}


def test_camera_url_signs_every_field() -> None:
    """The signature covers each field, in the order the notifier rebuilds them."""
    url = signed_camera_url(HOST, SECRET, VIEW, now=1000)
    q = url.query
    assert url.path == "/camera"
    # The values arrive as sent, also after the URL's own encoding.
    assert {key: q[key] for key in VIEW} == VIEW
    fields = [q["ts"], q["nonce"], "camera", *VIEW.values()]
    expected = hmac.new(
        SECRET.encode(), "\n".join(fields).encode(), hashlib.sha256
    ).hexdigest()
    assert q["sig"] == expected


def test_camera_url_bounds_long_text() -> None:
    url = signed_camera_url(HOST, SECRET, {**VIEW, "message": "x" * 5000})
    assert len(url.query["message"]) == 300


async def test_camera_requests_are_posts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    for path in ("camera", "camera/message", "camera/close"):
        aioclient_mock.post(f"http://{HOST}:8181/{path}")
    assert await async_show_camera(hass, HOST, SECRET, VIEW)
    assert await async_camera_message(hass, HOST, SECRET, "new")
    assert await async_close_camera(hass, HOST, SECRET)
    assert [call[0] for call in aioclient_mock.mock_calls] == ["POST"] * 3


@pytest.mark.parametrize(
    "answer", [{"status": 401}, {"exc": aiohttp.ClientConnectionError()}]
)
async def test_camera_miss_is_soft(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, answer: dict
) -> None:
    aioclient_mock.post(f"http://{HOST}:8181/camera", **answer)
    assert not await async_show_camera(hass, HOST, SECRET, VIEW)


def test_notifier_accepts_what_home_assistant_sends() -> None:
    """The C# side cannot run here: its literals must still match this side's."""
    folder = Path(__file__).parent.parent / "tv-app" / "notifier-dotnet"
    camera = (folder / "CornerCamera.cs").read_text(encoding="utf-8")
    program = (folder / "Program.cs").read_text(encoding="utf-8")

    def keys(table: str) -> tuple[str, ...]:
        body = re.search(rf"> {table} = new .*?\n        \}};", camera, re.DOTALL)
        assert body
        return tuple(re.findall(r'\{ "(\w+)",', body[0]))

    assert keys("Sizes") == CORNER_SIZES
    assert keys("TextSizes") == TEXT_SIZES
    for value in (*CORNERS, *TEXT_POSITIONS):
        assert f'"{value}"' in camera
    for name in CAMERA_FIELDS:
        assert f'q["{name}"]' in program
    assert f"hold > {MAX_CORNER_SECONDS}" in program
