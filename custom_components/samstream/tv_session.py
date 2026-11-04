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
from homeassistant.helpers.dispatcher import async_dispatcher_send
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
# Input names the TV app reports ("TV1", "HDMI2"); anything longer is junk.
_MAX_SOURCE = 16


def signal_playing(entry_id: str) -> str:
    """Dispatcher signal: the TV shows command `seq` (first frame, notice, video)."""
    return f"{DOMAIN}_playing_{entry_id}"


def signal_closed(entry_id: str) -> str:
    """Dispatcher signal: the viewer pressed Back on command `seq`; Samstream closes."""
    return f"{DOMAIN}_closed_{entry_id}"


def signal_source(entry_id: str) -> str:
    """Dispatcher signal: (seq, input) the TV showed under command `seq`."""
    return f"{DOMAIN}_source_{entry_id}"


def signal_ended(entry_id: str) -> str:
    """Dispatcher signal: the video of command `seq` ended on the TV."""
    return f"{DOMAIN}_ended_{entry_id}"


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


def current_command(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, Any] | None:
    """Return the latest command given to this TV, if any."""
    return _session(hass, entry.entry_id).command


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
        since = _int_query(request, "since") or 0
        playing = _int_query(request, "playing")
        ended = _int_query(request, "ended")
        closed = _int_query(request, "closed")
        for entry in hass.config_entries.async_entries(DOMAIN):
            known = entry.data.get(CONF_TV_SECRET)
            if known and secrets.compare_digest(str(known), secret):
                if playing is not None:
                    async_dispatcher_send(hass, signal_playing(entry.entry_id), playing)
                if ended is not None:
                    async_dispatcher_send(hass, signal_ended(entry.entry_id), ended)
                if closed is not None:
                    async_dispatcher_send(hass, signal_closed(entry.entry_id), closed)
                source = request.query.get("source", "")
                if (
                    playing is not None
                    and source.isalnum()
                    and len(source) <= _MAX_SOURCE
                ):
                    async_dispatcher_send(
                        hass, signal_source(entry.entry_id), playing, source
                    )
                return self.json(session_answer(hass, entry, since), headers=_CORS)
        return self.json_message("Unknown TV", HTTPStatus.NOT_FOUND, headers=_CORS)


def _int_query(request: web.Request, name: str) -> int | None:
    try:
        return int(request.query[name])
    except (KeyError, ValueError):
        return None
