"""Base entity: one device per TV, actions wrapped into HA errors."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from aiosamstream import SamstreamAuthError, SamstreamError
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SamstreamCoordinator

_T = TypeVar("_T")


class SamstreamEntity(CoordinatorEntity[SamstreamCoordinator]):
    """Entity attached to the TV device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SamstreamCoordinator, key: str) -> None:
        """Name the entity `key` within the TV device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})

    async def _async_call(self, action: Awaitable[_T]) -> _T:
        """Run a TV action (returning its result); a revoked token starts reauth."""
        try:
            return await action
        except SamstreamAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except SamstreamError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
