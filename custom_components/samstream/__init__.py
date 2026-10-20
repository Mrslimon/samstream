"""The Samstream integration."""

from __future__ import annotations

from dataclasses import dataclass

from aiosamstream import SamsungTV
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_TOKEN, DOMAIN

PLATFORMS: list[Platform] = []


@dataclass
class SamstreamData:
    """Runtime objects for one TV."""

    tv: SamsungTV


type SamstreamConfigEntry = ConfigEntry[SamstreamData]


async def async_setup_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Set up Samstream from a config entry.

    The TV is often off, so setup only uses what the config flow stored; talking to
    the TV (and availability) is the coordinator's job from milestone 5.
    """
    tv = SamsungTV(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        token=entry.data.get(CONF_TOKEN),
    )
    entry.runtime_data = SamstreamData(tv=tv)

    connections = set()
    if mac := entry.data.get(CONF_MAC):
        connections.add((dr.CONNECTION_NETWORK_MAC, mac))
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        connections=connections,
        manufacturer="Samsung",
        model=entry.data.get(CONF_MODEL),
        name=entry.data.get(CONF_NAME) or entry.title,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
