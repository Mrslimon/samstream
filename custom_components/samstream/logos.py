"""App logos the user provides: /config/www/samstream/apps/<file> (png, jpg, svg).

Samsung TVs do not hand out app icons and there is no public lookup by app ID,
so logos come from this folder (served by HA at /local/samstream/apps/). A file
matches an app by its ID (`111299001912.png`), its name as the TV shows it
(`YouTube.png`, `شاهد MBC.png`) or that name slugified (`netflix.png`).
Apps without a file get a letter tile in the card. The "Download app logos"
button fills the folder from each app's public website icon.
"""

from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path

import aiohttp
from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

LOGO_FOLDER = ("www", "samstream", "apps")
LOGO_URL = "/local/samstream/apps/"
_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg")


def _scan(folder: Path) -> dict[str, str]:
    """Logo files by lower-case stem."""
    if not folder.is_dir():
        return {}
    return {
        path.stem.casefold(): path.name
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in _EXTENSIONS
    }


def match_logos(files: dict[str, str], apps: dict[str, str]) -> dict[str, str]:
    """App ID -> logo URL for the apps that have a file."""
    logos: dict[str, str] = {}
    for app_id, name in apps.items():
        for key in (app_id, name, slugify(name)):
            if key and (file := files.get(key.casefold())):
                logos[app_id] = LOGO_URL + file
                break
    return logos


async def async_app_logos(hass: HomeAssistant, apps: dict[str, str]) -> dict[str, str]:
    """Read the logo folder (in the executor) and match it to `apps`."""
    folder = Path(hass.config.path(*LOGO_FOLDER))
    files = await hass.async_add_executor_job(_scan, folder)
    return match_logos(files, apps)


# ---- Download (the "Download app logos" button) --------------------------------
#
# Logos stay out of the repository (they belong to the app makers); this fetches
# each app's public site icon onto the user's own HA, into the folder above.
# Matched by words in the app's name, so regional app IDs work too.
LOGO_SITES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("youtube",), "youtube.com"),
    (("netflix",), "netflix.com"),
    (("disney",), "disneyplus.com"),
    (("prime video", "amazon prime"), "primevideo.com"),
    (("apple tv",), "tv.apple.com"),
    (("apple music",), "music.apple.com"),
    (("spotify",), "spotify.com"),
    (("anghami", "أنغامي"), "anghami.com"),
    (("deezer",), "deezer.com"),
    (("osn",), "osnplus.com"),
    (("starzplay", "starz play"), "starzplay.com"),
    (("shahid", "شاهد"), "shahid.mbc.net"),
    (("tod", "bein"), "tod.tv"),
    (("الشرق", "asharq"), "asharq.com"),
    (("yango", "يانغو"), "play.yango.com"),
    (("weyyak", "وياك"), "weyyak.com"),
    (("watch it", "watchit"), "watchit.com"),
    (("stremio",), "stremio.com"),
    (("plex",), "plex.tv"),
    (("jellyfin",), "jellyfin.org"),
    (("emby",), "emby.media"),
    (("kodi",), "kodi.tv"),
    (("twitch",), "twitch.tv"),
    (("tiktok",), "tiktok.com"),
    (("max", "hbo"), "max.com"),
    (("paramount",), "paramountplus.com"),
    (("pluto",), "pluto.tv"),
    (("tubi",), "tubitv.com"),
    (("geforce",), "nvidia.com"),
    (("xbox",), "xbox.com"),
    (("steam",), "steampowered.com"),
    (("copilot",), "copilot.microsoft.com"),
    (
        ("smartthings", "bixby", "browser", "samsung", "user guide", "securitycenter"),
        "samsung.com",
    ),
)
# Tried in order; the largest PNG wins (site icons vary from 16 to 256 px).
_ICON_URLS = (
    "https://www.google.com/s2/favicons?domain={domain}&sz=256",
    "https://{domain}/apple-touch-icon.png",
)
_MIN_SIZE = 32
_PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
_PNG_HEADER = 24  # signature + IHDR length/type + width/height
_SAMSTREAM_ICON = Path(__file__).parent / "brand" / "icon@2x.png"


def logo_site(name: str) -> str | None:
    """Website whose icon stands for the app called `name`, if known."""
    folded = name.casefold()
    for keywords, domain in LOGO_SITES:
        for keyword in keywords:
            # Latin keywords match whole words ("tod" is not "today"); Arabic ones
            # match anywhere in the name.
            escaped = re.escape(keyword)
            pattern = rf"\b{escaped}\b" if keyword.isascii() else escaped
            if re.search(pattern, folded):
                return domain
    return None


def png_size(data: bytes) -> int:
    """Width of a PNG image (0 if it is not one)."""
    if data[:8] != _PNG_SIGNATURE or len(data) < _PNG_HEADER:
        return 0
    return int.from_bytes(data[16:20], "big")


async def async_download_logos(
    hass: HomeAssistant, apps: dict[str, str], session: aiohttp.ClientSession
) -> dict[str, str]:
    """Fetch logos for apps without one; return app ID -> what happened."""
    folder = Path(hass.config.path(*LOGO_FOLDER))
    have = match_logos(await hass.async_add_executor_job(_scan, folder), apps)
    results: dict[str, str] = {}
    for app_id, name in apps.items():
        if app_id in have:
            results[app_id] = "kept"
            continue
        if app_id == SAMSTREAM_APP_ID:
            data = await hass.async_add_executor_job(_SAMSTREAM_ICON.read_bytes)
        elif domain := logo_site(name):
            data = await _best_icon(session, domain)
        else:
            results[app_id] = "unknown"
            continue
        if png_size(data) < _MIN_SIZE:
            results[app_id] = "not_found"
            continue
        await hass.async_add_executor_job(_save, folder / f"{app_id}.png", data)
        results[app_id] = "downloaded"
    return results


async def _best_icon(session: aiohttp.ClientSession, domain: str) -> bytes:
    best = b""
    for template in _ICON_URLS:
        try:
            async with session.get(
                template.format(domain=domain), timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                ok = response.status == HTTPStatus.OK
                data = await response.read() if ok else b""
        except aiohttp.ClientError, TimeoutError:
            continue
        if png_size(data) > png_size(best):
            best = data
    return best


def _save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
