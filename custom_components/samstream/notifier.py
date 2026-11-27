"""Talk to the native .NET notifier app running on the TV (`:8181`).

The notifier posts a real Samsung notification (title + text, with a chime) over
whatever is playing, which the web-app notice cannot do, and draws the corner
camera there. HA reaches it with plain HTTP on the TV's LAN address (GET for a
notification, POST for the camera). Only HA may use it: every request is signed
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
# The corner camera request's fields, in the order the notifier signs them.
CAMERA_FIELDS = (
    "corner",
    "size",
    "seconds",
    "url",
    "title",
    "message",
    "text_position",
    "text_size",
)
# The caption has room for two lines; longer text would only bloat the URL.
_MAX_TEXT = 300


def _signature(secret: str, parts: list[str]) -> str:
    """Return the hex HMAC-SHA256 the notifier recomputes to authorize a request.

    `parts` are joined with newlines, in the order the notifier rebuilds them:
    ts, nonce, then the request's own fields.
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
    return _signed_url(
        host,
        secret,
        "/notify",
        [title, content, icon, image],
        {"title": title, "content": content, "icon": icon, "image": image},
        now=now,
    )


def _signed_url(  # noqa: PLR0913 - the parts of one signed request
    host: str,
    secret: str,
    path: str,
    fields: list[str],
    query: dict[str, str],
    *,
    now: float | None = None,
) -> URL:
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_hex(8)
    sig = _signature(secret, [ts, nonce, *fields])
    return URL.build(
        scheme="http",
        host=host,
        port=NOTIFIER_PORT,
        path=path,
        query={**query, "ts": ts, "nonce": nonce, "sig": sig},
    )


def signed_camera_url(
    host: str, secret: str, view: dict[str, str], *, now: float | None = None
) -> URL:
    """Build the signed POST URL that shows the corner camera (`CAMERA_FIELDS`)."""
    query = {key: view[key] for key in CAMERA_FIELDS}
    query["title"] = query["title"][:_MAX_TEXT]
    query["message"] = query["message"][:_MAX_TEXT]
    return _signed_url(
        host, secret, "/camera", ["camera", *query.values()], query, now=now
    )


async def _async_camera_post(hass: HomeAssistant, host: str, url: URL) -> bool:
    session = async_get_clientsession(hass)
    try:
        async with session.post(url, timeout=_TIMEOUT) as resp:
            if resp.status == HTTPStatus.OK:
                return True
            _LOGGER.debug(
                "Notifier on %s refused %s: HTTP %s", host, url.path, resp.status
            )
            return False
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not reach the notifier on %s: %s", host, err)
        return False


async def async_show_camera(
    hass: HomeAssistant, host: str, secret: str, view: dict[str, str]
) -> bool:
    """Show a camera in a corner of the TV; True when the notifier accepted it."""
    return await _async_camera_post(hass, host, signed_camera_url(host, secret, view))


async def async_camera_message(
    hass: HomeAssistant, host: str, secret: str, message: str
) -> bool:
    """Change the text on the corner camera, if one is showing."""
    message = message[:_MAX_TEXT]
    url = _signed_url(
        host,
        secret,
        "/camera/message",
        ["camera/message", message],
        {"message": message},
    )
    return await _async_camera_post(hass, host, url)


async def async_close_camera(hass: HomeAssistant, host: str, secret: str) -> bool:
    """Remove the corner camera from the TV."""
    url = _signed_url(host, secret, "/camera/close", ["camera/close"], {})
    return await _async_camera_post(hass, host, url)


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
            _LOGGER.debug("Notifier on %s refused the post: HTTP %s", host, resp.status)
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
