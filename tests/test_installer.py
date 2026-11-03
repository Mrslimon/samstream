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

from custom_components.samstream.app_signing import async_save_signing
from custom_components.samstream.const import DOMAIN
from custom_components.samstream.installer import (
    LRI,
    PDI,
    async_get_sdb_key,
    developer_problem,
    ha_lan_host,
    ip_boxes,
)
from custom_components.samstream.notifier import NOTIFIER_APP_ID, NOTIFIER_KEY_FILE

from .conftest import NETFLIX, YOUTUBE
from .test_app_signing import setup_for

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
    # The DUID the test certificates list (test_app_signing.DUID).
    client.duid = AsyncMock(return_value="EXCBZZZZGFIFJSY")
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
    host = case.ha_url.split("//")[1].split(":")[0]
    assert issue.translation_placeholders == {
        "name": '65" Neo QLED 8K',
        "ha_host": host,
        "ha_host_boxes": ip_boxes(host),
        "ha_host_rtl": ip_boxes(host, reverse=True),
        "developer_host": case.shown_host,
    }

    sdb.connect.side_effect = None
    await _install(hass, str(package))
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


def test_ip_boxes() -> None:
    """One part per TV box; reversed for right-to-left menus; kept left-to-right."""
    assert ip_boxes("192.168.1.5") == f"{LRI}192  |  168  |  1  |  5{PDI}"
    assert ip_boxes("192.168.1.5", reverse=True) == f"{LRI}5  |  1  |  168  |  192{PDI}"
    assert ip_boxes("ha.local") == "ha.local"
    assert ip_boxes("?", reverse=True) == "?"


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


@pytest.mark.usefixtures("setup_entry")
async def test_install_refused_when_certificate_lacks_tv(
    hass: HomeAssistant, setup_entry: MockConfigEntry, sdb: MagicMock
) -> None:
    """A TV the certificate does not list: a clear error, not the TV's cryptic one."""
    await async_save_signing(hass, setup_for(["OTHERTVDUID"]))
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "install_app",
            {"entity_id": TV},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "certificate_missing_tv"
    sdb.install.assert_not_awaited()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"duid_not_covered_{setup_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["duid"] == "EXCBZZZZGFIFJSY"
    # The DUID is remembered for the next certificate.
    assert setup_entry.data["duid"] == "EXCBZZZZGFIFJSY"

    await async_save_signing(hass, setup_for(["EXCBZZZZGFIFJSY"]))
    await hass.services.async_call(
        DOMAIN, "install_app", {"entity_id": TV}, blocking=True, return_response=True
    )
    # The bundled web app installs, and the notifier rides on the same session.
    installed_ids = [call.args[1] for call in sdb.install.await_args_list]
    assert installed_ids == [SAMSTREAM_APP_ID, NOTIFIER_APP_ID]
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"duid_not_covered_{setup_entry.entry_id}"
        )
        is None
    )


@pytest.mark.usefixtures("setup_entry")
async def test_notifier_installed_alongside_signed_and_stamped(
    hass: HomeAssistant, sdb: MagicMock
) -> None:
    """The bundled install also installs the notifier, key-stamped and signed."""
    await async_save_signing(hass, setup_for(["EXCBZZZZGFIFJSY"]))
    await hass.services.async_call(
        DOMAIN, "install_app", {"entity_id": TV}, blocking=True, return_response=True
    )
    assert sdb.install.await_count == 2
    notifier_tpk, app_id = sdb.install.await_args_list[1].args
    assert app_id == NOTIFIER_APP_ID
    names = zipfile.ZipFile(io.BytesIO(notifier_tpk)).namelist()
    # The TV secret is stamped in, and HA re-signed it (covers the key file).
    assert NOTIFIER_KEY_FILE in names
    assert "author-signature.xml" in names
    assert "signature1.xml" in names


@pytest.mark.usefixtures("setup_entry")
async def test_notifier_failure_does_not_fail_web_install(
    hass: HomeAssistant, sdb: MagicMock
) -> None:
    """A notifier install error is swallowed; the web app install still succeeds."""
    await async_save_signing(hass, setup_for(["EXCBZZZZGFIFJSY"]))
    sdb.install.side_effect = [
        InstallResult(SAMSTREAM_APP_ID, LOG),
        SdbError("Install of org.samstream.notifier failed: whatever"),
    ]
    response = await hass.services.async_call(
        DOMAIN, "install_app", {"entity_id": TV}, blocking=True, return_response=True
    )
    # The web app's result is returned even though the notifier install failed.
    assert response[TV]["app_id"] == SAMSTREAM_APP_ID
    assert sdb.install.await_count == 2


async def _uninstall(hass: HomeAssistant) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        "uninstall_app",
        {ATTR_ENTITY_ID: TV},
        blocking=True,
        return_response=True,
    )


@pytest.mark.usefixtures("setup_entry")
async def test_uninstall_removes_both_apps(
    hass: HomeAssistant, mock_tv: MagicMock, sdb: MagicMock
) -> None:
    """Uninstall removes the web app and the notifier, and reports both."""
    mock_tv.installed_apps.return_value = [YOUTUBE, NETFLIX]
    sdb.uninstall = AsyncMock(return_value="uninstall completed")

    response = await _uninstall(hass)

    assert response[TV]["removed"] == [SAMSTREAM_APP_ID, NOTIFIER_APP_ID]
    removed_ids = [call.args[0] for call in sdb.uninstall.await_args_list]
    assert removed_ids == [SAMSTREAM_APP_ID, NOTIFIER_APP_ID]


@pytest.mark.usefixtures("setup_entry")
async def test_uninstall_skips_an_app_that_is_not_installed(
    hass: HomeAssistant, mock_tv: MagicMock, sdb: MagicMock
) -> None:
    """An app already gone is not reported, but the other is still removed."""
    mock_tv.installed_apps.return_value = [YOUTUBE, NETFLIX]
    sdb.uninstall = AsyncMock(
        side_effect=["uninstall completed", "was get app info failed"]
    )

    response = await _uninstall(hass)

    # The notifier was not installed; only the web app came off.
    assert response[TV]["removed"] == [SAMSTREAM_APP_ID]
    assert sdb.uninstall.await_count == 2


@pytest.mark.usefixtures("setup_entry")
async def test_uninstall_requires_sdb(
    hass: HomeAssistant, sdb: MagicMock
) -> None:
    """When the TV refuses sdb, uninstall raises and the repair issue is created."""
    sdb.connect = AsyncMock(side_effect=SdbConnectionError("refused"))
    with pytest.raises(HomeAssistantError):
        await _uninstall(hass)
