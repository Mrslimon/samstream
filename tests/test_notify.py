"""notify.send_message shows the message on the TV, then returns."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.samstream.media_player import SamstreamMediaPlayer

NOTIFY = "notify.65_neo_qled_8k_notifications"


@pytest.mark.usefixtures("setup_entry")
async def test_send_message_shows_it_on_the_tv(hass: HomeAssistant) -> None:
    assert hass.states.get(NOTIFY) is not None
    with patch.object(SamstreamMediaPlayer, "async_show_message", AsyncMock()) as shown:
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": NOTIFY, "title": "Doorbell", "message": "Someone is here"},
            blocking=True,
        )
    assert shown.await_args.kwargs["message"] == "Someone is here"
    assert shown.await_args.kwargs["title"] == "Doorbell"
    assert shown.await_args.kwargs["duration"] == 10.0
    assert shown.await_args.kwargs["return_to_previous"] is True
