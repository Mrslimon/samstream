"""Talk to the native .NET notifier app running on the TV (`:8181`).

The notifier posts a real Samsung notification (title + text, with a chime) over
whatever is playing, which the web-app notice cannot do. HA reaches it with a
plain HTTP GET on the TV's LAN address. Only HA may post: every request is signed
with HMAC-SHA256 over its fields, using the TV's per-TV secret, and carries a
timestamp and a single-use nonce so a captured request cannot be replayed. The
notifier refuses anything missing, stale, replayed or wrongly signed.

The key the notifier checks is the same `tv_secret` HA stamps into the package at
install (`res/shared.key`), the credential the web app already uses.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import secrets
import time
import zipfile
from http import HTTPStatus

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

_LOGGER = logging.getLogger(__name__)

# The notifier app (the .NET companion that posts native notifications) and the
# port its listener binds (see tv-app/notifier-dotnet). It is its own nodisplay
# package; the web app starts it. Tizen has no Web-UI + .NET hybrid.
NOTIFIER_APP_ID = "org.samstream.notifier"
NOTIFIER_PORT = 8181
# The key file HA stamps into the .tpk; the notifier reads it from its res dir.
NOTIFIER_KEY_FILE = "res/shared.key"
# The notifier refuses a request whose timestamp is off by more than this; keep
# HA's own deadline under it so a slow request fails as "stale", not a false post.
_SKEW_SECONDS = 30
_TIMEOUT = aiohttp.ClientTimeout(total=5)
_HEALTH_TIMEOUT = aiohttp.ClientTimeout(total=3)


def _signature(secret: str, parts: list[str]) -> str:
    """Return the hex HMAC-SHA256 the notifier recomputes to authorize a post.

    `parts` are joined with newlines, in the order the notifier rebuilds them:
    ts, nonce, title, content, icon, image.
    """
    message = "\n".join(parts).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signed_notify_url(  # noqa: PLR0913 - one argument per notification field
    host: str,
    secret: str,
    title: str,
    content: str,
    *,
    icon: str = "",
    image: str = "",
    now: float | None = None,
) -> URL:
    """Build the signed GET URL HA sends the notifier for one notification.

    `icon` selects a bundled icon by name (res/icons/<icon>.png on the TV);
    `image` is an http(s) URL the notifier downloads and shows (e.g. a camera
    snapshot). Both are covered by the signature, so they can't be tampered with.
    """
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_hex(8)
    sig = _signature(secret, [ts, nonce, title, content, icon, image])
    return URL.build(
        scheme="http",
        host=host,
        port=NOTIFIER_PORT,
        path="/notify",
        query={
            "title": title,
            "content": content,
            "icon": icon,
            "image": image,
            "ts": ts,
            "nonce": nonce,
            "sig": sig,
        },
    )


async def async_notifier_alive(hass: HomeAssistant, host: str) -> bool:
    """Return True if the notifier answers its unauthenticated health check."""
    session = async_get_clientsession(hass)
    url = URL.build(scheme="http", host=host, port=NOTIFIER_PORT, path="/health")
    try:
        async with session.get(url, timeout=_HEALTH_TIMEOUT) as resp:
            return resp.status == HTTPStatus.OK
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Notifier health check failed on %s: %s", host, err)
        return False


async def async_post_native(  # noqa: PLR0913 - one argument per notification field
    hass: HomeAssistant,
    host: str,
    secret: str,
    title: str,
    content: str,
    *,
    icon: str = "",
    image: str = "",
) -> bool:
    """Post a native notification to the TV; True on a 200, False otherwise.

    Never raises: an unreachable or refusing notifier is a soft miss so the
    caller can fall back to the web-app notice.
    """
    session = async_get_clientsession(hass)
    url = signed_notify_url(host, secret, title, content, icon=icon, image=image)
    try:
        async with session.get(url, timeout=_TIMEOUT) as resp:
            if resp.status == HTTPStatus.OK:
                return True
            _LOGGER.debug(
                "Notifier on %s refused the post: HTTP %s", host, resp.status
            )
            return False
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not reach the notifier on %s: %s", host, err)
        return False


def stamp_notifier_key(tpk: bytes, secret: str) -> bytes:
    """Return the notifier package with the TV's shared key written into it.

    Mirrors how the web app's `samstream.json` is added — a pure zip rewrite, so
    no .NET toolchain is needed in HA. The notifier reads `res/shared.key` and
    refuses every post when it is absent, so stamping is what lets HA in.
    """
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(tpk)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            if item.filename != NOTIFIER_KEY_FILE:
                target.writestr(item, source.read(item))
        target.writestr(NOTIFIER_KEY_FILE, secret)
    return out.getvalue()
