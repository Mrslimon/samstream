"""Installed apps as sources, the app on screen, and the launch/close actions."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiosamstream import ListedApp, SamstreamConnectionError
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.samstream.const import (
    CONF_EXTRA_APPS,
    CONF_WOL_TARGET,
    DOMAIN,
)

from .conftest import NETFLIX

TV = "media_player.65_neo_qled_8k"
CURRENT_APP = "sensor.65_neo_qled_8k_current_app"


async def _poll(hass: HomeAssistant, seconds: int = 11) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


@pytest.mark.usefixtures("setup_entry")
async def test_sources_and_app_on_screen(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    state = hass.states.get(TV)
    assert state.attributes["source_list"] == ["Netflix", "YouTube"]
    assert "source" not in state.attributes
    assert hass.states.get(CURRENT_APP).state == "unknown"

    mock_tv.foreground_app.return_value = replace(NETFLIX, visible=True)
    await _poll(hass)

    state = hass.states.get(TV)
    assert state.attributes["source"] == "Netflix"
    assert state.attributes["app_id"] == "3201907018807"
    assert state.attributes["app_name"] == "Netflix"
    sensor = hass.states.get(CURRENT_APP)
    assert sensor.state == "Netflix"
    assert sensor.attributes["app_id"] == "3201907018807"


@pytest.mark.usefixtures("setup_entry")
async def test_apps_scanned_once_then_cached(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    await _poll(hass)
    await _poll(hass, 22)

    mock_tv.installed_apps.assert_awaited_once()
    assert mock_tv.foreground_app.await_count >= 3


async def test_extra_app_ids_are_scanned(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    hass.config_entries.async_update_entry(
        mock_entry,
        options={CONF_WOL_TARGET: "192.168.1.255", CONF_EXTRA_APPS: "my.app other.app"},
    )
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    scanned = mock_tv.installed_apps.await_args.args[0]
    assert scanned[-2:] == ["my.app", "other.app"]
    assert "111299001912" in scanned


@pytest.mark.usefixtures("setup_entry")
async def test_select_source_launches_app(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    await hass.services.async_call(
        "media_player",
        "select_source",
        {ATTR_ENTITY_ID: TV, ATTR_INPUT_SOURCE: "YouTube"},
        blocking=True,
    )

    mock_tv.launch_app.assert_awaited_once_with("111299001912")
    assert hass.states.get(TV).attributes["source"] == "YouTube"


@pytest.mark.usefixtures("setup_entry")
async def test_select_unknown_source(hass: HomeAssistant) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "media_player",
            "select_source",
            {ATTR_ENTITY_ID: TV, ATTR_INPUT_SOURCE: "Kodi"},
            blocking=True,
        )
    assert err.value.translation_key == "unknown_source"


@pytest.mark.usefixtures("setup_entry")
async def test_play_media_app(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            ATTR_ENTITY_ID: TV,
            ATTR_MEDIA_CONTENT_TYPE: "app",
            ATTR_MEDIA_CONTENT_ID: "3201907018807",
        },
        blocking=True,
    )
    mock_tv.launch_app.assert_awaited_once_with("3201907018807")

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                ATTR_ENTITY_ID: TV,
                ATTR_MEDIA_CONTENT_TYPE: "video",
                ATTR_MEDIA_CONTENT_ID: "http://x/y.mp4",
            },
            blocking=True,
        )
    assert err.value.translation_key == "unsupported_media_type"


@pytest.mark.usefixtures("setup_entry")
async def test_launch_and_close_actions(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "launch_app",
        {ATTR_ENTITY_ID: TV, "app_id": "3201907018807"},
        blocking=True,
    )
    mock_tv.launch_app.assert_awaited_once_with("3201907018807")
    assert hass.states.get(CURRENT_APP).state == "Netflix"

    await hass.services.async_call(
        DOMAIN,
        "close_app",
        {ATTR_ENTITY_ID: TV, "app_id": "3201907018807"},
        blocking=True,
    )
    mock_tv.close_app.assert_awaited_once_with("3201907018807")
    assert hass.states.get(CURRENT_APP).state == "unknown"


@pytest.mark.usefixtures("setup_entry")
async def test_close_other_app_keeps_current(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.foreground_app.return_value = replace(NETFLIX, visible=True)
    await _poll(hass)

    await hass.services.async_call(
        DOMAIN,
        "close_app",
        {ATTR_ENTITY_ID: TV, "app_id": "111299001912"},
        blocking=True,
    )
    assert hass.states.get(CURRENT_APP).state == "Netflix"


@pytest.mark.usefixtures("setup_entry")
async def test_app_status_failure_keeps_tv_on(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.foreground_app.side_effect = SamstreamConnectionError("busy")
    await _poll(hass)

    assert hass.states.get(TV).state == "on"
    assert hass.states.get(CURRENT_APP).state == "unknown"


async def test_failed_scan_retried_next_poll(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    mock_tv.installed_apps.side_effect = [SamstreamConnectionError("busy"), []]
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    # HA leaves an empty source list out of the attributes.
    assert mock_entry.runtime_data.coordinator.apps == {}

    await _poll(hass)
    assert mock_tv.installed_apps.await_count == 2


async def test_full_app_list_from_sdb(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_EXTRA_APPS: "111477000821 my.extra"}
    )
    mock_tv.list_apps.return_value = [
        ListedApp("111299001912", "9Ur5IzDKqV.TizenYouTube", "YouTube", "2.1.527"),
        ListedApp("111477000821", "Ggl33q588H.MBC", "شاهد MBC", "6.68.1"),
    ]
    mock_tv.installed_apps.return_value = []
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_entry.runtime_data.coordinator
    assert coordinator.app_source == "tv"
    assert coordinator.apps == {"111299001912": "YouTube", "111477000821": "شاهد MBC"}
    assert coordinator.app_versions["111477000821"] == "6.68.1"
    # Only the extra ID the TV did not list is probed over REST.
    mock_tv.installed_apps.assert_awaited_once_with(["my.extra"])
    assert hass.states.get(TV).attributes["source_list"] == ["YouTube", "شاهد MBC"]


@pytest.mark.usefixtures("setup_entry")
async def test_catalog_when_sdb_unavailable(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    assert coordinator.app_source == "catalog"
    scanned = mock_tv.installed_apps.await_args.args[0]
    assert "111299001912" in scanned


@pytest.mark.usefixtures("setup_entry")
async def test_last_app_checked_first(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    mock_tv.foreground_app.return_value = replace(NETFLIX, visible=True)
    await _poll(hass)
    assert hass.states.get(CURRENT_APP).state == "Netflix"

    mock_tv.foreground_app.reset_mock()
    mock_tv.app_status = AsyncMock(return_value=replace(NETFLIX, visible=True))
    await _poll(hass)

    mock_tv.app_status.assert_awaited_once_with("3201907018807")
    mock_tv.foreground_app.assert_not_awaited()
    assert hass.states.get(CURRENT_APP).state == "Netflix"

    # Netflix closed: fall back to the full check.
    mock_tv.app_status.return_value = replace(NETFLIX, visible=False)
    mock_tv.foreground_app.return_value = None
    await _poll(hass)
    mock_tv.foreground_app.assert_awaited_once()
    assert hass.states.get(CURRENT_APP).state == "unknown"
