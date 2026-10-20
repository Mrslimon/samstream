"""Setup works from stored data alone, so a TV that is off does not block it."""

from unittest.mock import MagicMock

from aiosamstream import SamstreamConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import CONF_WOL_TARGET, DOMAIN

from .conftest import MAC, UUID


async def test_setup_registers_device_and_unloads(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, UUID)})
    assert device is not None
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
    assert result["data_schema"]({})[CONF_WOL_TARGET] == "192.168.1.255"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_TARGET: "not an ip"}
    )
    assert result["errors"] == {CONF_WOL_TARGET: "invalid_address"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_TARGET: "192.168.1.11"}
    )
    await hass.async_block_till_done()

    assert setup_entry.options == {CONF_WOL_TARGET: "192.168.1.11"}
    assert setup_entry.state is ConfigEntryState.LOADED
    coordinator = setup_entry.runtime_data.coordinator
    assert coordinator.wol_target == "192.168.1.11"
