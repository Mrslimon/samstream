"""Fixtures for Samstream integration tests (need the `ha` dependency group)."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import AppStatus, DeviceInfo
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import CONF_TOKEN, DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]

UUID = "00000000-0000-0000-0000-000000000002"
HOST = "192.168.1.11"
MAC = "aa:bb:cc:00:11:22"
TV_INFO = DeviceInfo(
    uuid=UUID,
    name='65" Neo QLED 8K',
    model_name="QA65QN800CUXEG",
    model_code="23_OSCP_8K_T09",
    year=2023,
    os="Tizen",
    firmware=None,
    mac=MAC,
    ip=HOST,
    network_type="wireless",
    power_on=True,
    developer_mode=True,
    developer_ip="192.168.1.5",
    token_auth=True,
    resolution="7680x4320",
)


YOUTUBE = AppStatus("111299001912", "YouTube", True, False, "2.1.527")
NETFLIX = AppStatus("3201907018807", "Netflix", True, False, "80.24.16020")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components in every test."""


@pytest.fixture
def mock_tv() -> Generator[MagicMock]:
    """The library client used by the integration (not the config flow)."""
    tv = MagicMock()
    tv.token = "token"
    tv.device_info = AsyncMock(return_value=TV_INFO)
    tv.send_keys = AsyncMock()
    tv.power_on = AsyncMock()
    tv.power_off = AsyncMock()
    tv.close = AsyncMock()
    tv.rendering.get_volume = AsyncMock(return_value=38)
    tv.rendering.get_mute = AsyncMock(return_value=False)
    tv.rendering.set_volume = AsyncMock()
    tv.rendering.set_mute = AsyncMock()
    tv.installed_apps = AsyncMock(return_value=[YOUTUBE, NETFLIX])
    tv.foreground_app = AsyncMock(return_value=None)
    tv.launch_app = AsyncMock()
    tv.close_app = AsyncMock()
    tv.app_status = AsyncMock(return_value=None)
    # No sdb in tests by default: the coordinator falls back to the catalog.
    with (
        patch("custom_components.samstream.SamsungTV", return_value=tv),
        patch(
            "custom_components.samstream.coordinator.async_list_apps",
            AsyncMock(return_value=None),
        ) as list_apps,
    ):
        tv.list_apps = list_apps
        yield tv


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A paired TV."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UUID,
        title=TV_INFO.name,
        data={
            CONF_HOST: HOST,
            CONF_TOKEN: "token",
            CONF_MAC: MAC,
            CONF_MODEL: TV_INFO.model_name,
            CONF_NAME: TV_INFO.name,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> MockConfigEntry:
    """Set up the integration with the mocked TV."""
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
