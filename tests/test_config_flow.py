"""Config flow: find the TV, pair once, reauth and reconfigure."""

import asyncio
from collections.abc import Generator
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import (
    DeviceInfo,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
)
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.const import CONF_TOKEN, DOMAIN

HOST = "192.168.1.11"
UUID = "00000000-0000-0000-0000-000000000002"
INFO = DeviceInfo(
    uuid=UUID,
    name='65" Neo QLED 8K',
    model_name="QA65QN800CUXEG",
    model_code="23_OSCP_8K_T09",
    year=2023,
    os="Tizen",
    firmware=None,
    mac="aa:bb:cc:00:11:22",
    ip=HOST,
    network_type="wireless",
    power_on=True,
    developer_mode=True,
    developer_ip="192.168.1.5",
    token_auth=True,
    resolution="7680x4320",
)


@pytest.fixture(autouse=True)
def _no_real_tv(mock_tv: MagicMock) -> None:
    """Entries created or reloaded here set up the integration; keep it offline."""


@pytest.fixture
def tv() -> Generator[MagicMock]:
    """Patch the library client used by the flow."""
    client = MagicMock()
    client.device_info = AsyncMock(return_value=INFO)
    client.pair = AsyncMock(return_value="token-1")
    with patch(
        "custom_components.samstream.config_flow.SamsungTV", return_value=client
    ):
        yield client


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """An already paired TV."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UUID,
        title=INFO.name,
        data={
            CONF_HOST: HOST,
            CONF_TOKEN: "old-token",
            CONF_MAC: INFO.mac,
            CONF_MODEL: INFO.model_name,
            CONF_NAME: INFO.name,
        },
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def _finish_pairing(hass: HomeAssistant, result: dict) -> dict:
    """Let the pairing task run; HA may or may not stop on the progress screen."""
    progress = (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE)
    while result["type"] in progress:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def test_user_flow_pairs_and_creates_entry(
    hass: HomeAssistant, tv: MagicMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {HOST} "}
    )
    result = await _finish_pairing(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == '65" Neo QLED 8K'
    assert result["result"].unique_id == UUID
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_TOKEN: "token-1",
        CONF_MAC: "aa:bb:cc:00:11:22",
        CONF_MODEL: "QA65QN800CUXEG",
        CONF_NAME: '65" Neo QLED 8K',
    }


async def test_progress_screen_while_waiting_for_allow(
    hass: HomeAssistant, tv: MagicMock
) -> None:
    allowed = asyncio.Event()

    async def pair() -> str:
        await allowed.wait()
        return "token-1"

    tv.pair.side_effect = pair
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "wait_for_allow"
    assert result["description_placeholders"] == {"name": INFO.name}

    allowed.set()
    result = await _finish_pairing(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("error", "key"),
    [(SamstreamConnectionError("down"), "cannot_connect"), (ValueError, "unknown")],
)
async def test_user_flow_tv_unreachable(
    hass: HomeAssistant, tv: MagicMock, error: Exception, key: str
) -> None:
    tv.device_info.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SamstreamAuthError("denied"), "pairing_denied"),
        (SamstreamTimeoutError("slow"), "pairing_timeout"),
        (SamstreamConnectionError("gone"), "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_pairing_failure_then_retry(
    hass: HomeAssistant, tv: MagicMock, error: Exception, key: str
) -> None:
    tv.pair.side_effect = [error, "token-2"]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    result = await _finish_pairing(hass, result)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair_failed"
    assert result["errors"] == {"base": key}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish_pairing(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TOKEN] == "token-2"


async def test_same_tv_new_address_updates_entry(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.99"
    tv.pair.assert_not_called()


async def test_reauth_stores_new_token(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"] == {"name": INFO.name}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish_pairing(hass, result)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "token-1"
    # The update reloads the entry in the background; let it finish, then stop
    # its polling timer.
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_moves_host(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.1.50"
    assert entry.data[CONF_TOKEN] == "old-token"
    # The update reloads the entry in the background; let it finish, then stop
    # its polling timer.
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_rejects_other_tv(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    tv.device_info.return_value = replace(INFO, uuid="other")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.60"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_unreachable(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    tv.device_info.side_effect = SamstreamConnectionError("down")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.60"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


def _ssdp(location: str | None = f"http://{HOST}:9197/dmr") -> SsdpServiceInfo:
    return SsdpServiceInfo(
        ssdp_usn=f"uuid:{UUID}::urn:samsung.com:device:RemoteControlReceiver:1",
        ssdp_st="urn:samsung.com:device:RemoteControlReceiver:1",
        ssdp_location=location,
        upnp={"manufacturer": "Samsung Electronics"},
    )


async def test_discovered_tv_is_confirmed_then_paired(
    hass: HomeAssistant, tv: MagicMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=_ssdp()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"]["model"] == "QA65QN800CUXEG"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish_pairing(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == UUID
    assert result["data"][CONF_HOST] == HOST


async def test_discovery_moves_a_known_tv(
    hass: HomeAssistant, tv: MagicMock, entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=_ssdp("http://192.168.1.77:9197/dmr"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.77"


@pytest.mark.parametrize("location", [None, "http://192.168.1.50:9197/dmr"])
async def test_discovery_of_unsupported_tv(
    hass: HomeAssistant, tv: MagicMock, location: str | None
) -> None:
    tv.device_info.side_effect = SamstreamConnectionError("no API")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_SSDP}, data=_ssdp(location)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"
