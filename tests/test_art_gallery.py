"""Frame art gallery: select_art, list_art and the thumbnail view."""

from collections.abc import AsyncIterator
from dataclasses import replace
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SamstreamConnectionError, SamstreamError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.samstream.art_gallery import (
    BATCH,
    MAX_CACHED,
    ArtGallery,
    gallery,
)
from custom_components.samstream.const import DOMAIN

from .conftest import TV_INFO

TV = "media_player.65_neo_qled_8k"
ITEMS = [
    {
        "content_id": "MY_F0001",
        "category_id": "MY-C0002",
        "width": 3840,
        "height": 2160,
        "secret_field": "not passed on",
    },
    {"content_id": "MY_F0002", "category_id": "MY-C0002"},
    {"content_id": "bad id/../x"},  # never offered (and never sent to the TV)
    {"content_id": "MY_F0001", "category_id": "MY-C0004"},  # listed twice
]


@pytest.fixture
async def art(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> MagicMock:
    """A set-up Frame whose art channel lists ITEMS, MY_F0002 showing."""
    mock_tv.device_info = AsyncMock(return_value=replace(TV_INFO, frame_tv=True))
    channel = MagicMock()
    channel.available = AsyncMock(return_value=ITEMS)
    channel.current = AsyncMock(return_value="MY_F0002")
    channel.mattes = AsyncMock(
        return_value=(["none", "shadowbox"], {"sand": (164, 145, 113)})
    )
    mock_tv.art_upload = AsyncMock(return_value="MY_F0099")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=channel)
    context.__aexit__ = AsyncMock(return_value=None)
    mock_tv.art = MagicMock(return_value=context)
    mock_tv.art_select = AsyncMock()
    mock_tv.art_thumbnails = AsyncMock(
        return_value={"MY_F0001": (b"jpeg-1", "jpg"), "MY_F0002": (b"png-2", "png")}
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return channel


async def _list(hass: HomeAssistant, **data: str) -> dict:
    response = await hass.services.async_call(
        DOMAIN,
        "list_art",
        {"entity_id": TV, **data},
        blocking=True,
        return_response=True,
    )
    return response[TV]  # type: ignore[return-value,index]


async def test_list_art_returns_ids_and_thumbnails(
    hass: HomeAssistant, art: MagicMock
) -> None:
    result = await _list(hass, category="MY-C0002")
    art.available.assert_awaited_once_with("MY-C0002")
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    assert result["current"] == "MY_F0002"
    assert [item["content_id"] for item in result["art"]] == ["MY_F0001", "MY_F0002"]
    first = result["art"][0]
    assert first["width"] == 3840
    assert "secret_field" not in first
    assert first["thumbnail"].startswith(f"/api/samstream/art/{entry_id}/MY_F0001")
    assert result["mattes"] == {
        "styles": ["none", "shadowbox"],
        "colours": {"sand": [164, 145, 113]},
    }
    assert result["upload_url"] == f"/api/samstream/art_upload/{entry_id}"
    assert hass.states.get(TV).attributes["frame_tv"] is True


@pytest.mark.usefixtures("art")
async def test_select_art(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await hass.services.async_call(
        DOMAIN, "select_art", {"entity_id": TV, "content_id": "MY_F0001"}, blocking=True
    )
    mock_tv.art_select.assert_awaited_once_with("MY_F0001", matte=None)


@pytest.mark.usefixtures("art")
async def test_select_art_refuses_odd_ids(hass: HomeAssistant) -> None:
    with pytest.raises(Exception, match="content_id"):
        await hass.services.async_call(
            DOMAIN,
            "select_art",
            {"entity_id": TV, "content_id": "../etc"},
            blocking=True,
        )


@pytest.mark.usefixtures("setup_entry")
async def test_art_actions_need_a_frame(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.art_select = AsyncMock()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "select_art",
            {"entity_id": TV, "content_id": "MY_F0001"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await _list(hass)
    mock_tv.art_select.assert_not_called()


async def test_thumbnail_view(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    art: MagicMock,  # the Frame, set up
    hass_client: ClientSessionGenerator,
) -> None:
    await _list(hass)
    client = await hass_client()
    base = f"/api/samstream/art/{mock_entry.entry_id}"

    reply = await client.get(f"{base}/MY_F0001")
    assert reply.status == HTTPStatus.OK
    assert reply.content_type == "image/jpeg"
    assert await reply.read() == b"jpeg-1"
    # One trip fetched the batch: the next one comes from the cache.
    mock_tv.art_thumbnails.assert_awaited_once_with(["MY_F0001", "MY_F0002"])
    reply = await client.get(f"{base}/MY_F0002")
    assert reply.content_type == "image/png"
    assert mock_tv.art_thumbnails.await_count == 1

    # Not in the listing: refused here, the TV would reject the whole batch.
    assert (await client.get(f"{base}/MY_F0009")).status == HTTPStatus.NOT_FOUND
    assert mock_tv.art_thumbnails.await_count == 1

    cache = gallery(hass, mock_entry.entry_id).thumbnails
    cache.clear()
    # A socket dropped while the art app wakes: one more try.
    mock_tv.art_thumbnails.side_effect = [
        SamstreamConnectionError("woke"),
        {"MY_F0001": (b"jpeg-1", "jpg")},
    ]
    assert (await client.get(f"{base}/MY_F0001")).status == HTTPStatus.OK
    cache.clear()
    mock_tv.art_thumbnails.side_effect = SamstreamConnectionError("gone")
    reply = await client.get(f"{base}/MY_F0001")
    assert reply.status == HTTPStatus.BAD_GATEWAY
    assert "gone" not in await reply.text()  # no internals in the answer
    # The TV refusing the id (error -1): not found.
    mock_tv.art_thumbnails.side_effect = SamstreamError("failed (-1)")
    assert (await client.get(f"{base}/MY_F0001")).status == HTTPStatus.NOT_FOUND

    # Unknown TVs, bad ids: not found, and nothing is asked of the TV.
    assert (await client.get("/api/samstream/art/nope/MY_F0001")).status == 404
    assert (await client.get(f"{base}/bad%20id")).status == 404


async def test_thumbnail_view_needs_login(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    client = await hass_client_no_auth()
    reply = await client.get(f"/api/samstream/art/{setup_entry.entry_id}/MY_F0001")
    assert reply.status == HTTPStatus.UNAUTHORIZED


def test_gallery_batches_and_bounds() -> None:
    gallery = ArtGallery(order=[f"MY_F{n:04}" for n in range(40)])
    gallery.thumbnails["MY_F0002"] = (b"", "jpg")
    batch = gallery.batch_from("MY_F0000")
    assert len(batch) == BATCH
    assert "MY_F0002" not in batch
    assert gallery.batch_from("other") == ["other"]
    gallery.keep(["X0", "SAM-S1"], {f"X{n}": (b"", "jpg") for n in range(MAX_CACHED)})
    assert len(gallery.thumbnails) == MAX_CACHED  # cleared, then refilled
    assert gallery.missing == {"SAM-S1"}  # the TV skipped it: not asked again
    gallery.order.insert(1, "SAM-S1")
    assert "SAM-S1" not in gallery.batch_from("MY_F0000")


async def test_media_browser_art_folder(
    hass: HomeAssistant,
    mock_tv: MagicMock,
    art: MagicMock,  # the Frame, set up
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "media_player/browse_media",
            "entity_id": TV,
            "media_content_id": "samstream://art",
            "media_content_type": "samstream_art",
        }
    )
    answer = await client.receive_json()
    assert answer["success"], answer
    children = answer["result"]["children"]
    assert [c["media_content_id"] for c in children] == ["MY_F0001", "MY_F0002"]
    assert children[0]["thumbnail"].startswith("/api/samstream/art/")

    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": TV,
            "media_content_type": "samstream_art",
            "media_content_id": "MY_F0002",
        },
        blocking=True,
    )
    mock_tv.art_select.assert_awaited_once_with("MY_F0002", matte=None)


@pytest.mark.usefixtures("art")
async def test_select_art_with_a_border(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "select_art",
        {"entity_id": TV, "content_id": "MY_F0001", "matte": "shadowbox_sand"},
        blocking=True,
    )
    mock_tv.art_select.assert_awaited_once_with("MY_F0001", matte="shadowbox_sand")
    with pytest.raises(Exception, match="matte"):
        await hass.services.async_call(
            DOMAIN,
            "select_art",
            {"entity_id": TV, "content_id": "MY_F0001", "matte": "a b"},
            blocking=True,
        )


JPEG = b"\xff\xd8\xff\xe0" + bytes(32)
PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)


async def test_upload_view(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    art: MagicMock,  # the Frame, set up
    hass_client: ClientSessionGenerator,
) -> None:
    client = await hass_client()
    url = f"/api/samstream/art_upload/{mock_entry.entry_id}"

    reply = await client.post(f"{url}?matte=shadowbox_sand&show=1", data=JPEG)
    assert reply.status == HTTPStatus.OK
    assert await reply.json() == {"content_id": "MY_F0099"}
    mock_tv.art_upload.assert_awaited_once_with(
        JPEG, file_type="jpg", show=True, matte="shadowbox_sand"
    )
    assert (await client.post(url, data=PNG)).status == HTTPStatus.OK
    assert mock_tv.art_upload.await_args.kwargs == {
        "file_type": "png",
        "show": False,
        "matte": "none",
    }

    # A big picture arrives in many chunks: all of it reaches the TV.
    big = JPEG + bytes(3 * 1024 * 1024)

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(big), 64 * 1024):
            yield big[start : start + 64 * 1024]

    assert (await client.post(url, data=chunks())).status == HTTPStatus.OK
    assert mock_tv.art_upload.await_args.args == (big,)
    mock_tv.art_upload.reset_mock()

    # Not a picture (by its bytes, whatever it is called), bad border, too big.
    bad = await client.post(url, data=b"<svg onload=alert(1)>")
    assert bad.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert (await client.post(f"{url}?matte=../x", data=JPEG)).status == 400
    with patch("custom_components.samstream.art_gallery.MAX_UPLOAD", 16):
        assert (await client.post(url, data=JPEG)).status == 413
    with patch("custom_components.samstream.art_gallery.MAX_UPLOAD", 1024 * 1024):
        # No length up front: the size is checked while reading.
        assert (await client.post(url, data=chunks())).status == 413
    mock_tv.art_upload.assert_not_awaited()

    mock_tv.art_upload.side_effect = SamstreamError("tv says no")
    failed = await client.post(url, data=JPEG)
    assert failed.status == HTTPStatus.BAD_GATEWAY
    assert "tv says no" not in await failed.text()
    nope = "/api/samstream/art_upload/nope"
    assert (await client.post(nope, data=JPEG)).status == 404


@pytest.mark.usefixtures("setup_entry")
async def test_upload_view_only_for_frames(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    url = f"/api/samstream/art_upload/{entry_id}"
    assert (await (await hass_client()).post(url, data=JPEG)).status == 404
    assert (await (await hass_client_no_auth()).post(url, data=JPEG)).status == 401
    assert "frame_tv" not in hass.states.get(TV).attributes
