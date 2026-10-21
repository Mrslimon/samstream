"""Installing the Samstream TV app over sdb from Home Assistant."""

import io
import zipfile
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import (
    SAMSTREAM_APP_ID,
    AppStatus,
    InstallResult,
    SamstreamConnectionError,
    SdbConnectionError,
    SdbError,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.network import NoURLAvailableError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import DOMAIN
from custom_components.samstream.installer import (
    async_get_sdb_key,
    developer_problem,
    ha_lan_host,
)

from .conftest import NETFLIX, YOUTUBE

TV = "media_player.65_neo_qled_8k"
APP_SENSOR = "binary_sensor.65_neo_qled_8k_samstream_app"
SAMSTREAM = AppStatus(SAMSTREAM_APP_ID, "Samstream", False, False, "0.0.1")
LOG = [f"app_id[{SAMSTREAM_APP_ID}] installing[100]", "install completed"]


@pytest.fixture
def package(hass: HomeAssistant, tmp_path: Path) -> Path:
    """A .wgt in an allowed directory."""
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    wgt = tmp_path / "Samstream.wgt"
    with zipfile.ZipFile(wgt, "w") as archive:
        archive.writestr("config.xml", '<widget version="0.1.0"/>')
    return wgt


@pytest.fixture
def sdb() -> Generator[MagicMock]:
    """SdbClient as used by the installer: an async context manager."""
    client = MagicMock()
    client.install = AsyncMock(return_value=InstallResult(SAMSTREAM_APP_ID, LOG))
    client.connect = AsyncMock()
    client.close = AsyncMock()
    with patch(
        "custom_components.samstream.installer.SdbClient", return_value=client
    ) as factory:
        client.factory = factory
        yield client


async def _install(hass: HomeAssistant, path: str) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        "install_app",
        {ATTR_ENTITY_ID: TV, "path": path},
        blocking=True,
        return_response=True,
    )


@pytest.mark.usefixtures("setup_entry")
async def test_install_reports_log_and_rescans(
    hass: HomeAssistant, mock_tv: MagicMock, sdb: MagicMock, package: Path
) -> None:
    assert hass.states.get(APP_SENSOR).state == "off"
    mock_tv.installed_apps.return_value = [YOUTUBE, NETFLIX, SAMSTREAM]

    response = await _install(hass, str(package))

    assert response == {TV: {"app_id": SAMSTREAM_APP_ID, "log": LOG}}
    pushed, app_id = sdb.install.await_args.args
    assert app_id == SAMSTREAM_APP_ID
    # Not signed (no signing set up), but HA's settings file was added.
    assert sorted(zipfile.ZipFile(io.BytesIO(pushed)).namelist()) == [
        "config.xml",
        "samstream.json",
    ]
    host, key = sdb.factory.call_args.args
    assert host == "192.168.1.11"
    assert key.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert mock_tv.installed_apps.await_count == 2
    sensor = hass.states.get(APP_SENSOR)
    assert sensor.state == "on"
    assert sensor.attributes["version"] == "0.0.1"


@pytest.mark.usefixtures("setup_entry", "sdb")
async def test_relative_path_is_inside_config(hass: HomeAssistant) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _install(hass, "samstream/missing.wgt")
    assert err.value.translation_key == "file_not_found"


@pytest.mark.usefixtures("setup_entry", "sdb")
async def test_path_outside_allowed_dirs(hass: HomeAssistant, tmp_path: Path) -> None:
    hass.config.allowlist_external_dirs = set()
    with pytest.raises(ServiceValidationError) as err:
        await _install(hass, str(tmp_path / "x.wgt"))
    assert err.value.translation_key == "file_not_allowed"


@dataclass(frozen=True)
class RefusedCase:
    ha_url: str
    developer_mode: bool
    developer_ip: str
    error: str
    issue: str
    shown_host: str


REFUSED = [
    # Right host, not listening: the TV needs a full restart.
    RefusedCase(
        "http://192.168.1.5:8123",
        True,
        "192.168.1.5",
        "sdb_restart_needed",
        "developer_restart",
        "192.168.1.5",
    ),
    # Host set to another computer.
    RefusedCase(
        "http://192.168.1.21:8123",
        True,
        "192.168.1.5",
        "sdb_unreachable",
        "developer_mode",
        "192.168.1.5",
    ),
    # Typed into a mirrored (RTL) field: stored backwards.
    RefusedCase(
        "http://192.168.1.5:8123",
        True,
        "5.1.168.192",
        "sdb_host_reversed",
        "developer_reversed",
        "5.1.168.192",
    ),
    # Developer Mode off.
    RefusedCase(
        "http://192.168.1.5:8123",
        False,
        "192.168.1.5",
        "sdb_unreachable",
        "developer_mode",
        "off",
    ),
]


@pytest.mark.parametrize("case", REFUSED, ids=lambda case: case.issue + case.shown_host)
@pytest.mark.usefixtures("setup_entry")
async def test_unreachable_sdb_raises_repair_issue(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    sdb: MagicMock,
    package: Path,
    case: RefusedCase,
) -> None:
    await async_process_ha_core_config(hass, {"internal_url": case.ha_url})
    # Processing core config resets the allowed directories.
    hass.config.allowlist_external_dirs = {str(package.parent)}
    coordinator = setup_entry.runtime_data.coordinator
    info = replace(
        coordinator.data.info,
        developer_mode=case.developer_mode,
        developer_ip=case.developer_ip,
    )
    coordinator.async_set_updated_data(replace(coordinator.data, info=info))
    sdb.connect.side_effect = SdbConnectionError("refused")

    with pytest.raises(HomeAssistantError) as err:
        await _install(hass, str(package))

    assert err.value.translation_key == case.error
    issue_id = f"developer_mode_{setup_entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == case.issue
    assert issue.translation_placeholders == {
        "name": '65" Neo QLED 8K',
        "ha_host": case.ha_url.split("//")[1].split(":")[0],
        "developer_host": case.shown_host,
    }

    sdb.connect.side_effect = None
    await _install(hass, str(package))
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


def test_reversed_check_ignores_palindromes() -> None:
    """An address that reads the same backwards is not 'reversed'."""
    assert developer_problem("1.2.2.1", "1.2.2.1")[0] == "developer_restart"
    assert developer_problem("10.0.0.10", "10.0.0.10")[0] == "developer_restart"


@pytest.mark.usefixtures("setup_entry")
async def test_reinstalls_over_other_author(
    hass: HomeAssistant, sdb: MagicMock, package: Path
) -> None:
    sdb.uninstall = AsyncMock(return_value="uninstall completed")
    sdb.install.side_effect = [
        SdbError(
            f"Install of {SAMSTREAM_APP_ID} failed: Author certificate not match :"
        ),
        InstallResult(SAMSTREAM_APP_ID, LOG),
    ]

    response = await _install(hass, str(package))

    sdb.uninstall.assert_awaited_once_with("SmStrm0001.Samstream")
    assert sdb.install.await_count == 2
    assert response[TV]["log"] == LOG


@pytest.mark.usefixtures("setup_entry", "sdb")
async def test_not_a_package(hass: HomeAssistant, tmp_path: Path) -> None:
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    junk = tmp_path / "junk.wgt"
    junk.write_bytes(b"not a zip")
    with pytest.raises(ServiceValidationError) as err:
        await _install(hass, str(junk))
    assert "not a .wgt" in err.value.translation_placeholders["error"]


@pytest.mark.usefixtures("setup_entry")
async def test_rejected_package(
    hass: HomeAssistant, sdb: MagicMock, package: Path
) -> None:
    sdb.install.side_effect = SdbError("Check certificate error")
    with pytest.raises(HomeAssistantError) as err:
        await _install(hass, str(package))
    assert err.value.translation_key == "install_failed"
    assert err.value.translation_placeholders == {"error": "Check certificate error"}


async def test_key_created_once(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.samstream.installer.generate_key",
        return_value=b"-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY-----\n",
    ) as generate:
        first = await async_get_sdb_key(hass)
        second = await async_get_sdb_key(hass)

    assert first == second
    generate.assert_called_once()


async def test_ha_lan_host(hass: HomeAssistant) -> None:
    await async_process_ha_core_config(
        hass, {"internal_url": "http://192.168.1.5:8123"}
    )
    assert ha_lan_host(hass) == "192.168.1.5"


async def test_ha_lan_host_unknown(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.samstream.installer.get_url",
        side_effect=NoURLAvailableError,
    ):
        assert ha_lan_host(hass) is None


async def test_app_sensor_unknown_until_scanned(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    mock_tv.device_info.side_effect = SamstreamConnectionError("off")
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(APP_SENSOR).state == "unavailable"
