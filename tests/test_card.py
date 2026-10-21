"""App logos, the Apps folder in the media browser, and the Lovelace card."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import media_source
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.media_player import BrowseMedia, MediaClass
from homeassistant.components.media_player.const import MediaType
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.samstream.const import DOMAIN
from custom_components.samstream.frontend import CARD_FILE, URL_BASE
from custom_components.samstream.logos import match_logos

from .conftest import NETFLIX, YOUTUBE

TV = "media_player.65_neo_qled_8k"


@pytest.fixture
def logo_folder(hass: HomeAssistant) -> Path:
    folder = Path(hass.config.path("www", "samstream", "apps"))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{YOUTUBE.app_id}.png").write_bytes(b"png")
    (folder / "netflix.svg").write_bytes(b"svg")
    (folder / "notes.txt").write_text("not a logo")
    return folder


def test_match_by_id_name_or_slug() -> None:
    files = {
        "111299001912": "111299001912.png",
        "netflix": "Netflix.PNG",
        slugify("شاهد MBC"): "shahd.webp",
    }
    apps = {
        "111299001912": "YouTube",
        "3201907018807": "Netflix",
        "111477000821": "شاهد MBC",
        "x": "Other",
    }
    assert match_logos(files, apps) == {
        "111299001912": "/local/samstream/apps/111299001912.png",
        "3201907018807": "/local/samstream/apps/Netflix.PNG",
        "111477000821": "/local/samstream/apps/shahd.webp",
    }


@pytest.mark.usefixtures("logo_folder", "setup_entry")
async def test_apps_websocket(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "samstream/apps", "entity_id": TV})
    answer = await client.receive_json()

    assert answer["success"], answer
    assert answer["result"] == {
        "home": "Home",
        "current": None,
        "apps": [
            {
                "id": NETFLIX.app_id,
                "name": "Netflix",
                "logo": "/local/samstream/apps/netflix.svg",
            },
            {
                "id": YOUTUBE.app_id,
                "name": "YouTube",
                "logo": f"/local/samstream/apps/{YOUTUBE.app_id}.png",
            },
        ],
    }

    await client.send_json_auto_id(
        {"type": "samstream/apps", "entity_id": "light.kitchen"}
    )
    assert (await client.receive_json())["error"]["code"] == "not_found"


@pytest.mark.usefixtures("logo_folder", "setup_entry")
async def test_current_app_logo_is_the_picture(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:

    assert "entity_picture" not in hass.states.get(TV).attributes
    mock_tv.foreground_app.return_value = replace(YOUTUBE, visible=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    picture = hass.states.get(TV).attributes["entity_picture"]
    assert picture == f"/local/samstream/apps/{YOUTUBE.app_id}.png"


@pytest.mark.usefixtures("logo_folder", "setup_entry")
async def test_browse_apps(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    library = BrowseMedia(
        media_class=MediaClass.DIRECTORY,
        media_content_id="media-source://media_source",
        media_content_type="",
        title="Media",
        can_play=False,
        can_expand=True,
    )
    client = await hass_ws_client(hass)
    with patch.object(
        media_source, "async_browse_media", AsyncMock(return_value=library)
    ):
        await client.send_json_auto_id(
            {"type": "media_player/browse_media", "entity_id": TV}
        )
        root = (await client.receive_json())["result"]
        await client.send_json_auto_id(
            {
                "type": "media_player/browse_media",
                "entity_id": TV,
                "media_content_type": MediaType.APPS,
                "media_content_id": "samstream://apps",
            }
        )
        apps = (await client.receive_json())["result"]

    assert [child["title"] for child in root["children"]] == ["Apps", "Media"]
    assert [(app["title"], app["can_play"]) for app in apps["children"]] == [
        ("Netflix", True),
        ("YouTube", True),
    ]
    assert (
        apps["children"][1]["thumbnail"]
        == f"/local/samstream/apps/{YOUTUBE.app_id}.png"
    )


@pytest.mark.usefixtures("setup_entry")
async def test_card_is_served(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    card = next(url for url in urls if url.startswith(f"{URL_BASE}/{CARD_FILE}?v="))
    client = await hass_client()
    response = await client.get(card)
    assert response.status == 200
    assert "samstream-card" in await response.text()
    assert DOMAIN == "samstream"
