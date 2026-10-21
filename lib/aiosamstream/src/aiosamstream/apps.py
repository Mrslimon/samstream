"""Known Tizen app IDs.

2020+ firmwares no longer answer `ed.installedApp.get`, so the installed apps are
found by asking the TV about each known ID (unknown ones answer 404). Names here
are only fallbacks: the TV reports its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .const import SAMSTREAM_APP_ID

# Confirmed on a 2023 QN800C (Tizen 9): YouTube, Netflix, Prime Video, Spotify,
# Apple TV, Browser. The others are widely published IDs.
KNOWN_APPS: Final[dict[str, str]] = {
    "111299001912": "YouTube",
    "3201907018807": "Netflix",
    "3201910019365": "Prime Video",
    "3201901017640": "Disney+",
    "3201606009684": "Spotify",
    "3201807016597": "Apple TV",
    "3201908019041": "Apple Music",
    "3202010022079": "Browser",
    "3201512006963": "Plex",
    "3201611010983": "YouTube Kids",
    "3201601007230": "HBO Max",
    "3201710014981": "Paramount+",
    "3201808016802": "Pluto TV",
    "3201511006428": "Rakuten TV",
    "3201608010385": "Deezer",
    "3201702011851": "Steam Link",
    "11091000000": "Facebook Watch",
    SAMSTREAM_APP_ID: "Samstream",
}


# vd_applist prints blocks of "-------<key>   =<value>-------" lines between rules.
_FIELD = re.compile(r"^\s*-{3,}\s*(?P<key>[^\s=]+)\s*=\s*(?P<value>.*?)\s*-{3,}\s*$")


@dataclass(frozen=True, slots=True)
class ListedApp:
    """One installed app from `vd_applist` (needs Developer Mode / sdb)."""

    # The store ID the REST API understands (e.g. 111299001912), not the Tizen ID.
    app_id: str
    tizen_id: str
    name: str
    version: str | None


def parse_app_list(text: str) -> list[ListedApp]:
    """Parse `0 vd_applist` output; hidden apps are left out."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if match := _FIELD.match(line):
            current[match.group("key")] = match.group("value")
        elif current and "----" in line and "=" not in line:
            blocks.append(current)
            current = {}
    if current:
        blocks.append(current)
    listed = []
    for block in blocks:
        app_id = block.get("app_id") or block.get("app_tizen_id")
        if not app_id or block.get("is_hidden") == "1":
            continue
        listed.append(
            ListedApp(
                app_id=app_id,
                tizen_id=block.get("app_tizen_id", app_id),
                name=block.get("app_title") or app_id,
                version=block.get("app_version") or None,
            )
        )
    return listed
