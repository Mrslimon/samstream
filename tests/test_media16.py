"""Full-screen messages with sound, and media library files on the TV."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.components import media_source
from homeassistant.components.media_player import BrowseMedia, MediaClass
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.samstream.const import DOMAIN
from custom_components.samstream.tv_session import session_answer, signal_ended

TV = "media_player.65_neo_qled_8k"
SLEEP = "custom_components.samstream.media_player.asyncio.sleep"
TTS = "media-source://tts/tts.google_translate_ar_com?message=hello"

pytestmark = pytest.mark.usefixtures("setup_entry")


@pytest.fixture(autouse=True)
async def internal_url(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )


def command(hass: HomeAssistant) -> dict:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return session_answer(hass, entry, 0)["command"]


def resolved(url: str, mime: str) -> AsyncMock:
    return AsyncMock(return_value=media_source.PlayMedia(url, mime))


async def show(hass: HomeAssistant, **data: object) -> None:
    await hass.services.async_call(
        DOMAIN, "show_message", {"entity_id": TV, **data}, blocking=True
    )


async def play_media(hass: HomeAssistant, media_type: str, media_id: str) -> None:
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": TV,
            "media_content_type": media_type,
            "media_content_id": media_id,
        },
        blocking=True,
    )


async def test_show_message(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await show(hass, title="الباب الأمامي", message="شخص عند الباب", severity="alert")

    assert command(hass) == {
        "action": "notice",
        "title": "الباب الأمامي",
        "message": "شخص عند الباب",
        "severity": "alert",
        "sound": None,
    }
    mock_tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_message_needs_text(hass: HomeAssistant) -> None:
    with pytest.raises(ServiceValidationError):
        await show(hass, severity="info")


async def test_sound_from_tts(hass: HomeAssistant) -> None:
    with patch.object(
        media_source,
        "async_resolve_media",
        resolved("/api/tts_proxy/abc.mp3", "audio/mpeg"),
    ):
        await show(
            hass,
            message="Doorbell",
            sound={"media_content_id": TTS, "media_content_type": "provider"},
        )
    # Absolute, on HA's local address (TTS audio needs no signature).
    assert command(hass)["sound"] == "http://192.168.1.5:8123/api/tts_proxy/abc.mp3"


async def test_sound_url(hass: HomeAssistant) -> None:
    await show(hass, message="Chime", sound="https://example.com/chime.mp3")
    assert command(hass)["sound"] == "https://example.com/chime.mp3"


async def test_unresolvable_sound(hass: HomeAssistant) -> None:
    with (
        patch.object(
            media_source,
            "async_resolve_media",
            AsyncMock(side_effect=media_source.Unresolvable("gone")),
        ),
        pytest.raises(ServiceValidationError),
    ):
        await show(hass, message="x", sound=TTS)


async def test_play_library_video(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    with patch.object(
        media_source,
        "async_resolve_media",
        resolved("/media/local/clips/garden.mp4", "video/mp4"),
    ):
        await play_media(
            hass, "video/mp4", "media-source://media_source/local/garden.mp4"
        )

    sent = command(hass)
    assert sent["action"] == "media"
    assert sent["kind"] == "video"
    assert sent["title"] == "garden"
    assert sent["url"].startswith(
        "http://192.168.1.5:8123/media/local/clips/garden.mp4?authSig="
    )
    mock_tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_play_audio_url(hass: HomeAssistant) -> None:
    await play_media(hass, "music", "http://192.168.1.9/radio/news.mp3?x=1")
    sent = command(hass)
    assert sent["kind"] == "audio"
    assert sent["title"] == "news"
    assert sent["url"] == "http://192.168.1.9/radio/news.mp3?x=1"


async def test_unsupported_media(hass: HomeAssistant) -> None:
    with pytest.raises(ServiceValidationError):
        await play_media(hass, "playlist", "my favourites")


async def test_video_end_returns(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    mock_tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=True))
    await play_media(hass, "video", "http://192.168.1.9/clip.mp4")
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    seq = session_answer(hass, entry, 0)["seq"]

    async_dispatcher_send(hass, signal_ended(entry.entry_id), seq - 1)  # Old: ignored.
    await hass.async_block_till_done()
    mock_tv.close_app.assert_not_awaited()

    with patch(SLEEP, AsyncMock()):
        async_dispatcher_send(hass, signal_ended(entry.entry_id), seq)
        await hass.async_block_till_done()
    # Home was underneath: closing Samstream returns there.
    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_update_message_on_notice(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    await show(hass, title="Camera", message="Analysing…")
    await hass.services.async_call(
        DOMAIN,
        "update_message",
        {"entity_id": TV, "message": "A courier with a parcel"},
        blocking=True,
    )
    assert command(hass)["message"] == "A courier with a parcel"
    assert command(hass)["title"] == "Camera"
    mock_tv.launch_app.assert_awaited_once()


async def test_browse_media(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    library = BrowseMedia(
        media_class=MediaClass.DIRECTORY,
        media_content_id="media-source://media_source",
        media_content_type="",
        title="Media",
        can_play=False,
        can_expand=True,
    )
    browse = AsyncMock(return_value=library)
    with patch.object(media_source, "async_browse_media", browse):
        client = await hass_ws_client(hass)
        await client.send_json_auto_id(
            {"type": "media_player/browse_media", "entity_id": TV}
        )
        answer = await client.receive_json()

    assert answer["success"], answer
    assert answer["result"]["title"] == "Media"
    keep = browse.await_args.kwargs["content_filter"]
    assert keep(SimpleNamespace(media_content_type="video/mp4"))
    assert keep(SimpleNamespace(media_content_type="audio/mpeg"))
    assert not keep(SimpleNamespace(media_content_type="image/png"))
