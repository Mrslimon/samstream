"""The "Samstream is set up" screen after local control connects."""

from unittest.mock import AsyncMock, MagicMock, patch

from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import CONF_OCF_WELCOME
from custom_components.samstream.media_player import SamstreamMediaPlayer


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_welcome_waits_for_the_app_then_shows_once(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_OCF_WELCOME: True}
    )
    shown = AsyncMock()
    with patch.object(SamstreamMediaPlayer, "async_show_message", shown):
        await _setup(hass, mock_entry)
        # The Samstream app is not on the TV yet (first setup): wait.
        shown.assert_not_called()
        assert mock_entry.data[CONF_OCF_WELCOME] is True

        coordinator = mock_entry.runtime_data.coordinator
        coordinator.apps = {**coordinator.apps, SAMSTREAM_APP_ID: "Samstream"}
        coordinator.async_update_listeners()
        await hass.async_block_till_done()
        shown.assert_awaited_once()
        assert shown.await_args.kwargs["severity"] == "success"
        assert shown.await_args.kwargs["return_to_previous"] is True
        assert CONF_OCF_WELCOME not in mock_entry.data

        # Never again.
        coordinator.async_update_listeners()
        await hass.async_block_till_done()
        shown.assert_awaited_once()


async def test_no_welcome_without_the_flag(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    shown = AsyncMock()
    with patch.object(SamstreamMediaPlayer, "async_show_message", shown):
        await _setup(hass, mock_entry)
        coordinator = mock_entry.runtime_data.coordinator
        coordinator.apps = {**coordinator.apps, SAMSTREAM_APP_ID: "Samstream"}
        coordinator.async_update_listeners()
        await hass.async_block_till_done()
    shown.assert_not_called()
