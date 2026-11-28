"""play_stream in a corner: the notifier draws the camera over what is playing."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SAMSTREAM_APP_ID, AppStatus, SamstreamConnectionError
from aiosamstream.ocf.state import OcfTvState
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.util import dt as dt_util

from custom_components.samstream.const import CONF_TV_SECRET, DOMAIN
from custom_components.samstream.tv_session import session_answer

from .conftest import HOST, YOUTUBE

TV = "media_player.65_neo_qled_8k"
RTSP = "rtsp://user:pass@192.168.1.6:554/Streaming/channels/101"
PLAYER = "custom_components.samstream.media_player"

pytestmark = pytest.mark.usefixtures("setup_entry", "camera")


@pytest.fixture
async def camera(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )
    hass.states.async_set("camera.door", "idle", {"friendly_name": "Front door"})
    with (
        patch(f"{PLAYER}.async_get_stream_source", AsyncMock(return_value=RTSP)),
        patch(f"{PLAYER}.async_publish_stream", AsyncMock(return_value="cam")),
        patch(f"{PLAYER}.asyncio.sleep", AsyncMock()),
    ):
        yield


@pytest.fixture
def watching_youtube(mock_tv: MagicMock) -> MagicMock:
    mock_tv.foreground_app = AsyncMock(return_value=replace(YOUTUBE, visible=True))
    mock_tv.app_status = AsyncMock(return_value=replace(YOUTUBE, visible=True))
    return mock_tv


@pytest.fixture
def notifier(no_notifier: dict[str, AsyncMock]) -> dict[str, AsyncMock]:
    """A running notifier that accepts everything."""
    for call in ("show", "message", "close", "alive"):
        no_notifier[call].return_value = True
    return no_notifier


async def action(hass: HomeAssistant, name: str, **data: object) -> None:
    await hass.services.async_call(
        DOMAIN, name, {"entity_id": TV, **data}, blocking=True
    )


async def play(hass: HomeAssistant, **data: object) -> None:
    await action(hass, "play_stream", camera="camera.door", **data)


def view(notifier: dict[str, AsyncMock]) -> dict[str, str]:
    return notifier["show"].await_args.args[3]


def command(hass: HomeAssistant) -> dict | None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return session_answer(hass, entry, 0)["command"]


def set_options(hass: HomeAssistant, **options: object) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(entry, options=options)


async def test_corner_over_an_app(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    """Nothing is paused, opened or taken over."""
    await play(hass, message="شخص عند الباب")

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    secret = entry.data[CONF_TV_SECRET]
    assert notifier["show"].await_args.args[1:3] == (HOST, secret)
    assert view(notifier) == {
        "corner": "top_right",
        "size": "large",
        "seconds": "30",
        "url": f"http://192.168.1.5:8123/api/samstream/tv/{secret}/mjpeg/cam?size=large",
        "title": "Front door",
        "message": "شخص عند الباب",
        "text_position": "bottom",
        "text_size": "large",
    }
    watching_youtube.launch_app.assert_not_called()
    watching_youtube.send_keys.assert_not_called()
    assert command(hass) is None


async def test_corner_follows_the_cameras_settings(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    set_options(
        hass,
        tv_corner="bottom_left",
        corner_size="small",
        corner_seconds=90,
        text_position="top",
        text_size="extra_large",
    )
    await hass.async_block_till_done()
    await play(hass)
    shown = view(notifier)
    assert shown["corner"] == "bottom_left"
    assert shown["size"] == "small"
    assert shown["url"].endswith("?size=small")
    assert shown["seconds"] == "90"
    assert (shown["text_position"], shown["text_size"]) == ("top", "extra_large")


async def test_action_fields_win_over_the_settings(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    set_options(hass, corner_view=False, tv_corner="bottom_left")
    await hass.async_block_till_done()
    await play(
        hass, corner=True, corner_position="top_left", corner_size="small", duration=7
    )
    shown = view(notifier)
    assert (shown["corner"], shown["size"], shown["seconds"]) == (
        "top_left",
        "small",
        "7",
    )


@pytest.mark.parametrize(
    ("data", "options"),
    [
        ({"corner": False}, {}),
        ({}, {"corner_view": False}),
        ({"tv_corner": "off"}, {}),  # The former field, still accepted.
    ],
)
async def test_full_screen_when_asked(
    hass: HomeAssistant,
    watching_youtube: MagicMock,
    notifier: dict,
    data: dict,
    options: dict,
) -> None:
    set_options(hass, **options)
    await hass.async_block_till_done()
    await play(hass, **data)
    notifier["show"].assert_not_called()
    watching_youtube.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
    assert command(hass)["action"] == "play"
    assert command(hass)["text_position"] == "bottom"


async def test_former_corner_field_picks_the_corner(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    await play(hass, tv_corner="bottom_right")
    assert view(notifier)["corner"] == "bottom_right"


async def test_full_screen_when_the_tv_is_off(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict
) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(replace(coordinator.data, is_on=False))
    mock_tv.is_on = AsyncMock(return_value=True)
    await play(hass)
    notifier["show"].assert_not_called()
    mock_tv.power_on.assert_awaited_once()
    mock_tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_corner_without_a_known_app(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict
) -> None:
    """Without local control Home, Live TV and HDMI look alike: never interrupt."""
    await play(hass)
    notifier["show"].assert_awaited_once()
    mock_tv.launch_app.assert_not_called()


async def test_full_screen_when_samstream_is_showing(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict
) -> None:
    mock_tv.foreground_app = AsyncMock(
        return_value=AppStatus(SAMSTREAM_APP_ID, "Samstream", True, True, "0.14.0")
    )
    mock_tv.installed_apps = AsyncMock(return_value=[])
    await play(hass)
    notifier["show"].assert_not_called()
    mock_tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_corner_when_the_screen_cannot_be_read(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict
) -> None:
    mock_tv.foreground_app = AsyncMock(side_effect=SamstreamConnectionError("busy"))
    await play(hass)
    notifier["show"].assert_awaited_once()


def local_control_reports(app_id: str) -> object:
    """Local control naming `app_id` as the app in front."""
    coordinator = "custom_components.samstream.coordinator.SamstreamCoordinator"
    state = OcfTvState(content_input="webapp", app_id=app_id)
    return patch(f"{coordinator}.ocf_state", return_value=state)


@pytest.mark.parametrize(
    "app_id", ["9Ur5IzDKqV.TizenYouTube", "org.samstream.notifier"]
)
async def test_corner_when_only_local_control_sees_the_app(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict, app_id: str
) -> None:
    with local_control_reports(app_id):
        await play(hass)
    notifier["show"].assert_awaited_once()
    mock_tv.launch_app.assert_not_called()


@pytest.mark.parametrize("app_id", ["com.samsung.tv.csfs", SAMSTREAM_APP_ID])
async def test_full_screen_on_home_with_local_control(
    hass: HomeAssistant, mock_tv: MagicMock, notifier: dict, app_id: str
) -> None:
    with local_control_reports(app_id):
        await play(hass)
    notifier["show"].assert_not_called()
    mock_tv.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_second_call_stays_in_the_corner(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    """While the box is up, a TV reporting no app does not turn it full screen."""
    await play(hass)
    watching_youtube.foreground_app.return_value = None
    watching_youtube.app_status.return_value = None
    with local_control_reports("com.samsung.tv.csfs"):
        await play(hass)
    assert notifier["show"].await_count == 2
    watching_youtube.launch_app.assert_not_called()


async def test_stopped_notifier_is_started(
    hass: HomeAssistant, watching_youtube: MagicMock, no_notifier: dict
) -> None:
    no_notifier["show"].side_effect = [False, True]
    no_notifier["alive"].side_effect = [False, False, True]
    no_notifier["start"].return_value = True
    await play(hass)
    no_notifier["start"].assert_awaited_once()
    assert no_notifier["show"].await_count == 2
    watching_youtube.launch_app.assert_not_called()


async def test_old_notifier_falls_back_to_full_screen(
    hass: HomeAssistant, watching_youtube: MagicMock, no_notifier: dict
) -> None:
    """Running but refusing (an older TV app): no restart, the camera still shows."""
    no_notifier["alive"].return_value = True
    await play(hass)
    no_notifier["start"].assert_not_called()
    watching_youtube.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_notifier_that_does_not_start(
    hass: HomeAssistant, watching_youtube: MagicMock, no_notifier: dict
) -> None:
    no_notifier["start"].return_value = True
    await play(hass)
    watching_youtube.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)


async def test_stop_removes_only_the_corner(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    await play(hass)
    await action(hass, "update_message", message="A courier")
    assert notifier["message"].await_args.args[3] == "A courier"
    await action(hass, "stop_stream")
    notifier["close"].assert_awaited_once()
    watching_youtube.close_app.assert_not_called()
    watching_youtube.launch_app.assert_not_called()
    watching_youtube.send_keys.assert_not_called()
    assert command(hass) is None


async def test_nothing_reaches_a_corner_that_has_ended(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    await play(hass, duration=5)
    later = hass.loop.time() + timedelta(seconds=6).total_seconds()
    with patch.object(hass.loop, "time", return_value=later):
        await action(hass, "update_message", message="late")
        await action(hass, "stop_stream")
    notifier["message"].assert_not_called()
    notifier["close"].assert_not_called()
    watching_youtube.close_app.assert_not_called()
    assert dt_util.utcnow()  # The test's clock patch is undone.


async def test_full_screen_replaces_the_corner(
    hass: HomeAssistant, watching_youtube: MagicMock, notifier: dict
) -> None:
    await play(hass)
    await play(hass, corner=False)
    notifier["close"].assert_awaited_once()
    watching_youtube.launch_app.assert_awaited_once_with(SAMSTREAM_APP_ID)
