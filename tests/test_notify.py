"""notify.send_message: native TV notification first, on-screen notice fallback."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.samstream.media_player import SamstreamMediaPlayer

NOTIFY = "notify.65_neo_qled_8k_notifications"


@pytest.mark.usefixtures("setup_entry")
async def test_falls_back_to_the_tv_notice(hass: HomeAssistant) -> None:
    """When the native notifier is unreachable, show the message on the app."""
    assert hass.states.get(NOTIFY) is not None
    with (
        patch(
            "custom_components.samstream.notify.async_post_native",
            AsyncMock(return_value=False),
        ) as native,
        patch.object(SamstreamMediaPlayer, "async_show_message", AsyncMock()) as shown,
    ):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": NOTIFY, "title": "Doorbell", "message": "Someone is here"},
            blocking=True,
        )
    assert native.await_args.args[3] == "Doorbell"
    assert native.await_args.args[4] == "Someone is here"
    assert shown.await_args.kwargs["message"] == "Someone is here"
    assert shown.await_args.kwargs["title"] == "Doorbell"
    assert shown.await_args.kwargs["duration"] == 10.0
    assert shown.await_args.kwargs["return_to_previous"] is True


@pytest.mark.usefixtures("setup_entry")
async def test_identical_message_is_not_repeated(hass: HomeAssistant) -> None:
    """A flood of the same message posts once; a different one still gets through."""
    with patch(
        "custom_components.samstream.notify.async_post_native",
        AsyncMock(return_value=True),
    ) as native:
        for _ in range(3):
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": NOTIFY, "title": "Motion", "message": "Driveway"},
                blocking=True,
            )
        assert native.await_count == 1

        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": NOTIFY, "title": "Motion", "message": "Back gate"},
            blocking=True,
        )
        assert native.await_count == 2


@pytest.mark.usefixtures("setup_entry")
async def test_native_notifier_skips_the_notice(hass: HomeAssistant) -> None:
    """A successful native post must not also take over the screen."""
    with (
        patch(
            "custom_components.samstream.notify.async_post_native",
            AsyncMock(return_value=True),
        ),
        patch.object(SamstreamMediaPlayer, "async_show_message", AsyncMock()) as shown,
    ):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": NOTIFY, "title": "Doorbell", "message": "Someone is here"},
            blocking=True,
        )
    shown.assert_not_awaited()
