"""Update entity for the Samstream TV app: installed version vs. the bundled one.

An integration update (HACS) brings a newer TV app inside it. With the
"automatic updates" option (on by default) it is installed by itself once the
TV is on and Samstream is not on screen; otherwise the entity offers it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiosamstream import SAMSTREAM_APP_ID
from awesomeversion import AwesomeVersion, AwesomeVersionException
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .app_signing import async_load_signing
from .const import CONF_AUTO_UPDATE
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .installer import async_install_package

_LOGGER = logging.getLogger(__name__)
# Without app signing set up, look again this often (not on every poll).
NO_SIGNING_RECHECK_SECONDS = 600

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
    _attr_release_url = "https://github.com/Mrslimon/samstream/releases"

    def __init__(self, coordinator: SamstreamCoordinator, bundled: str | None) -> None:
        """Compare the TV's copy with `bundled` (None when no package ships)."""
        super().__init__(coordinator, "samstream_app_update")
        self._attr_latest_version = bundled
        # Bundled version already tried automatically (once per version and run).
        self._auto_tried: str | None = None
        self._auto_busy = False
        self._recheck_signing_at = 0.0

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

    @callback
    def _handle_coordinator_update(self) -> None:
        """After each poll, install a newer bundled app if allowed and idle."""
        super()._handle_coordinator_update()
        if self._auto_update_due():
            self._auto_busy = True
            self.hass.async_create_task(self._async_auto_update())

    def _auto_update_due(self) -> bool:
        coordinator = self.coordinator
        latest, installed = self.latest_version, self.installed_version
        return bool(
            coordinator.config_entry.options.get(CONF_AUTO_UPDATE, True)
            and not self._auto_busy
            and latest is not None
            and installed is not None  # Updates only; first installs stay manual.
            and latest != self._auto_tried
            and coordinator.data.is_on
            # Samstream on screen: a camera or message is showing, wait.
            and coordinator.data.app_id != SAMSTREAM_APP_ID
            and not coordinator.installing
            and time.monotonic() >= self._recheck_signing_at
            and _newer(latest, installed)
        )

    async def _async_auto_update(self) -> None:
        latest, installed = self.latest_version, self.installed_version
        try:
            if await async_load_signing(self.hass) is None:
                self._recheck_signing_at = time.monotonic() + NO_SIGNING_RECHECK_SECONDS
                return
            self._auto_tried = latest
            _LOGGER.info(
                "Updating the Samstream TV app on %s from %s to %s",
                self.coordinator.config_entry.title,
                installed,
                latest,
            )
            await async_install_package(self.hass, self.coordinator.config_entry, None)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Automatic update of the Samstream TV app to %s failed: %s. "
                "Install it from the update entity",
                latest,
                err,
            )
        finally:
            self._auto_busy = False


def _newer(latest: str, installed: str) -> bool:
    try:
        return AwesomeVersion(latest) > AwesomeVersion(installed)
    except AwesomeVersionException:
        return latest != installed
