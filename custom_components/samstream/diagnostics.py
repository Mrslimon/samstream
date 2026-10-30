"""Diagnostics download: what helps a bug report, with secrets removed."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from aiosamstream import SAMSTREAM_APP_ID, OcfError
from aiosamstream.ocf import CloudDevice
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

from . import SamstreamConfigEntry
from .app_signing import async_load_signing
from .const import (
    CONF_AUTHOR_P12,
    CONF_DISTRIBUTOR_P12,
    CONF_OCF_OWNER_PSK,
    CONF_OCF_TOKEN,
    CONF_TOKEN,
    CONF_TV_SECRET,
)
from .ocf import async_get_service
from .tv_session import current_command

TO_REDACT = {
    CONF_TOKEN,
    CONF_TV_SECRET,
    CONF_MAC,
    CONF_AUTHOR_P12,
    CONF_DISTRIBUTOR_P12,
    CONF_OCF_TOKEN,
    CONF_OCF_OWNER_PSK,
    "mac",
    "password",
    "email",
    "url",
    "sound",
    # Raw OCF resources (read_all): network and device identifiers.
    "ssid",
    "bssid",
    "ap_ssid",
    "ap_bssid",
    "ip",
    "ipaddress",
    "serialNumber",
    "x.com.samsung.devicelog.connectioninfo",
    # The cloud token the TV holds (/CoapCloudConfResURI) and its MAC addresses.
    "at",
    "accesstoken",
    "refreshtoken",
    "x.com.samsung.refreshtoken",
    "x.com.samsung.tv.btmac",
    "x.com.samsung.tv.blemac",
    "x.com.samsung.tv.wifimac",
    "x.com.samsung.tv.ethmac",
    "x.com.samsung.tv.p2pmac",
    "x.com.samsung.mde.addressinfo",
    "x.com.samsung.rsd",
    # Setup details (/DevConfResURI): the Samsung account, serial, setup phone.
    "x.com.samsung.account",
    "x.com.samsung.ssolist",
    "x.com.samsung.plainserial",
    "x.com.samsung.rmd",
}
_READ_ALL_TIMEOUT = 240


def _jsonable(value: Any) -> Any:
    """CBOR bodies may hold byte strings; show those as a short hex preview."""
    if isinstance(value, bytes):
        return f"<{len(value)} bytes: {value[:16].hex()}…>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


async def _ocf_resources(device: CloudDevice | None) -> Any:
    """Every resource the connected TV lists, as it answers right now."""
    if device is None or not device.connected:
        return None
    try:
        async with asyncio.timeout(_READ_ALL_TIMEOUT):
            return _jsonable(await device.read_all())
    except (OcfError, TimeoutError) as err:
        return {"error": str(err) or "timed out"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, Any]:
    """Return entry, TV, app and signing state for a bug report."""
    data = entry.runtime_data
    coordinator = data.coordinator
    state = coordinator.data
    signing = await async_load_signing(hass)
    command = current_command(hass, entry)
    service = async_get_service(hass)
    device = coordinator.ocf_device
    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "tv": {
                "is_on": state.is_on,
                "volume": state.volume,
                "muted": state.muted,
                "app_id": state.app_id,
                "app_name": state.app_name,
                "device_info": asdict(state.info) if state.info else None,
            },
            "apps": {
                "source": coordinator.app_source,
                "count": len(coordinator.apps),
                "installed": coordinator.apps,
                "versions": coordinator.app_versions,
                "logos": sorted(coordinator.logos),
            },
            "samstream_app": {
                "bundled_version": data.bundled_version,
                "installed_version": coordinator.app_versions.get(SAMSTREAM_APP_ID),
                "installing": coordinator.installing,
                # The last command for the TV app (stream URLs redacted).
                "last_command": command,
            },
            # Local control: never the CA key or the TV's token (redacted above).
            "local_control": {
                "listening": service.cloud is not None,
                "problem": service.problem,
                "address": service.cis(),
                "tv_connected": device.connected if device else None,
                "state": asdict(state.ocf) if state.ocf else None,
                "resources": await _ocf_resources(device),
            },
            "signing": (
                {
                    "source": signing.source,
                    "expires": signing.expires.isoformat(),
                    "duids": len(signing.duids),
                }
                if signing
                else None
            ),
        },
        TO_REDACT,
    )
