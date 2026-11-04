"""Hand-off point between the sign-in helper and a waiting options flow.

Samsung's sign-in only redirects to localhost:4794, so `npx samstream-signin` runs
next to the user's browser. It asks this view for the sign-in URL and posts the
callback back, identified by a short one-time code shown in the options flow.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus

from aiohttp import web
from aiosamstream.samsung_cert import new_state, sign_in_url
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN

SIGN_IN_TIMEOUT = 600.0
_DATA_KEY = f"{DOMAIN}_signins"


@dataclass
class PendingSignIn:
    """One sign-in the options flow is waiting for."""

    code: str
    state: str = field(default_factory=new_state)
    callback: asyncio.Future[str] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    expires: float = field(default_factory=lambda: time.monotonic() + SIGN_IN_TIMEOUT)


def _pending(hass: HomeAssistant) -> dict[str, PendingSignIn]:
    signins: dict[str, PendingSignIn] = hass.data.setdefault(_DATA_KEY, {})
    now = time.monotonic()
    for code in [code for code, item in signins.items() if item.expires < now]:
        signins.pop(code).callback.cancel()
    return signins


def start_sign_in(hass: HomeAssistant) -> PendingSignIn:
    """Register a new sign-in with a fresh one-time code."""
    pending = PendingSignIn(code=secrets.token_hex(4))
    _pending(hass)[pending.code] = pending
    return pending


def cancel_sign_in(hass: HomeAssistant, pending: PendingSignIn) -> None:
    """Forget a sign-in (finished, failed or abandoned)."""
    _pending(hass).pop(pending.code, None)
    if not pending.callback.done():
        pending.callback.cancel()


def helper_command(hass: HomeAssistant, code: str) -> str:
    """Return the command the user runs on a computer with a browser."""
    try:
        base = get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        base = "http://<home-assistant>:8123"
    return f"npx samstream-signin {base} {code}"


class SamstreamSignInView(HomeAssistantView):
    """GET the sign-in URL, POST the callback; authorized by the one-time code."""

    url = "/api/samstream/signin/{code}"
    name = "api:samstream:signin"
    # The helper has no HA token; the short-lived one-time code is the credential.
    requires_auth = False

    async def get(self, request: web.Request, code: str) -> web.Response:
        """Return the Samsung sign-in URL for this code."""
        pending = _pending(request.app[KEY_HASS]).get(code)
        if pending is None:
            return self.json_message("Unknown or expired code", HTTPStatus.NOT_FOUND)
        return self.json({"sign_in_url": sign_in_url(pending.state)})

    async def post(self, request: web.Request, code: str) -> web.Response:
        """Accept the callback body the helper caught on localhost."""
        hass = request.app[KEY_HASS]
        pending = _pending(hass).pop(code, None)
        if pending is None or pending.callback.done():
            return self.json_message("Unknown or expired code", HTTPStatus.NOT_FOUND)
        try:
            data = await request.json()
            body = data["body"]
        except (ValueError, KeyError, TypeError):
            return self.json_message('Expected {"body": ...}', HTTPStatus.BAD_REQUEST)
        if not isinstance(body, str):
            return self.json_message('Expected {"body": ...}', HTTPStatus.BAD_REQUEST)
        pending.callback.set_result(body)
        return self.json({"ok": True})
