"""Setup works from stored data alone, so a TV that is off does not block it."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import CONF_TOKEN, DOMAIN


async def test_setup_registers_device_and_unloads(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="uuid-1",
        title="Living room TV",
        data={
            CONF_HOST: "192.168.1.11",
            CONF_TOKEN: "token",
            CONF_MAC: "aa:bb:cc:00:11:22",
            CONF_MODEL: "QA65QN800CUXEG",
            CONF_NAME: "Living room TV",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "uuid-1")})
    assert device is not None
    assert device.model == "QA65QN800CUXEG"
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:00:11:22") in device.connections
    assert entry.runtime_data.tv.token == "token"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
