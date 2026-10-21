"""Poll the TV's power state, volume and the app on screen."""

from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiosamstream import (
    KNOWN_APPS,
    DeviceInfo,
    SamstreamConnectionError,
    SamstreamError,
    SamsungTV,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    APP_SCAN_INTERVAL,
    CONF_EXTRA_APPS,
    CONF_WOL_TARGET,
    DOMAIN,
    SCAN_INTERVAL,
)

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SamstreamState:
    """What the entities show."""

    is_on: bool
    # 0-100 from UPnP; None while off or when the TV does not answer UPnP.
    volume: int | None = None
    muted: bool | None = None
    # Last device info the TV reported; kept while it is off.
    info: DeviceInfo | None = None
    # App in the foreground; None for home, live TV, HDMI or an unknown app.
    app_id: str | None = None
    app_name: str | None = None


def parse_app_ids(text: str) -> list[str]:
    """Split the "extra app IDs" option (comma, space or newline separated)."""
    return [part for part in text.replace(",", " ").split() if part]


def default_wol_target(host: str) -> str:
    """Return the TV's subnet broadcast address (assumes /24).

    A global broadcast never leaves a Docker bridge network; a directed one is
    routed out to the LAN.
    """
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return "255.255.255.255"
    return str(ipaddress.IPv4Network(f"{address}/24", strict=False).broadcast_address)


class SamstreamCoordinator(DataUpdateCoordinator[SamstreamState]):
    """An unreachable TV is simply off, so updates never fail."""

    config_entry: SamstreamConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: SamstreamConfigEntry, tv: SamsungTV
    ) -> None:
        """Poll `tv` for `entry`."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.tv = tv
        # Installed apps (id -> name the TV reports), refreshed while the TV is on.
        self.apps: dict[str, str] = {}
        self.app_versions: dict[str, str | None] = {}
        # True while the Samstream app is being installed (one install at a time).
        self.installing = False
        self._apps_scanned_at: float | None = None

    @property
    def wol_target(self) -> str:
        """Where Wake-on-LAN packets go (options, else the TV's subnet broadcast)."""
        entry = self.config_entry
        return entry.options.get(CONF_WOL_TARGET) or default_wol_target(
            entry.data[CONF_HOST]
        )

    async def _async_update_data(self) -> SamstreamState:
        previous = self.data
        try:
            info = await self.tv.device_info()
        except SamstreamConnectionError:
            if previous is not None and previous.is_on:
                _LOGGER.info("%s is off or unreachable", self.config_entry.title)
                await self.tv.close()
            return SamstreamState(is_on=False, info=previous.info if previous else None)

        is_on = info.power_on is not False
        if not is_on:
            if previous is not None and previous.is_on:
                await self.tv.close()
            return SamstreamState(is_on=False, info=info)

        volume: int | None = None
        muted: bool | None = None
        try:
            volume = await self.tv.rendering.get_volume()
            muted = await self.tv.rendering.get_mute()
        except SamstreamError as err:
            _LOGGER.debug("No UPnP volume from %s: %s", self.config_entry.title, err)

        await self._async_scan_apps()
        app_id = app_name = None
        try:
            foreground = await self.tv.foreground_app(self.apps)
        except SamstreamError as err:
            _LOGGER.debug("No app status from %s: %s", self.config_entry.title, err)
        else:
            if foreground is not None:
                app_id, app_name = foreground.app_id, foreground.name
        return SamstreamState(
            is_on=True,
            volume=volume,
            muted=muted,
            info=info,
            app_id=app_id,
            app_name=app_name,
        )

    async def _async_scan_apps(self) -> None:
        """Find installed apps: on first contact, then every APP_SCAN_INTERVAL.

        The TV cannot list its apps, so every known ID is asked about.
        """
        now = time.monotonic()
        if (
            self._apps_scanned_at is not None
            and now - self._apps_scanned_at < APP_SCAN_INTERVAL.total_seconds()
        ):
            return
        extra = parse_app_ids(self.config_entry.options.get(CONF_EXTRA_APPS, ""))
        try:
            installed = await self.tv.installed_apps([*KNOWN_APPS, *extra])
        except SamstreamError as err:
            _LOGGER.debug("App scan on %s failed: %s", self.config_entry.title, err)
            return
        self.apps = {app.app_id: app.name for app in installed}
        self.app_versions = {app.app_id: app.version for app in installed}
        self._apps_scanned_at = now

    @property
    def apps_scanned(self) -> bool:
        """True once the installed apps have been read from the TV at least once."""
        return self._apps_scanned_at is not None

    async def async_rescan_apps(self) -> None:
        """Scan apps on the next refresh (e.g. right after installing one)."""
        self._apps_scanned_at = None
        await self.async_refresh()
