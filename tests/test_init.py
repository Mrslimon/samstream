"""Setup works from stored data alone, so a TV that is off does not block it."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiosamstream import SamstreamConnectionError
from aiosamstream.ocf import OcfTvState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import (
    CONF_SCAN_INTERVAL,
    CONF_WOL_TARGET,
    DOMAIN,
)

from .conftest import MAC, UUID


async def test_setup_registers_device_and_unloads(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED

    registry = dr.async_get(hass)
    [device] = dr.async_entries_for_config_entry(registry, setup_entry.entry_id)
    assert (DOMAIN, UUID) in device.identifiers
    assert device.model == "QA65QN800CUXEG"
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in device.connections

    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    mock_tv.close.assert_awaited()


async def test_setup_with_tv_off(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    mock_tv.device_info.side_effect = SamstreamConnectionError("off")

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("media_player.65_neo_qled_8k").state == "off"


async def test_options_change_reloads(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "network"}
    )
    assert result["data_schema"]({})[CONF_WOL_TARGET] == "192.168.1.255"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_TARGET: "not an ip"}
    )
    assert result["errors"] == {CONF_WOL_TARGET: "invalid_address"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_TARGET: "192.168.1.11"}
    )
    await hass.async_block_till_done()

    assert setup_entry.options == {
        CONF_WOL_TARGET: "192.168.1.11",
        CONF_SCAN_INTERVAL: 10,
    }
    assert setup_entry.state is ConfigEntryState.LOADED
    coordinator = setup_entry.runtime_data.coordinator
    assert coordinator.wol_target == "192.168.1.11"


async def test_scan_interval_option(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    """The check interval is an option: default 10 s, changeable, applied on reload."""
    assert setup_entry.runtime_data.coordinator.update_interval == timedelta(seconds=10)
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "network"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_WOL_TARGET: "192.168.1.255", CONF_SCAN_INTERVAL: 45},
    )
    await hass.async_block_till_done()

    assert setup_entry.options[CONF_SCAN_INTERVAL] == 45
    coordinator = setup_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=45)


async def test_ocf_power_change_checks_immediately(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    """A power change the TV reports over local control does not wait for the poll."""
    coordinator = setup_entry.runtime_data.coordinator
    assert coordinator.data.is_on
    with (
        patch.object(coordinator, "ocf_state", return_value=OcfTvState(power=False)),
        patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh,
    ):
        coordinator.async_ocf_updated(MagicMock())
        await hass.async_block_till_done()
        refresh.assert_awaited_once()

        refresh.reset_mock()  # same power as we already know: nothing to do
        with patch.object(
            coordinator, "ocf_state", return_value=OcfTvState(power=True)
        ):
            coordinator.async_ocf_updated(MagicMock())
            await hass.async_block_till_done()
        refresh.assert_not_awaited()
