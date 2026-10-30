"""Frame art gallery: list stored artwork with thumbnails, for dashboard pickers.

`list_art` answers with each artwork's content id plus a signed thumbnail link
(`/api/samstream/art/<entry>/<content id>`), so an `<img>` in a dashboard can
load it without a login prompt. Thumbnails are fetched from the TV on first use,
a batch at a time, and kept in memory per TV.

The card uploads a picture (already cropped to the screen) with a POST to
`/api/samstream/art_upload/<entry>`: JPEG or PNG only, checked by its first
bytes, and passed straight to the TV (nothing is stored in Home Assistant).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aiohttp import web
from aiosamstream import SamstreamConnectionError, SamstreamError
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .const import DOMAIN

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

DATA_GALLERIES = f"{DOMAIN}_art_galleries"
LINK_LIFETIME = timedelta(hours=24)
# Content ids look like MY_F0003 or SAM-S0700; nothing else reaches the TV.
CONTENT_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
# A frame border: `none` or `<style>_<colour>` (e.g. shadowbox_sand).
MATTE = re.compile(r"^(none|[a-z]{1,24}_[a-z]{1,24})$")
MAX_UPLOAD = 25 * 1024 * 1024  # a 4K JPEG is a few MB; PNGs can be larger
_MAGIC = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png"}
BATCH = 16  # thumbnails fetched per trip to the TV
MAX_CACHED = 256
# Only these fields of a content-list item are passed on.
_FIELDS = ("content_id", "category_id", "width", "height", "image_date", "matte_id")
_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


@dataclass
class ArtGallery:
    """One Frame's listing order and the thumbnails fetched so far."""

    order: list[str] = field(default_factory=list)
    thumbnails: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    # Ids the TV has no thumbnail for (it skips them): not asked for again.
    missing: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def batch_from(self, content_id: str) -> list[str]:
        """`content_id` plus the next uncached ids in listing order."""
        ids = [content_id]
        if content_id in self.order:
            start = self.order.index(content_id) + 1
            ids += [
                i
                for i in self.order[start:]
                if i not in self.thumbnails and i not in self.missing
            ]
        return ids[:BATCH]

    def keep(self, asked: list[str], files: dict[str, tuple[bytes, str]]) -> None:
        """Cache fetched thumbnails, dropping all when the cache is full."""
        if len(self.thumbnails) + len(files) > MAX_CACHED:
            self.thumbnails.clear()
        self.thumbnails.update(files)
        self.missing.update(i for i in asked if i not in files)


def gallery(hass: HomeAssistant, entry_id: str) -> ArtGallery:
    """Return the gallery of one TV, creating it on first use."""
    galleries: dict[str, ArtGallery] = hass.data.setdefault(DATA_GALLERIES, {})
    return galleries.setdefault(entry_id, ArtGallery())


def forget(hass: HomeAssistant, entry_id: str) -> None:
    """Drop a TV's cached thumbnails (on unload)."""
    hass.data.get(DATA_GALLERIES, {}).pop(entry_id, None)


def thumbnail_url(hass: HomeAssistant, entry_id: str, content_id: str) -> str:
    """Return a signed, expiring link to one thumbnail."""
    path = f"/api/samstream/art/{entry_id}/{content_id}"
    try:
        return async_sign_path(hass, path, LINK_LIFETIME)
    except KeyError:  # auth not set up (tests): the link then needs a login
        return path


def upload_url(entry_id: str) -> str:
    """Return where the card POSTs a picture for this TV."""
    return f"/api/samstream/art_upload/{entry_id}"


def image_type(data: bytes) -> str | None:
    """Return `jpg` or `png` from the file's first bytes, else None."""
    return next(
        (kind for magic, kind in _MAGIC.items() if data.startswith(magic)), None
    )


def _frame_entry(hass: HomeAssistant, entry_id: str) -> SamstreamConfigEntry | None:
    """Return the loaded Samstream entry of a Frame, else None."""
    entry: SamstreamConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        return None
    info = entry.runtime_data.coordinator.data.info
    return entry if info and info.frame_tv else None


def describe(
    hass: HomeAssistant, entry_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the listing: the known fields, plus the thumbnail link."""
    out = []
    seen: set[str] = set()
    for item in items:
        content_id = item.get("content_id")
        if (
            not isinstance(content_id, str)
            or not CONTENT_ID.match(content_id)
            or content_id in seen
        ):
            continue  # the TV lists a picture once per category it is in
        seen.add(content_id)
        entry = {key: item[key] for key in _FIELDS if key in item}
        entry["thumbnail"] = thumbnail_url(hass, entry_id, content_id)
        out.append(entry)
    gallery(hass, entry_id).order = [item["content_id"] for item in out]
    return out


async def _async_fetch(
    entry: SamstreamConfigEntry, art: ArtGallery, content_id: str
) -> HTTPStatus | None:
    """Fetch a batch into the cache; return an error status, or None.

    The thumbnail socket sometimes drops while the art app wakes up, so a
    dropped socket is tried once more. An id the TV does not hold makes it
    refuse the request (error -1): that is a 404.
    """
    tv = entry.runtime_data.coordinator.tv
    for attempt in range(2):
        try:
            batch = art.batch_from(content_id)
            art.keep(batch, await tv.art_thumbnails(batch))
        except SamstreamConnectionError:
            if attempt:
                return HTTPStatus.BAD_GATEWAY
        except SamstreamError:
            return HTTPStatus.NOT_FOUND
        else:
            return None
    return HTTPStatus.BAD_GATEWAY  # pragma: no cover - the loop always returns


async def _read_picture(request: web.Request) -> tuple[bytes, str] | HTTPStatus:
    """Return (bytes, `jpg`|`png`) from the body, or why it is refused."""
    if (request.content_length or 0) > MAX_UPLOAD:
        return HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    # read(n) returns what has arrived so far, not the whole body: loop to EOF.
    body = bytearray()
    while chunk := await request.content.read(1024 * 1024):
        body += chunk
        if len(body) > MAX_UPLOAD:
            return HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    image = bytes(body)
    file_type = image_type(image)
    if file_type is None:
        return HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    return image, file_type


class SamstreamArtUploadView(HomeAssistantView):
    """Take a picture from the card and add it to a Frame's My Photos."""

    url = "/api/samstream/art_upload/{entry_id}"
    name = "api:samstream:art_upload"
    requires_auth = True

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Upload the request body; `?matte=` sets the border, `?show=1` shows it."""
        hass = request.app[KEY_HASS]
        entry = _frame_entry(hass, entry_id)
        if entry is None:
            return self.json_message("Not found", HTTPStatus.NOT_FOUND)
        matte = request.query.get("matte", "none")
        if not MATTE.match(matte):
            return self.json_message("Invalid border", HTTPStatus.BAD_REQUEST)
        picture = await _read_picture(request)
        if isinstance(picture, HTTPStatus):
            return self.json_message("Only a JPEG or PNG picture up to 25 MB", picture)
        image, file_type = picture
        tv = entry.runtime_data.coordinator.tv
        try:
            content_id = await tv.art_upload(
                image,
                file_type=file_type,
                show=request.query.get("show") == "1",
                matte=matte,
            )
        except SamstreamError:
            _LOGGER.exception("Uploading art to %s failed", entry.title)
            return self.json_message("Something went wrong", HTTPStatus.BAD_GATEWAY)
        gallery(hass, entry_id).order = []  # the listing is out of date now
        return self.json({"content_id": content_id})


class SamstreamArtThumbnailView(HomeAssistantView):
    """Serve one artwork thumbnail of a Frame (logged-in user or signed link)."""

    url = "/api/samstream/art/{entry_id}/{content_id}"
    name = "api:samstream:art"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, content_id: str
    ) -> web.Response:
        """Return the thumbnail image, fetching it from the TV if needed."""
        hass = request.app[KEY_HASS]
        entry: SamstreamConfigEntry | None = hass.config_entries.async_get_entry(
            entry_id
        )
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or not CONTENT_ID.match(content_id)
        ):
            return self.json_message("Not found", HTTPStatus.NOT_FOUND)
        art = gallery(hass, entry_id)
        if art.order and content_id not in art.order:
            # Not in the last listing: the TV would refuse the whole batch.
            return self.json_message("Not found", HTTPStatus.NOT_FOUND)
        async with art.lock:
            if content_id not in art.thumbnails and content_id not in art.missing:
                status = await _async_fetch(entry, art, content_id)
                if status is not None:
                    return self.json_message("Something went wrong", status)
            found = art.thumbnails.get(content_id)
        if found is None:
            return self.json_message("Not found", HTTPStatus.NOT_FOUND)
        body, file_type = found
        return web.Response(
            body=body,
            content_type=_MIME.get(file_type, "image/jpeg"),
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )
