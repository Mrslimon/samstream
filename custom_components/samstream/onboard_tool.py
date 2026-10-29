"""The LAN onboarding helper, offered as a download when HA cannot reach the TV.

When Home Assistant cannot talk to the TV's local SmartThings service itself,
the user onboards the TV from a computer on its network instead. HA builds that
tool on the fly: a zip app (`samstream-onboard.pyz`) holding only the onboarding
modules of aiosamstream, with the TV's address and the cloud bundle baked in, so
the user just runs it. A Windows launcher next to it installs `cryptography`
(the tool's one dependency) and runs it.

The bundle carries the TV's access token, so the downloads need a logged-in
user: the links the setup screen shows are signed and expire.
"""

from __future__ import annotations

import io
import secrets
import time
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path

import aiosamstream
from aiohttp import web
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .const import DOMAIN

TOOL_FILE = "samstream-onboard.pyz"
LAUNCHER_FILE = "samstream-onboard.cmd"
LINK_LIFETIME = timedelta(hours=1)
DATA_OFFERS = f"{DOMAIN}_onboard_offers"

# The onboarding subset of the library: stdlib + cryptography only.
_MODULES = (
    "exceptions.py",
    "ocf/cbor.py",
    "ocf/coap_tcp.py",
    "ocf/dtls.py",
    "ocf/onboard.py",
    "ocf/onboard_cli.py",
)

_MAIN = '''"""Samstream: onboard the TV at {tv} for Home Assistant local control."""

import sys

if sys.version_info < (3, 11):
    sys.exit("samstream-onboard needs Python 3.11 or newer.")
try:
    import cryptography  # noqa: F401
except ImportError:
    sys.exit(
        "samstream-onboard needs the cryptography package:\\n"
        "    python -m pip install cryptography"
    )

from aiosamstream.ocf.onboard_cli import main

raise SystemExit(main(tv={tv!r}, bundle={bundle!r}))
'''

_LAUNCHER = "\r\n".join(
    [
        "@echo off",
        "rem Samstream: onboard the TV for Home Assistant local control.",
        "rem Needs Python 3.11 or newer (https://www.python.org/downloads/).",
        'cd /d "%~dp0"',
        "set PY=python",
        "where py >nul 2>nul && set PY=py -3",
        (
            '%PY% -c "import cryptography" 2>nul'
            " || %PY% -m pip install --user cryptography"
        ),
        f"%PY% {TOOL_FILE} %*",
        "pause",
        "",
    ]
)


@dataclass(frozen=True, slots=True)
class _Offer:
    tv: str
    bundle: str
    expires: float


def build_tool(tv: str, bundle: str) -> bytes:
    """Return the zip app: the onboarding modules plus a `__main__` with `tv`."""
    root = Path(aiosamstream.__file__).parent
    buffer = io.BytesIO()
    buffer.write(b"#!/usr/bin/env python3\n")  # runnable as ./samstream-onboard.pyz
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # Stub packages: the real __init__ files import the whole library.
        archive.writestr("aiosamstream/__init__.py", "")
        archive.writestr("aiosamstream/ocf/__init__.py", "")
        for name in _MODULES:
            archive.write(root / name, f"aiosamstream/{name}")
        archive.writestr("__main__.py", _MAIN.format(tv=tv, bundle=bundle))
    return buffer.getvalue()


def async_offer(hass: HomeAssistant, tv: str, bundle: str) -> dict[str, str]:
    """Return signed, expiring download links for this TV and bundle."""
    offers: dict[str, _Offer] = hass.data.setdefault(DATA_OFFERS, {})
    now = time.monotonic()
    for stale in [key for key, offer in offers.items() if offer.expires < now]:
        del offers[stale]
    key = secrets.token_urlsafe(16)
    offers[key] = _Offer(tv, bundle, now + LINK_LIFETIME.total_seconds())
    return {
        "tool_url": _sign(hass, f"/api/samstream/onboard/{key}/{TOOL_FILE}"),
        "launcher_url": _sign(hass, f"/api/samstream/onboard/{key}/{LAUNCHER_FILE}"),
    }


def _sign(hass: HomeAssistant, path: str) -> str:
    try:
        return async_sign_path(hass, path, LINK_LIFETIME)
    except KeyError:  # auth not set up (tests): the link then needs a login
        return path


class SamstreamOnboardToolView(HomeAssistantView):
    """Serve the LAN onboarding tool for one offer (signed link, logged-in user)."""

    url = "/api/samstream/onboard/{key}/{filename}"
    name = "api:samstream:onboard"
    requires_auth = True

    async def get(self, request: web.Request, key: str, filename: str) -> web.Response:
        """Return the zip app or the Windows launcher."""
        hass = request.app[KEY_HASS]
        offer = hass.data.get(DATA_OFFERS, {}).get(key)
        if offer is None or offer.expires < time.monotonic():
            return self.json_message("Link expired", HTTPStatus.NOT_FOUND)
        if filename == TOOL_FILE:
            body = await hass.async_add_executor_job(build_tool, offer.tv, offer.bundle)
        elif filename == LAUNCHER_FILE:
            body = _LAUNCHER.encode()
        else:
            return self.json_message("Not found", HTTPStatus.NOT_FOUND)
        return web.Response(
            body=body,
            content_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
