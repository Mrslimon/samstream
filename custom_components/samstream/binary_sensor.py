"""Developer Mode and the Samstream TV app: what installing the player needs."""

from __future__ import annotations

from collections.abc import Callable

from aiosamstream import SAMSTREAM_APP_ID
from aiosamstream.ocf import OcfTvState

# Moved out of the package root in 2026.10; still re-exported there.
from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined,unused-ignore]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import CONF_OCF
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Developer Mode and Samstream app sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = [
        DeveloperModeSensor(coordinator),
        SamstreamAppSensor(coordinator),
    ]
    if entry.options.get(CONF_OCF):
        entities += [
            LocalControlSensor(coordinator),
            OcfBinarySensor(
                coordinator,
                "tv_camera",
                lambda s: s.camera_connected,
                BinarySensorDeviceClass.CONNECTIVITY,
            ),
            OcfBinarySensor(coordinator, "energy_saving", lambda s: s.energy_saving),
            *(
                OcfBinarySensor(
                    coordinator,
                    key,
                    _accessibility(menu),
                    category=None,
                )
                for key, menu in ACCESSIBILITY
            ),
            OcfBinarySensor(
                coordinator,
                "motion",
                _motion,
                BinarySensorDeviceClass.MOTION,
                category=None,
            ),
        ]
    async_add_entities(entities)


# Accessibility settings the TV reports (entity key, the TV's menu id).
ACCESSIBILITY = (
    ("voice_guide", "voiceguide_on"),
    ("high_contrast", "highcontrast"),
    ("color_inversion", "color-inversion"),
    ("grayscale", "grayscale"),
)


def _accessibility(menu: str) -> Callable[[OcfTvState], bool | None]:
    """Read one accessibility setting by the TV's menu id."""
    return lambda state: state.accessibility_on(menu)


def _motion(state: OcfTvState) -> bool | None:
    """Motion the TV reported; clear while its motion detection is on and quiet."""
    if state.motion is not None:
        return state.motion
    return False if state.motion_sensor_enabled else None


class DeveloperModeSensor(SamstreamEntity, BinarySensorEntity):
    """On when the TV accepts sideloading from the developer host."""

    _attr_translation_key = "developer_mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "developer_mode")

    @property
    def available(self) -> bool:
        """Only known after the TV has answered once."""
        return super().available and self.coordinator.data.info is not None

    @property
    def is_on(self) -> bool | None:
        """Developer Mode flag from the TV's REST API."""
        info = self.coordinator.data.info
        return None if info is None else info.developer_mode


class SamstreamAppSensor(SamstreamEntity, BinarySensorEntity):
    """On when the Samstream player is installed on the TV."""

    _attr_translation_key = "samstream_app"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "samstream_app")

    @property
    def available(self) -> bool:
        """Known once the TV has been on and its apps were scanned."""
        return super().available and self.coordinator.apps_scanned

    @property
    def is_on(self) -> bool:
        """Installed according to the last app scan."""
        return SAMSTREAM_APP_ID in self.coordinator.apps

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Installed version, compared with the bundled one in milestone 7b."""
        return {"version": self.coordinator.app_versions.get(SAMSTREAM_APP_ID)}


class LocalControlSensor(SamstreamEntity, BinarySensorEntity):
    """On while the TV reports to Home Assistant's local cloud (local control)."""

    _attr_translation_key = "local_control"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the sensor for the coordinator's TV."""
        super().__init__(coordinator, "local_control")

    @property
    def available(self) -> bool:
        """Always: a TV that never dialled in is simply not connected."""
        return True

    @property
    def is_on(self) -> bool:
        """The TV reported within the last minute (it re-dials every few s)."""
        return self.coordinator.ocf_state() is not None


class OcfBinarySensor(SamstreamEntity, BinarySensorEntity):
    """An on/off the TV reports over local control."""

    _attr_entity_category: EntityCategory | None

    def __init__(
        self,
        coordinator: SamstreamCoordinator,
        key: str,
        value: Callable[[OcfTvState], bool | None],
        device_class: BinarySensorDeviceClass | None = None,
        *,
        category: EntityCategory | None = EntityCategory.DIAGNOSTIC,
    ) -> None:
        """Create the sensor `key` for the coordinator's TV."""
        super().__init__(coordinator, key)
        self._attr_entity_category = category
        self._attr_translation_key = key
        self._attr_device_class = device_class
        self._value = value

    @property
    def available(self) -> bool:
        """While the TV reports this value."""
        ocf = self.coordinator.data.ocf
        return super().available and ocf is not None and self._value(ocf) is not None

    @property
    def is_on(self) -> bool | None:
        """The reported value."""
        ocf = self.coordinator.data.ocf
        return self._value(ocf) if ocf else None
