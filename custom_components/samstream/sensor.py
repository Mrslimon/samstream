"""Current app, and the developer host (the machine allowed to install apps)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiosamstream.ocf import OcfTvState
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import SamstreamConfigEntry
from .const import ATTR_APP_ID, CONF_OCF, SCREEN_HOME, SCREEN_OTHER
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
    entities: list[SensorEntity] = [
        CurrentAppSensor(coordinator),
        DeveloperHostSensor(coordinator),
    ]
    if entry.options.get(CONF_OCF):
        entities += [OcfSensor(coordinator, d) for d in OCF_SENSORS]
    async_add_entities(entities)


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


def _channel(ocf: OcfTvState) -> str | None:
    if ocf.content_input == "webapp":
        return None
    return ocf.channel_name or ocf.channel_number


@dataclass(frozen=True, kw_only=True)
class OcfSensorDescription(SensorEntityDescription):
    """A sensor fed by what the TV reports over local control."""

    value_fn: Callable[[OcfTvState], StateType]
    attrs_fn: Callable[[OcfTvState], dict[str, Any]] = lambda _: {}


OCF_SENSORS: tuple[OcfSensorDescription, ...] = (
    OcfSensorDescription(
        key="channel",
        translation_key="channel",
        value_fn=_channel,
        attrs_fn=lambda s: {"number": s.channel_number},
    ),
    OcfSensorDescription(
        key="ambient_light",
        translation_key="ambient_light",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.illuminance,
        attrs_fn=lambda s: {"level": s.brightness_level},
    ),
    OcfSensorDescription(
        key="sound_detected",
        translation_key="sound_detected",
        value_fn=lambda s: s.sound_detected,
        attrs_fn=lambda s: {"sound_types": list(s.sound_types)},
    ),
    OcfSensorDescription(
        key="remote_battery",
        translation_key="remote_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.remote_battery,
    ),
    OcfSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.wifi_dbm,
        attrs_fn=lambda s: {
            "frequency": s.wifi_frequency,
            "channel": s.wifi_channel,
            "protocol": s.wifi_protocol,
            "disconnects": s.wifi_disconnects,
        },
    ),
)


class OcfSensor(SamstreamEntity, SensorEntity):
    """A value the TV reports over local control; unavailable until it does."""

    entity_description: OcfSensorDescription

    def __init__(
        self, coordinator: SamstreamCoordinator, description: OcfSensorDescription
    ) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """While the TV reports over local control (a channel can be empty)."""
        ocf = self.coordinator.data.ocf
        if not super().available or ocf is None:
            return False
        key = self.entity_description.key
        return key == "channel" or self.entity_description.value_fn(ocf) is not None

    @property
    def native_value(self) -> StateType:
        """The reported value."""
        ocf = self.coordinator.data.ocf
        return self.entity_description.value_fn(ocf) if ocf else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details that come with the value."""
        ocf = self.coordinator.data.ocf
        return self.entity_description.attrs_fn(ocf) if ocf else {}
