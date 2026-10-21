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
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.app_signing import async_save_signing
from custom_components.samstream.const import CONF_LANGUAGE, CONF_THEME, CONF_TV_SECRET
from custom_components.samstream.tv_settings import (
    add_package_settings,
    ensure_tv_secret,
    package_settings,
)

from .test_app_signing import DUID, setup_for

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
    assert defaults == {CONF_LANGUAGE: "auto", CONF_THEME: "light"}

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
    assert await response.json() == {"language": "en", "theme": "dark"}

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
    assert payload["settings"] == {"language": "auto", "theme": "light"}

    original = io.BytesIO()
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("config.xml", "<widget/>")
        archive.writestr("samstream.json", "{}")
    updated = zipfile.ZipFile(
        io.BytesIO(add_package_settings(original.getvalue(), payload))
    )
    assert sorted(updated.namelist()) == ["config.xml", "samstream.json"]
    assert json.loads(updated.read("samstream.json")) == payload


@pytest.fixture
def sdb() -> MagicMock:
    client = MagicMock()
    client.connect = AsyncMock()
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

    pushed, app_id = sdb.install.await_args.args
    assert app_id == SAMSTREAM_APP_ID
    archive = zipfile.ZipFile(io.BytesIO(pushed))
    settings = json.loads(archive.read("samstream.json"))
    assert settings["tv_secret"] == setup_entry.data[CONF_TV_SECRET]
    # The settings file is covered by the signature like every other file.
    assert "samstream.json" in archive.read("author-signature.xml").decode()
