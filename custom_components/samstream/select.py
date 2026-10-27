"""Input, picture mode and sound mode, by the names the TV itself reports.

Only with local control (OCF) on: the TV lists its real inputs and modes and
switches by id, which the remote-key inputs of the media player cannot do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiosamstream.ocf import CloudDevice, OcfTvState
from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import CONF_OCF, DOMAIN
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 1

type Choices = tuple[tuple[str, str], ...]
type Reader = Callable[[OcfTvState], tuple[str | None, Choices]]
type Writer = Callable[[CloudDevice, str], Awaitable[int]]


def _inputs(state: OcfTvState) -> tuple[str | None, Choices]:
    return state.input_source, state.input_sources


def _picture(state: OcfTvState) -> tuple[str | None, Choices]:
    return state.picture_mode, state.picture_modes


def _sound(state: OcfTvState) -> tuple[str | None, Choices]:
    return state.sound_mode, state.sound_modes


def _sound_output(state: OcfTvState) -> tuple[str | None, Choices]:
    return state.sound_output, state.sound_outputs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects when local control is on for this TV."""
    if not entry.options.get(CONF_OCF):
        return
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            OcfSelect(coordinator, "input_source", _inputs, CloudDevice.select_input),
            OcfSelect(
                coordinator,
                "picture_mode",
                _picture,
                CloudDevice.set_picture_mode,
                EntityCategory.CONFIG,
            ),
            OcfSelect(
                coordinator,
                "sound_mode",
                _sound,
                CloudDevice.set_sound_mode,
                EntityCategory.CONFIG,
            ),
            OcfSelect(
                coordinator,
                "sound_output",
                _sound_output,
                CloudDevice.set_sound_output,
                EntityCategory.CONFIG,
            ),
        ]
    )


class OcfSelect(SamstreamEntity, SelectEntity):
    """One TV setting whose choices (id, name) the TV reports over OCF."""

    def __init__(
        self,
        coordinator: SamstreamCoordinator,
        key: str,
        read: Reader,
        write: Writer,
        category: EntityCategory | None = None,
    ) -> None:
        """Create the select `key` for the coordinator's TV."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_entity_category = category
        self._read = read
        self._write = write

    def _state(self) -> tuple[str | None, Choices]:
        ocf = self.coordinator.data.ocf
        return self._read(ocf) if ocf is not None else (None, ())

    @property
    def available(self) -> bool:
        """While the TV reports its choices over local control."""
        return super().available and bool(self._state()[1])

    @property
    def options(self) -> list[str]:
        """The TV's own names for the choices."""
        return [name for _, name in self._state()[1]]

    @property
    def current_option(self) -> str | None:
        """Name of the current choice."""
        current, choices = self._state()
        return next((name for ident, name in choices if ident == current), None)

    async def async_select_option(self, option: str) -> None:
        """Switch the TV to the choice with this name."""
        _, choices = self._state()
        ident = next((ident for ident, name in choices if name == option), None)
        device = self.coordinator.ocf_device
        if ident is None or device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="local_control_unavailable",
            )
        await self._async_call(self._send(device, ident))

    async def _send(self, device: CloudDevice, ident: str) -> None:
        await self._write(device, ident)
