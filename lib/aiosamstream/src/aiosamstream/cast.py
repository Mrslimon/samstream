"""Turn a web link into a casting target: a YouTube video id, or a web page."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_YT_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)
# A YouTube video id is 11 characters of the URL-safe base64 alphabet.
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


def youtube_id(url: str) -> str | None:
    """Return the video id from a YouTube watch / shorts / youtu.be link, else None.

    Handles `watch?v=`, `youtu.be/<id>`, and `/shorts|/embed|/live|/v/<id>`,
    ignoring extra query parameters. Anything that is not a YouTube link, or has
    no 11-character id, returns None.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = parsed.netloc.lower()
    if host not in _YT_HOSTS:
        return None
    if host in ("youtu.be", "www.youtu.be"):
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
    elif parsed.path.startswith(_PATH_PREFIXES):
        candidate = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    else:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    return candidate if _ID.match(candidate) else None
