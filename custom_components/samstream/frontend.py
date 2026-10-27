"""The Samstream Lovelace card: served by the integration, loaded automatically.

`custom:samstream-card` needs no dashboard resource: HA adds the script to every
page. The card asks `samstream/apps` for the TV's apps and their logos (kept out
of entity attributes so the list does not fill the recorder).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url

# Moved to http.server in 2026.10; still re-exported from the package.
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined,unused-ignore]
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    websocket_command,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SOURCE_HOME, SOURCE_KEYS
from .logos import async_app_logos
from .validation import vol

URL_BASE = "/samstream_files"
CARD_FILE = "samstream-card.js"
_FRONTEND = Path(__file__).parent / "frontend"


def _card_version() -> str:
    """Content hash, so browsers fetch the card again after an update."""
    return hashlib.sha256((_FRONTEND / CARD_FILE).read_bytes()).hexdigest()[:12]


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the card, add it to every dashboard, answer its app requests."""
    websocket_api.async_register_command(hass, websocket_apps)
    if not await hass.async_add_executor_job((_FRONTEND / CARD_FILE).is_file):
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(_FRONTEND), cache_headers=False)]
    )
    version = await hass.async_add_executor_job(_card_version)
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILE}?v={version}")


@websocket_command(
    {vol.Required("type"): "samstream/apps", vol.Required("entity_id"): str}
)
@async_response
async def websocket_apps(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Apps on the TV of `entity_id`, with logos; Home first."""
    coordinator = _coordinator(hass, msg["entity_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Not a Samstream TV")
        return
    apps = coordinator.apps
    logos = await async_app_logos(hass, apps)
    coordinator.logos = logos
    connection.send_result(
        msg["id"],
        {
            "home": SOURCE_HOME,
            # Live TV and HDMI inputs: tiles after Home (select_source by name).
            "sources": [name for name in SOURCE_KEYS if name != SOURCE_HOME],
            "current": coordinator.data.app_id,
            "apps": [
                {"id": app_id, "name": name, "logo": logos.get(app_id)}
                for app_id, name in sorted(apps.items(), key=lambda a: a[1].casefold())
            ],
        },
    )


@callback
def _coordinator(hass: HomeAssistant, entity_id: str) -> Any:
    entry_id = (
        entity.config_entry_id
        if (entity := er.async_get(hass).async_get(entity_id))
        else None
    )
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        return None
    return entry.runtime_data.coordinator
