"""Poll the TV's power state and volume."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiosamstream import DeviceInfo, SamstreamConnectionError, SamstreamError, SamsungTV
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_WOL_TARGET, DOMAIN, SCAN_INTERVAL

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
        return SamstreamState(is_on=True, volume=volume, muted=muted, info=info)
