"""The Samstream integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = []

type SamstreamConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Set up Samstream from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
