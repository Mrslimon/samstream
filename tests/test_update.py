"""Samstream TV app update entity, certificate expiry repair and renewal."""

import asyncio
import zipfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import SAMSTREAM_APP_ID, AppStatus
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.samstream import installer
from custom_components.samstream.app_signing import (
    EXPIRY_ISSUE,
    async_check_certificate_expiry,
    async_save_signing,
)
from custom_components.samstream.const import DOMAIN

from .conftest import NETFLIX, YOUTUBE
from .test_app_signing import ACCOUNT, DUID, identity, setup_for

UPDATE = "update.65_neo_qled_8k_samstream_tv_app"


def samstream(version: str) -> AppStatus:
    return AppStatus(SAMSTREAM_APP_ID, "Samstream", False, False, version)


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    tv: MagicMock,
    *,
    installed: str | None,
    bundled: str | None = "0.1.0",
) -> None:
    apps = [YOUTUBE, NETFLIX] + ([samstream(installed)] if installed else [])
    tv.installed_apps.return_value = apps
    with patch(
        "custom_components.samstream.async_bundled_version",
        AsyncMock(return_value=bundled),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_update_offered(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    await _setup(hass, mock_entry, mock_tv, installed="0.0.1")

    state = hass.states.get(UPDATE)
    assert state.state == "on"
    assert state.attributes["installed_version"] == "0.0.1"
    assert state.attributes["latest_version"] == "0.1.0"
    assert state.attributes["in_progress"] is False


async def test_up_to_date(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    await _setup(hass, mock_entry, mock_tv, installed="0.1.0")
    assert hass.states.get(UPDATE).state == "off"


@pytest.mark.parametrize(("installed", "bundled"), [(None, "0.1.0"), ("0.0.1", None)])
async def test_unavailable_without_app_or_bundle(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    installed: str | None,
    bundled: str | None,
) -> None:
    await _setup(hass, mock_entry, mock_tv, installed=installed, bundled=bundled)
    assert hass.states.get(UPDATE).state == "unavailable"


async def test_install_shows_progress(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    await _setup(hass, mock_entry, mock_tv, installed="0.0.1")
    release = asyncio.Event()
    coordinator = mock_entry.runtime_data.coordinator

    async def slow_install(*_args: object) -> None:
        coordinator.installing = True
        coordinator.async_update_listeners()
        await release.wait()
        coordinator.installing = False
        coordinator.async_update_listeners()

    with patch(
        "custom_components.samstream.update.async_install_package",
        AsyncMock(side_effect=slow_install),
    ) as install:
        task = hass.async_create_task(
            hass.services.async_call(
                "update", "install", {"entity_id": UPDATE}, blocking=True
            )
        )
        await asyncio.sleep(0.05)
        assert hass.states.get(UPDATE).attributes["in_progress"] is True
        release.set()
        await task

    install.assert_awaited_once_with(hass, mock_entry, None)
    assert hass.states.get(UPDATE).attributes["in_progress"] is False


@pytest.mark.parametrize(
    ("days", "severity", "key"),
    [
        (10, ir.IssueSeverity.WARNING, "certificate_expiring"),
        (-1, ir.IssueSeverity.ERROR, "certificate_expired"),
    ],
)
async def test_expiry_issue(
    hass: HomeAssistant, days: int, severity: ir.IssueSeverity, key: str
) -> None:
    await async_save_signing(hass, setup_for([DUID], days=days))
    await async_check_certificate_expiry(hass)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, EXPIRY_ISSUE)
    assert issue is not None
    assert issue.severity is severity
    assert issue.translation_key == key
    assert "date" in issue.translation_placeholders

    await async_save_signing(hass, setup_for([DUID], days=365))
    await async_check_certificate_expiry(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, EXPIRY_ISSUE) is None


async def test_no_issue_without_signing(hass: HomeAssistant) -> None:
    await async_check_certificate_expiry(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, EXPIRY_ISSUE) is None


async def test_expiry_checked_at_setup(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    await async_save_signing(hass, setup_for([DUID], days=5))
    await _setup(hass, mock_entry, mock_tv, installed="0.0.1")
    assert ir.async_get(hass).async_get_issue(DOMAIN, EXPIRY_ISSUE) is not None


async def test_sign_in_renews_expiring_certificates(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    current = setup_for([DUID], days=10)
    await async_save_signing(hass, current)
    await async_check_certificate_expiry(hass)
    renewed_author = identity(days=365)
    renewed_distributor = identity([DUID], days=365)
    with (
        patch(
            "custom_components.samstream.installer.async_read_duid",
            AsyncMock(return_value=DUID),
        ),
        patch(
            "custom_components.samstream.installer.request_author",
            AsyncMock(return_value=renewed_author),
        ) as request_author,
        patch(
            "custom_components.samstream.installer.request_distributor",
            AsyncMock(return_value=(renewed_distributor, b"")),
        ) as request_distributor,
    ):
        setup = await installer.async_obtain_samsung_certificates(
            hass, setup_entry, ACCOUNT
        )

    key = current.author.key.private_numbers()
    assert request_author.await_args.args[2].private_numbers() == key
    assert request_distributor.await_args.args[2].private_numbers() == key
    assert not setup.needs_renewal()
    assert ir.async_get(hass).async_get_issue(DOMAIN, EXPIRY_ISSUE) is None


async def test_bundled_version(hass: HomeAssistant, tmp_path: Path) -> None:
    package = tmp_path / "samstream.wgt"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("config.xml", '<widget version="0.2.0"></widget>')
    with patch.object(installer, "BUNDLED_PACKAGE", package):
        assert await installer.async_bundled_version(hass) == "0.2.0"
    with patch.object(installer, "BUNDLED_PACKAGE", tmp_path / "missing.wgt"):
        assert await installer.async_bundled_version(hass) is None


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()


@pytest.fixture
def signing(hass: HomeAssistant) -> None:
    """App signing is set up (certificates for the test TV)."""
    hass.async_create_task(async_save_signing(hass, setup_for([DUID])))


async def test_auto_update_installs_newer_app_once(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock, signing: None
) -> None:
    with patch(
        "custom_components.samstream.update.async_install_package",
        AsyncMock(side_effect=HomeAssistantError("TV busy")),
    ) as install:
        await _setup(hass, mock_entry, mock_tv, installed="0.0.1")
        await _poll(hass)
        await _poll(hass)
    # Tried once for 0.1.0; a failure leaves it to the update entity.
    install.assert_awaited_once()
    assert hass.states.get(UPDATE).state == "on"


async def test_auto_update_waits_while_samstream_is_on_screen(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock, signing: None
) -> None:
    mock_tv.foreground_app.return_value = replace(samstream("0.0.1"), visible=True)
    with patch(
        "custom_components.samstream.update.async_install_package", AsyncMock()
    ) as install:
        await _setup(hass, mock_entry, mock_tv, installed="0.0.1")
        await _poll(hass)
        install.assert_not_awaited()

        mock_tv.foreground_app.return_value = None
        await _poll(hass)
    install.assert_awaited_once()


@pytest.mark.parametrize(
    ("installed", "options"),
    [
        ("0.0.1", {"auto_update": False}),  # Switched off.
        ("0.1.0", {}),  # Up to date.
        ("0.2.0", {}),  # Newer than the bundle (dev build): never downgrade.
        (None, {}),  # Not installed: first installs stay manual.
    ],
)
@pytest.mark.usefixtures("signing")
async def test_auto_update_skipped(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    installed: str | None,
    options: dict,
) -> None:
    hass.config_entries.async_update_entry(mock_entry, options=options)
    with patch(
        "custom_components.samstream.update.async_install_package", AsyncMock()
    ) as install:
        await _setup(hass, mock_entry, mock_tv, installed=installed)
        await _poll(hass)
    install.assert_not_awaited()


async def test_auto_update_needs_signing(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    with patch(
        "custom_components.samstream.update.async_install_package", AsyncMock()
    ) as install:
        await _setup(hass, mock_entry, mock_tv, installed="0.0.1")
        await _poll(hass)
    install.assert_not_awaited()
