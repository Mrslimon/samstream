"""Update entity for the Samstream TV app: installed version vs. the bundled one."""

from __future__ import annotations

from typing import Any

from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Samstream app update entity."""
    data = entry.runtime_data
    async_add_entities([SamstreamAppUpdate(data.coordinator, data.bundled_version)])


class SamstreamAppUpdate(SamstreamEntity, UpdateEntity):
    """The integration ships a newer TV app than the one on the TV."""

    _attr_translation_key = "samstream_app"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_release_url = "https://github.com/islamahmady/samstream/releases"

    def __init__(self, coordinator: SamstreamCoordinator, bundled: str | None) -> None:
        """Compare the TV's copy with `bundled` (None when no package ships)."""
        super().__init__(coordinator, "samstream_app_update")
        self._attr_latest_version = bundled

    @property
    def available(self) -> bool:
        """Known once the TV's apps were read and a bundled package exists."""
        return (
            super().available
            and self.coordinator.apps_scanned
            and self.latest_version is not None
            and SAMSTREAM_APP_ID in self.coordinator.apps
        )

    @property
    def installed_version(self) -> str | None:
        """Version the TV reports for Samstream."""
        return self.coordinator.app_versions.get(SAMSTREAM_APP_ID)

    @property
    def in_progress(self) -> bool:
        """True while the app is being installed (also from the install button)."""
        return self.coordinator.installing

    async def async_install(
        self,
        version: str | None,
        backup: bool,  # noqa: FBT001
        **kwargs: Any,
    ) -> None:
        """Sign the bundled app with HA's certificates and install it."""
        await async_install_package(self.hass, self.coordinator.config_entry, None)
