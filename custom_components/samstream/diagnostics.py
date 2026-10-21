"""Diagnostics download: what helps a bug report, with secrets removed."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

from . import SamstreamConfigEntry
from .app_signing import async_load_signing
from .const import CONF_AUTHOR_P12, CONF_DISTRIBUTOR_P12, CONF_TOKEN, CONF_TV_SECRET
from .tv_session import current_command

TO_REDACT = {
    CONF_TOKEN,
    CONF_TV_SECRET,
    CONF_MAC,
    CONF_AUTHOR_P12,
    CONF_DISTRIBUTOR_P12,
    "mac",
    "password",
    "email",
    "url",
    "sound",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, Any]:
    """Return entry, TV, app and signing state for a bug report."""
    data = entry.runtime_data
    coordinator = data.coordinator
    state = coordinator.data
    signing = await async_load_signing(hass)
    command = current_command(hass, entry)
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
