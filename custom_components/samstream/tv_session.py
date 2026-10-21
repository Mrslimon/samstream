"""Commands for the TV app, pulled by the app from Home Assistant.

Samsung TVs ignore deep links (launch with data) for sideloaded apps, so HA
stores the command here and opens the app with a plain REST launch. The app asks
`GET /api/samstream/tv/{secret}/session?since=<seq>` when it starts and every
couple of seconds while it is on screen.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .const import CONF_TV_SECRET, DOMAIN
from .tv_settings import tv_settings

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_SESSIONS = f"{DOMAIN}_sessions"
# A play command still counts when the app starts this long after it was given
# (the TV may need to wake up first); later ones are history, not a request.
COMMAND_TTL = 120.0
_CORS = {"Access-Control-Allow-Origin": "*"}


@dataclass
class TvSession:
    """Latest command for one TV, numbered so the app applies each once."""

    seq: int = 0
    command: dict[str, Any] | None = None
    issued: float = field(default=0.0)


def _session(hass: HomeAssistant, entry_id: str) -> TvSession:
    sessions: dict[str, TvSession] = hass.data.setdefault(_SESSIONS, {})
    return sessions.setdefault(entry_id, TvSession())


def set_command(
    hass: HomeAssistant, entry: SamstreamConfigEntry, command: dict[str, Any]
) -> int:
    """Queue `command` (`{"action": "play", ...}` or `{"action": "stop"}`)."""
    session = _session(hass, entry.entry_id)
    session.seq += 1
    session.command = command
    session.issued = time.monotonic()
    return session.seq


def session_answer(
    hass: HomeAssistant, entry: SamstreamConfigEntry, since: int
) -> dict[str, Any]:
    """Return settings plus the command the app has not applied yet (if fresh)."""
    session = _session(hass, entry.entry_id)
    fresh = time.monotonic() - session.issued <= COMMAND_TTL
    command = session.command if session.seq > since and fresh else None
    return {"settings": tv_settings(entry), "seq": session.seq, "command": command}


class SamstreamTvSessionView(HomeAssistantView):
    """GET /api/samstream/tv/{secret}/session, authorized by the TV secret."""

    url = "/api/samstream/tv/{secret}/session"
    name = "api:samstream:tv_session"
    # The TV app has no HA token; its per-TV secret (from the package) is the key.
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.Response:
        """Return settings and any newer command for the TV owning `secret`."""
        hass = request.app[KEY_HASS]
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            since = 0
        for entry in hass.config_entries.async_entries(DOMAIN):
            known = entry.data.get(CONF_TV_SECRET)
            if known and secrets.compare_digest(str(known), secret):
                return self.json(session_answer(hass, entry, since), headers=_CORS)
        return self.json_message("Unknown TV", HTTPStatus.NOT_FOUND, headers=_CORS)
