"""play_stream interrupts what is on the TV; stop_stream or `duration` returns."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SAMSTREAM_APP_ID, SamstreamConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.samstream.const import DOMAIN
from custom_components.samstream.media_player import source_key
from custom_components.samstream.tv_session import (
    session_answer,
    signal_closed,
    signal_playing,
    signal_source,
)

from .conftest import YOUTUBE

TV = "media_player.65_neo_qled_8k"
RTSP = "rtsp://user:pass@192.168.1.6:554/Streaming/channels/101"
SLEEP = "custom_components.samstream.media_player.asyncio.sleep"

pytestmark = pytest.mark.usefixtures("setup_entry", "go2rtc")


@pytest.fixture
def go2rtc(hass: HomeAssistant) -> None:
    """Stream publishing is covered in test_stream; here it only has to succeed."""
    with (
        patch(
            "custom_components.samstream.media_player.async_publish_stream",
            AsyncMock(return_value="samstream_x"),
        ),
        patch(
            "custom_components.samstream.media_player.tv_stream_url",
            return_value="ws://192.168.1.5:8123/x",
        ),
    ):
        yield


@pytest.fixture
def watching_youtube(mock_tv: MagicMock) -> MagicMock:
    mock_tv.foreground_app = AsyncMock(return_value=replace(YOUTUBE, visible=True))
    # Every app reports visible: YouTube for the poll, Samstream for the return.
    mock_tv.app_status = AsyncMock(return_value=replace(YOUTUBE, visible=True))
    return mock_tv


def first_frame(hass: HomeAssistant) -> None:
    """The TV app reports the first frame of the latest play command."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    seq = session_answer(hass, entry, 0)["seq"]
    async_dispatcher_send(hass, signal_playing(entry.entry_id), seq)


def later(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


def keys(tv: MagicMock) -> list[str]:
    return [call.args[0][0] for call in tv.send_keys.await_args_list]


async def play(hass: HomeAssistant, **data: object) -> None:
    await hass.services.async_call(
        DOMAIN, "play_stream", {"entity_id": TV, "url": RTSP, **data}, blocking=True
    )


async def stop(hass: HomeAssistant) -> None:
    with patch(SLEEP, AsyncMock()):
        await hass.services.async_call(
            DOMAIN, "stop_stream", {"entity_id": TV}, blocking=True
        )


async def test_pause_then_resume_after_duration(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass, duration=30)
    assert keys(tv) == ["KEY_PAUSE"]
    tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)

    # The camera is not on screen yet: the countdown has not started.
    later(hass, 31)
    await hass.async_block_till_done()
    assert tv.launch_app.await_count == 1

    first_frame(hass)
    with patch(SLEEP, AsyncMock()):
        later(hass, 31 + 31)
        await hass.async_block_till_done()

    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)
    assert keys(tv) == ["KEY_PAUSE", "KEY_PLAY"]


async def test_returns_without_a_first_frame(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass, duration=10)
    with patch(SLEEP, AsyncMock()):
        later(hass, 10 + 31)
        await hass.async_block_till_done()
    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)


async def test_same_camera_counts_from_now(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    """A second trigger for the camera on screen (no reload) needs no new frame."""
    tv = watching_youtube
    await play(hass)
    first_frame(hass)
    first_frame(hass)  # Reported twice: ignored.
    await play(hass, duration=10)
    with patch(SLEEP, AsyncMock()):
        later(hass, 11)
        await hass.async_block_till_done()
    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)


async def test_old_first_frame_is_ignored(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass, duration=10)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    async_dispatcher_send(hass, signal_playing(entry.entry_id), 0)
    later(hass, 11)
    await hass.async_block_till_done()
    assert tv.launch_app.await_count == 1


async def test_new_trigger_keeps_the_original_app(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass, duration=30)
    # Samstream is in front now; the second trigger must not remember it.
    tv.foreground_app = AsyncMock(return_value=SimpleNamespace(app_id=SAMSTREAM_APP_ID))
    await play(hass)
    await stop(hass)

    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)
    assert keys(tv) == ["KEY_PAUSE", "KEY_PLAY"]
    # The second play had no duration: the first timer is gone.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
    await hass.async_block_till_done()
    assert tv.launch_app.await_count == 3


async def test_tv_was_off_turns_off_again(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(replace(coordinator.data, is_on=False))
    mock_tv.is_on = AsyncMock(return_value=True)
    mock_tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=True))
    with patch(SLEEP, AsyncMock()):
        await play(hass)
    mock_tv.power_on.assert_awaited_once()

    # Standby after the Power key.
    mock_tv.is_on = AsyncMock(return_value=False)
    await stop(hass)
    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
    mock_tv.power_off.assert_awaited_once()


async def test_turn_off_again_is_checked_and_retried(
    hass: HomeAssistant, mock_tv: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(replace(coordinator.data, is_on=False))
    mock_tv.is_on = AsyncMock(return_value=True)
    mock_tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=True))
    with patch(SLEEP, AsyncMock()):
        await play(hass)
    # The first Power key is swallowed; the TV stays on.
    await stop(hass)
    assert mock_tv.power_off.await_count == 2
    assert "did not go back to standby" in caplog.text


async def test_missed_wake_up_repeats_wake_on_lan(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(replace(coordinator.data, is_on=False))
    # On only at the 12th check: one repeat at 8 s.
    mock_tv.is_on = AsyncMock(side_effect=[False] * 11 + [True] * 50)
    mock_tv.wake_on_lan = AsyncMock()
    with patch(SLEEP, AsyncMock()):
        await play(hass)
    mock_tv.wake_on_lan.assert_awaited_once()


async def test_home_or_live_tv_closes_samstream(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=True))
    await play(hass)
    await stop(hass)

    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
    assert keys(mock_tv) == []


async def test_viewer_already_left(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass)
    tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=False))
    await stop(hass)

    tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
    tv.close_app.assert_not_awaited()


async def test_without_return(hass: HomeAssistant, watching_youtube: MagicMock) -> None:
    tv = watching_youtube
    await play(hass, return_to_previous=False)
    await stop(hass)

    assert keys(tv) == []
    tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_unknown_app_still_closes(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    """No app status, no foreground: act as asked."""
    mock_tv.foreground_app = AsyncMock(side_effect=SamstreamConnectionError("busy"))
    mock_tv.app_status = AsyncMock(side_effect=SamstreamConnectionError("busy"))
    await play(hass)
    await stop(hass)
    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_failed_launch_forgets_the_screen(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    tv.launch_app = AsyncMock(side_effect=SamstreamConnectionError("down"))
    with patch(SLEEP, AsyncMock()), pytest.raises(HomeAssistantError):
        await play(hass)
    tv.launch_app = AsyncMock()
    await stop(hass)
    tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_timed_return_failure_is_logged(
    hass: HomeAssistant, watching_youtube: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    tv = watching_youtube
    await play(hass, duration=5)
    first_frame(hass)
    tv.launch_app = AsyncMock(side_effect=SamstreamConnectionError("down"))
    with patch(SLEEP, AsyncMock()):
        later(hass, 6)
        await hass.async_block_till_done()
    assert "Could not return from the camera" in caplog.text


async def test_update_message_keeps_the_camera(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await play(hass, message="Someone at the door")
    first = session_answer(hass, entry, 0)

    await hass.services.async_call(
        DOMAIN,
        "update_message",
        {"entity_id": TV, "message": "A courier with a parcel"},
        blocking=True,
    )
    update = session_answer(hass, entry, first["seq"])
    assert update["command"] == {
        **first["command"],
        "message": "A courier with a parcel",
    }
    # Only the text changed: no new launch.
    mock_tv.launch_app.assert_awaited_once()


async def test_update_message_without_camera(hass: HomeAssistant) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await hass.services.async_call(
        DOMAIN, "update_message", {"entity_id": TV, "message": "late"}, blocking=True
    )
    assert session_answer(hass, entry, 0)["command"] is None

    await play(hass)
    await stop(hass)
    seq = session_answer(hass, entry, 0)["seq"]
    await hass.services.async_call(
        DOMAIN, "update_message", {"entity_id": TV, "message": "late"}, blocking=True
    )
    assert session_answer(hass, entry, 0)["seq"] == seq


async def test_app_paused_through_ha_stays_paused(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(replace(coordinator.data, app_id=YOUTUBE.app_id))
    await hass.services.async_call(
        "media_player", "media_pause", {"entity_id": TV}, blocking=True
    )
    tv.send_keys.reset_mock()

    await play(hass)
    await stop(hass)

    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)
    assert keys(tv) == []  # Neither Pause before nor Play after.


async def test_resume_switched_off(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options={"resume_playback": False})
    await hass.async_block_till_done()

    await play(hass)
    await stop(hass)

    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)
    assert keys(tv) == []


def closed(hass: HomeAssistant) -> None:
    """The TV app reports Back on the latest command."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    seq = session_answer(hass, entry, 0)["seq"]
    async_dispatcher_send(hass, signal_closed(entry.entry_id), seq)


async def test_back_on_tv_resumes_the_app_underneath(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    await play(hass, duration=30)
    with patch(SLEEP, AsyncMock()):
        closed(hass)
        await hass.async_block_till_done()
    # The TV is already back on YouTube: no relaunch, just Play.
    assert keys(tv) == ["KEY_PAUSE", "KEY_PLAY"]
    tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)

    # The duration timer went with it; a second report does nothing.
    with patch(SLEEP, AsyncMock()):
        later(hass, 120)
        closed(hass)
        await hass.async_block_till_done()
    assert keys(tv) == ["KEY_PAUSE", "KEY_PLAY"]
    tv.launch_app.assert_awaited_once()


async def test_back_keeps_a_paused_app_paused(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    tv = watching_youtube
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options={"resume_playback": False})
    await hass.async_block_till_done()
    await play(hass)
    with patch(SLEEP, AsyncMock()):
        closed(hass)
        await hass.async_block_till_done()
    assert keys(tv) == []


async def test_return_button(hass: HomeAssistant, watching_youtube: MagicMock) -> None:
    tv = watching_youtube
    await play(hass)
    with patch(SLEEP, AsyncMock()):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.65_neo_qled_8k_return_to_previous"},
            blocking=True,
        )
    tv.launch_app.assert_awaited_with(YOUTUBE.app_id)
    assert keys(tv) == ["KEY_PAUSE", "KEY_PLAY"]


@pytest.mark.parametrize(("source", "key"), [("TV1", "KEY_TV"), ("HDMI2", "KEY_HDMI2")])
async def test_return_to_the_input_the_tv_app_reported(
    hass: HomeAssistant, mock_tv: MagicMock, source: str, key: str
) -> None:
    """Over Live TV / HDMI, closing Samstream lands on Home: press the input."""
    mock_tv.app_status = AsyncMock(return_value=SimpleNamespace(visible=True))
    await play(hass, tv_corner="on")
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    seq = session_answer(hass, entry, 0)["seq"]
    async_dispatcher_send(hass, signal_source(entry.entry_id), seq, source)
    await stop(hass)

    mock_tv.close_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
    assert keys(mock_tv) == [key]


def test_source_key() -> None:
    assert source_key("TV1") == "KEY_TV"
    assert source_key("HDMI3") == "KEY_HDMI3"
    assert source_key("AV1") is None
    assert source_key(None) is None


@pytest.mark.parametrize(
    ("options", "requested", "expected"),
    [
        ({}, "on", "top_right"),  # The default corner.
        ({"tv_corner": "bottom_left"}, "on", "bottom_left"),  # The configured one.
        ({"tv_corner": "bottom_left"}, "top_left", "top_left"),  # Asked explicitly.
        ({}, "off", None),
    ],
)
async def test_corner_over_live_tv_or_home(
    hass: HomeAssistant,
    mock_tv: MagicMock,
    options: dict,
    requested: str,
    expected: str | None,
) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    await play(hass, tv_corner=requested)
    assert command_sent(hass)["tv_corner"] == expected
    assert ("mjpeg_url" in command_sent(hass)["stream"]) is (expected is not None)


async def test_no_corner_over_a_streaming_app(
    hass: HomeAssistant, watching_youtube: MagicMock
) -> None:
    """Over YouTube the TV window would replace it with Live TV: normal camera."""
    await play(hass, tv_corner="on")
    assert command_sent(hass)["tv_corner"] is None
    assert "mjpeg_url" not in command_sent(hass)["stream"]


def command_sent(hass: HomeAssistant) -> dict:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return session_answer(hass, entry, 0)["command"]
