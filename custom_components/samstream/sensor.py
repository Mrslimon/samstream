"""Current app, and the developer host (the machine allowed to install apps)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import ATTR_APP_ID, SCREEN_HOME, SCREEN_OTHER
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the current app and developer host sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [CurrentAppSensor(coordinator), DeveloperHostSensor(coordinator)]
    )


class CurrentAppSensor(SamstreamEntity, SensorEntity):
    """Name of the app on screen, for automations ("is Netflix playing?").

    With no app in front it reports `home` when the TV listed all its apps (so it
    must be the home screen, live TV or an input) and `other` when only the
    catalog is known (could also be an app the catalog lacks).
    """

    _attr_translation_key = "current_app"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "current_app")

    @property
    def options(self) -> list[str]:
        """Installed app names plus the two translated states."""
        return [*sorted(set(self.coordinator.apps.values())), SCREEN_HOME, SCREEN_OTHER]

    @property
    def native_value(self) -> str | None:
        """App name, `home`, `other`; unknown while the TV is off."""
        data = self.coordinator.data
        if not data.is_on:
            return None
        if data.app_name:
            return data.app_name
        return SCREEN_HOME if self.coordinator.app_source == "tv" else SCREEN_OTHER

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """The Tizen app ID, for `samstream.launch_app` / `close_app`."""
        return {ATTR_APP_ID: self.coordinator.data.app_id}


class DeveloperHostSensor(SamstreamEntity, SensorEntity):
    """IP address set in the TV's Developer Mode screen."""

    _attr_translation_key = "developer_host"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Only needed when installs fail; the Developer Mode repair issue says so too.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "developer_host")

    @property
    def available(self) -> bool:
        """Only known after the TV has answered once."""
        return super().available and self.coordinator.data.info is not None

    @property
    def native_value(self) -> str | None:
        """Developer host IP, None when Developer Mode is off."""
        info = self.coordinator.data.info
        return info.developer_ip if info and info.developer_mode else None
