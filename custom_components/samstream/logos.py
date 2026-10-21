"""App logos the user provides: /config/www/samstream/apps/<file> (png, jpg, svg).

Samsung TVs do not hand out app icons and there is no public lookup by app ID,
so logos come from this folder (served by HA at /local/samstream/apps/). A file
matches an app by its ID (`111299001912.png`), its name as the TV shows it
(`YouTube.png`, `شاهد MBC.png`) or that name slugified (`netflix.png`).
Apps without a file get a letter tile in the card.
"""

from __future__ import annotations

from pathlib import Path

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
