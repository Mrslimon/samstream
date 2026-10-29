"""Art Mode on a Frame TV, with local control on (the TV reports Art Mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import CONF_OCF, DOMAIN
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Art Mode switch for a Frame with local control."""
    coordinator = entry.runtime_data.coordinator
    if entry.options.get(CONF_OCF) and _is_frame(entry):
        async_add_entities([ArtModeSwitch(coordinator)])


def _is_frame(entry: SamstreamConfigEntry) -> bool:
    """Tell a Frame: the TV says so, or (TV off at start) its model is an LS03."""
    data = entry.runtime_data.coordinator.data
    if data is not None and data.info is not None:
        return data.info.frame_tv
    return "LS03" in str(entry.data.get(CONF_MODEL, "")).upper()


class ArtModeSwitch(SamstreamEntity, SwitchEntity):
    """On while the Frame shows art.

    On goes straight to Art Mode (local control); off is the power key, which
    on a Frame flips from Art Mode back to TV.
    """

    _attr_translation_key = "art_mode"

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the switch for the coordinator's TV."""
        super().__init__(coordinator, "art_mode")

    @property
    def available(self) -> bool:
        """While the TV reports what it shows over local control."""
        ocf = self.coordinator.data.ocf
        return super().available and ocf is not None and ocf.art_mode is not None

    @property
    def is_on(self) -> bool | None:
        """Art Mode as the TV reports it."""
        ocf = self.coordinator.data.ocf
        return ocf.art_mode if ocf else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Go to Art Mode."""
        device = self.coordinator.ocf_device
        if device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="local_control_unavailable"
            )
        await self._async_call(_sent(device.art_mode_on()))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Leave Art Mode (power key); nothing to do when not in it."""
        if self.is_on:
            await self._async_call(self.coordinator.tv.toggle_art_mode())


async def _sent(command: Any) -> None:
    await command
