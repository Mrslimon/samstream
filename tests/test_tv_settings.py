"""TV app settings: options step, per-TV secret, settings view, package file."""

import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SAMSTREAM_APP_ID, InstallResult
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.app_signing import async_save_signing
from custom_components.samstream.const import (
    CONF_CAMERAS,
    CONF_LANGUAGE,
    CONF_THEME,
    CONF_TV_SECRET,
)
from custom_components.samstream.tv_settings import (
    add_package_settings,
    async_resolve_cameras,
    ensure_tv_secret,
    package_settings,
)

from .test_app_signing import DUID, setup_for
from .test_stream import RTSP, FakeGo2rtc, go2rtc  # noqa: F401 - go2rtc is a fixture

INSTALL_BUTTON = "button.65_neo_qled_8k_install_samstream_app"


async def _tv_app_options(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "tv_app" in result["menu_options"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "tv_app"}
    )


async def test_options_step_defaults_and_save(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await _tv_app_options(hass, setup_entry)
    assert result["type"] is FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults == {
        CONF_LANGUAGE: "auto",
        CONF_THEME: "light",
        "tv_corner": "top_right",
        "resume_playback": True,
        "auto_update": True,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LANGUAGE: "ar", CONF_THEME: "dark"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_LANGUAGE] == "ar"
    assert setup_entry.options[CONF_THEME] == "dark"


async def test_network_options_keep_tv_settings(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(setup_entry, options={CONF_LANGUAGE: "ar"})
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "network"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"wol_target": "192.168.1.255"}
    )
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_LANGUAGE] == "ar"


async def test_secret_created_once(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    first = ensure_tv_secret(hass, setup_entry)
    await hass.async_block_till_done()
    assert len(first) >= 24
    assert ensure_tv_secret(hass, setup_entry) == first
    assert setup_entry.data[CONF_TV_SECRET] == first
    # Storing the secret is a data update: the integration is not reloaded.
    assert setup_entry.runtime_data.coordinator.last_update_success


async def test_settings_view(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    secret = ensure_tv_secret(hass, setup_entry)
    hass.config_entries.async_update_entry(
        setup_entry, options={CONF_LANGUAGE: "en", CONF_THEME: "dark"}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()

    response = await client.get(f"/api/samstream/tv/{secret}/settings")
    assert response.status == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert await response.json() == {"language": "en", "theme": "dark", "cameras": []}

    unknown = await client.get("/api/samstream/tv/not-a-tv/settings")
    assert unknown.status == 404


async def test_package_settings_file(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )
    payload = package_settings(hass, setup_entry)
    assert payload["ha_url"] == "http://192.168.1.5:8123"
    assert payload["settings"] == {
        "language": "auto",
        "theme": "light",
        "cameras": [],
    }

    original = io.BytesIO()
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("config.xml", "<widget/>")
        archive.writestr("samstream.json", "{}")
    updated = zipfile.ZipFile(
        io.BytesIO(add_package_settings(original.getvalue(), payload))
    )
    assert sorted(updated.namelist()) == ["config.xml", "samstream.json"]
    assert json.loads(updated.read("samstream.json")) == payload


CAMERA = "camera.front_door"


async def _async_options_cameras(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "cameras" in result["menu_options"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "cameras"}
    )


async def test_cameras_option_step_saves_in_field_order(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Numbered dropdowns, not a multi-select: field order is the saved order."""
    result = await _async_options_cameras(hass, setup_entry)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"camera_1": "camera.b", "camera_2": "camera.a"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_entry.options[CONF_CAMERAS] == ["camera.b", "camera.a"]


async def test_cameras_option_step_defaults_show_the_saved_order(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        setup_entry,
        options={**setup_entry.options, CONF_CAMERAS: ["camera.b", "camera.a"]},
    )
    # The option change reloads the entry in the background (async_resolve_cameras
    # runs again, for cameras that don't exist here) - let it finish before this
    # test ends, or it can fail the next test's hass fixture teardown instead.
    await hass.async_block_till_done()
    result = await _async_options_cameras(hass, setup_entry)
    defaults = result["data_schema"]({})
    assert defaults["camera_1"] == "camera.b"
    assert defaults["camera_2"] == "camera.a"
    assert "camera_3" not in defaults


@pytest.mark.usefixtures("socket_enabled")
async def test_async_resolve_cameras_registers_and_builds_the_list(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    go2rtc: FakeGo2rtc,  # noqa: F811
) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )
    hass.states.async_set(CAMERA, "idle", {"friendly_name": "Front door"})
    hass.config_entries.async_update_entry(mock_entry, options={CONF_CAMERAS: [CAMERA]})
    with patch(
        "custom_components.samstream.tv_settings.async_get_stream_source",
        AsyncMock(return_value=RTSP),
    ):
        streams = await async_resolve_cameras(hass, mock_entry)
    assert len(streams) == 1
    assert streams[0]["label"] == "Front door"
    assert streams[0]["type"] == "mse"
    assert streams[0]["url"].startswith("ws://192.168.1.5:8123/api/samstream/tv/")
    assert list(go2rtc.streams.values()) == [RTSP]


@pytest.mark.usefixtures("socket_enabled")
async def test_async_resolve_cameras_skips_a_camera_with_no_source(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    go2rtc: FakeGo2rtc,  # noqa: F811
) -> None:
    hass.states.async_set(CAMERA, "idle")
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_CAMERAS: [CAMERA, "camera.gone"]}
    )
    with patch(
        "custom_components.samstream.tv_settings.async_get_stream_source",
        AsyncMock(return_value=None),
    ):
        streams = await async_resolve_cameras(hass, mock_entry)
    assert streams == []
    assert go2rtc.streams == {}


@pytest.mark.usefixtures("socket_enabled")
async def test_async_resolve_cameras_skips_a_camera_that_errors(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    go2rtc: FakeGo2rtc,  # noqa: F811
) -> None:
    """One bad camera (removed, unavailable) does not block the rest of setup."""
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_CAMERAS: ["camera.gone"]}
    )
    with patch(
        "custom_components.samstream.tv_settings.async_get_stream_source",
        AsyncMock(side_effect=HomeAssistantError("not found")),
    ):
        streams = await async_resolve_cameras(hass, mock_entry)
    assert streams == []


@pytest.fixture
def sdb() -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
    client.duid = AsyncMock(return_value="EXCBZZZZGFIFJSY")
    client.close = AsyncMock()
    client.install = AsyncMock(
        return_value=InstallResult(SAMSTREAM_APP_ID, ["install completed"])
    )
    with patch("custom_components.samstream.installer.SdbClient", return_value=client):
        yield client


async def test_installed_package_carries_settings(
    hass: HomeAssistant, setup_entry: MockConfigEntry, sdb: MagicMock
) -> None:
    await async_save_signing(hass, setup_for([DUID]))
    await hass.services.async_call(
        "button", "press", {"entity_id": INSTALL_BUTTON}, blocking=True
    )

    # The web app is the first install; the notifier rides along as the second.
    pushed, app_id = sdb.install.await_args_list[0].args
    assert app_id == SAMSTREAM_APP_ID
    archive = zipfile.ZipFile(io.BytesIO(pushed))
    settings = json.loads(archive.read("samstream.json"))
    assert settings["tv_secret"] == setup_entry.data[CONF_TV_SECRET]
    # The settings file is covered by the signature like every other file.
    assert "samstream.json" in archive.read("author-signature.xml").decode()
