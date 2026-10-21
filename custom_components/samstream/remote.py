"""Remote entity: send any Samsung key, e.g. `KEY_HOME` or just `home`."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_HOLD_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.components.remote import (
    DOMAIN as REMOTE_DOMAIN,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import DOMAIN, REMOTE_HIDDEN
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 1


def normalize_key(command: str) -> str:
    """`home` / `key_home` / `KEY_HOME` all become `KEY_HOME`."""
    key = command.strip().upper()
    return key if key.startswith("KEY_") else f"KEY_{key}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the TV remote."""
    remote = SamstreamRemote(entry.runtime_data.coordinator)
    async_add_entities([remote])
    _hide_once(hass, entry, remote)


@callback
def _hide_once(
    hass: HomeAssistant, entry: SamstreamConfigEntry, remote: SamstreamRemote
) -> None:
    """Hide a remote registered before it was hidden by default; only once."""
    if entry.data.get(REMOTE_HIDDEN):
        return
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        REMOTE_DOMAIN, DOMAIN, remote.unique_id or ""
    )
    registered = registry.async_get(entity_id) if entity_id else None
    if registered is not None and registered.hidden_by is None:
        registry.async_update_entity(
            registered.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION
        )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, REMOTE_HIDDEN: True}
    )


class SamstreamRemote(SamstreamEntity, RemoteEntity):
    """Sends remote keys over the TV's control channel."""

    _attr_translation_key = "remote"
    # Its on/off is the TV's power again; the media player shows that. The
    # remote stays for key presses (remote.send_command, the card).
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the remote for the coordinator's TV."""
        super().__init__(coordinator, "remote")

    @property
    def is_on(self) -> bool:
        """Follows the TV power state."""
        return self.coordinator.data.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the TV."""
        coordinator = self.coordinator
        await self._async_call(
            coordinator.tv.power_on(
                coordinator.config_entry.data.get(CONF_MAC), coordinator.wol_target
            )
        )
        await coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Standby."""
        await self._async_call(self.coordinator.tv.power_off())
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Press keys in order, `num_repeats` times."""
        await self._async_call(
            self.coordinator.tv.send_keys(
                [normalize_key(key) for key in command],
                repeats=kwargs.get(ATTR_NUM_REPEATS, 1),
                delay=kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS),
                hold=kwargs.get(ATTR_HOLD_SECS, 0),
            )
        )
