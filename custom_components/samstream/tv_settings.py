"""Settings the Samstream TV app pulls from Home Assistant when it starts.

At install HA writes `samstream.json` into the package (its URL and a per-TV
secret). On every start the app asks this view for the current settings, so a
change in HA applies the next time Samstream opens, without reinstalling.
"""

from __future__ import annotations

import io
import json
import secrets
import zipfile
from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_LANGUAGE,
    CONF_THEME,
    CONF_TV_SECRET,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    DOMAIN,
)

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

PACKAGE_SETTINGS_FILE = "samstream.json"
# The app is a file:// page on the TV; let it read the answer.
_CORS = {"Access-Control-Allow-Origin": "*"}


def ensure_tv_secret(hass: HomeAssistant, entry: SamstreamConfigEntry) -> str:
    """Return this TV's secret, creating it on first use."""
    if secret := entry.data.get(CONF_TV_SECRET):
        return str(secret)
    secret = secrets.token_urlsafe(24)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TV_SECRET: secret}
    )
    return secret


def tv_settings(entry: SamstreamConfigEntry) -> dict[str, str]:
    """Return what the TV app applies: UI language and theme."""
    return {
        "language": entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        "theme": entry.options.get(CONF_THEME, DEFAULT_THEME),
    }


def package_settings(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, object]:
    """Build `samstream.json`: HA URL, TV secret, current settings (event loop)."""
    try:
        ha_url = get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        ha_url = ""
    return {
        "ha_url": ha_url,
        "tv_secret": ensure_tv_secret(hass, entry),
        "settings": tv_settings(entry),
    }


def add_package_settings(wgt: bytes, payload: dict[str, object]) -> bytes:
    """Return the package with `samstream.json` added or replaced (blocking)."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(wgt)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            if item.filename != PACKAGE_SETTINGS_FILE:
                target.writestr(item, source.read(item))
        target.writestr(PACKAGE_SETTINGS_FILE, json.dumps(payload))
    return out.getvalue()


class SamstreamTvSettingsView(HomeAssistantView):
    """GET /api/samstream/tv/{secret}/settings, authorized by the TV secret."""

    url = "/api/samstream/tv/{secret}/settings"
    name = "api:samstream:tv_settings"
    # The TV app has no HA token; the per-TV secret from its package is the credential.
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.Response:
        """Return the settings for the TV that owns this secret."""
        hass = request.app[KEY_HASS]
        for entry in hass.config_entries.async_entries(DOMAIN):
            known = entry.data.get(CONF_TV_SECRET)
            if known and secrets.compare_digest(str(known), secret):
                return self.json(tv_settings(entry), headers=_CORS)
        return self.json_message("Unknown TV", HTTPStatus.NOT_FOUND, headers=_CORS)
