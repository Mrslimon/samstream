"""Local control (OCF): options, the shared cloud, entities fed by the TV, issues."""

import socket
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosamstream import OcfError
from aiosamstream.ocf import (
    CloudDevice,
    OnboardResult,
    encode_credential,
    generate_identity,
)
from aiosamstream.ocf import state as ocf_state
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.config_flow import SamstreamOptionsFlow
from custom_components.samstream.const import (
    CONF_OCF,
    CONF_OCF_HOST,
    CONF_OCF_OWNER_PSK,
    CONF_OCF_PORT,
    CONF_OCF_TOKEN,
    DOMAIN,
    ISSUE_OCF_PORT,
)
from custom_components.samstream.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.samstream.ocf import CloudSettings, async_get_service

from .conftest import UUID

pytestmark = pytest.mark.enable_socket

TV = "x.com.samsung.tv."
TOKEN = "a-long-secret-access-token"
IDENTITY = generate_identity()

# Bodies the QN800C sent through the local cloud.
REPORT: dict[str, dict[str, Any]] = {
    ocf_state.CONTENT_INFO: {
        f"{TV}input": "webapp",
        f"{TV}title": "YouTube",
        f"{TV}subtitle": "111299001912",
    },
    ocf_state.INPUT_SOURCE: {
        f"{TV}supportedModes": [
            {f"{TV}name": "TV", f"{TV}id": "dtv"},
            {f"{TV}name": "HDMI 1", f"{TV}id": "HDMI1"},
        ],
        f"{TV}currentMode": "dtv",
    },
    ocf_state.PICTURE_MODE: {
        f"{TV}supportedModes": [
            {f"{TV}name": "FILMMAKER MODE", f"{TV}id": "modeFilmmakerMode"},
            {f"{TV}name": "أفلام", f"{TV}id": "modeMovie"},
        ],
        f"{TV}currentMode": "modeMovie",
    },
    ocf_state.CHANNEL: {f"{TV}channelNumber": "154", f"{TV}channelName": "Al-Majd3"},
    ocf_state.LIGHT_SENSOR: {"brightness.level": 1, "brightness.lux": 12},
    ocf_state.SOUND_DETECTION: {"x.com.samsung.vd.soundDetected": "noSound"},
    ocf_state.CAMERA: {"disableReason": "cameraDisconnect"},
    ocf_state.ENERGY: {"energySavingOperation": True},
    ocf_state.AUDIO: {"volume": 19, "mute": False},
}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
async def cloud_port(hass: HomeAssistant) -> AsyncIterator[int]:
    """Store a cloud on a free local port, as if set up before."""
    port = _free_port()
    service = async_get_service(hass)
    await service.store.async_save(
        CloudSettings(IDENTITY, port, "127.0.0.1").to_store()
    )
    yield port
    if service.cloud is not None:
        await service.cloud.stop()
        service.cloud = None


@pytest.fixture
async def ocf_entry(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    cloud_port: int,
) -> MockConfigEntry:
    """The paired TV with local control on."""
    hass.config_entries.async_update_entry(
        mock_entry,
        data={**mock_entry.data, CONF_OCF_TOKEN: TOKEN},
        options={CONF_OCF: True},
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry


def _entity(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{UUID}_{key}"
    )
    assert entity_id, key
    return entity_id


def _report(entry: MockConfigEntry, bodies: dict[str, dict[str, Any]]) -> CloudDevice:
    device = entry.runtime_data.coordinator.ocf_device
    assert device is not None
    for href, body in bodies.items():
        device._update(href, body)  # noqa: SLF001 - what a TV notification does
    return device


async def test_options_guided_onboarding(
    hass: HomeAssistant, setup_entry: MockConfigEntry, cloud_port: int
) -> None:
    """Walk the guided flow: intro -> settings -> connect bundle -> wait -> paired."""
    options = hass.config_entries.options
    result = await options.async_init(setup_entry.entry_id)
    assert "local_control" in result["menu_options"]
    result = await options.async_configure(
        result["flow_id"], {"next_step_id": "local_control"}
    )
    flow = result["flow_id"]
    assert result["type"] is FlowResultType.MENU
    assert "local_control_settings" in result["menu_options"]

    result = await options.async_configure(
        flow, {"next_step_id": "local_control_settings"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local_control_settings"
    base = {CONF_OCF_PORT: cloud_port, CONF_OCF_HOST: "127.0.0.1"}

    result = await options.async_configure(flow, {**base, CONF_OCF_TOKEN: "short"})
    assert result["errors"] == {CONF_OCF_TOKEN: "token_too_short"}
    result = await options.async_configure(
        flow,
        {
            **base,
            CONF_OCF_TOKEN: TOKEN,
            "import_cloud": {"cloud_uuid": "x", "ca_certificate": "y", "ca_key": "z"},
        },
    )
    assert result["errors"] == {"base": "invalid_cloud_identity"}

    # Valid settings: local control turns on, and HA (reaching the TV, mocked)
    # asks for the PIN.
    onboarded = OnboardResult(
        device_uuid=UUID,
        obt_uuid="5f3d8a21-1c7b-4e62-9a40-7e2b1d6c8f33",
        owner_psk_hex="ab" * 16,
        secure_port=40000,
    )
    with (
        patch(
            "custom_components.samstream.config_flow.discover",
            return_value=(40000, UUID),
        ),
        patch("custom_components.samstream.config_flow.trigger_pin"),
    ):
        result = await options.async_configure(flow, {**base, CONF_OCF_TOKEN: TOKEN})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local_control_pin"
    assert setup_entry.options[CONF_OCF] is True

    result = await options.async_configure(flow, {"pin": "nope"})
    assert result["errors"] == {"pin": "invalid_pin"}

    # The 8 digits: HA onboards (mocked) and the TV "dials in" -> paired -> created.
    progress = (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE)
    with (
        patch(
            "custom_components.samstream.config_flow.onboard_tv",
            return_value=onboarded,
        ) as onboard,
        patch.object(
            SamstreamOptionsFlow, "_await_dial_in", new=AsyncMock(return_value=True)
        ),
    ):
        result = await options.async_configure(flow, {"pin": "12345678"})
        while result["type"] in progress:
            await hass.async_block_till_done()
            result = await options.async_configure(flow)
        if result["type"] is FlowResultType.FORM:  # the paired screen
            assert result["step_id"] == "local_control_done"
            result = await options.async_configure(flow, {})
    onboard.assert_called_once()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.data[CONF_OCF_TOKEN] == TOKEN
    assert setup_entry.data[CONF_OCF_OWNER_PSK] == "ab" * 16
    assert setup_entry.options[CONF_OCF] is True
    assert async_get_service(hass).cloud is not None  # the reload started the cloud


async def test_options_onboarding_falls_back_to_lan(
    hass: HomeAssistant, setup_entry: MockConfigEntry, cloud_port: int
) -> None:
    """When HA cannot reach the TV, the connect step shows the LAN helper."""
    options = hass.config_entries.options
    result = await options.async_init(setup_entry.entry_id)
    result = await options.async_configure(
        result["flow_id"], {"next_step_id": "local_control"}
    )
    flow = result["flow_id"]
    result = await options.async_configure(
        flow, {"next_step_id": "local_control_settings"}
    )
    base = {CONF_OCF_PORT: cloud_port, CONF_OCF_HOST: "127.0.0.1"}
    with patch(
        "custom_components.samstream.config_flow.discover",
        side_effect=OcfError("unreachable"),
    ):
        result = await options.async_configure(flow, {**base, CONF_OCF_TOKEN: TOKEN})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local_control_connect_lan"
    assert result["description_placeholders"]["command"].startswith("uv run")

    # Pasting the credential the LAN tool printed lets HA release later.
    credential = encode_credential(
        OnboardResult(
            device_uuid=UUID,
            obt_uuid="5f3d8a21-1c7b-4e62-9a40-7e2b1d6c8f33",
            owner_psk_hex="ab" * 16,
            secure_port=40000,
        )
    )
    result = await options.async_configure(flow, {"credential": "YWJj"})
    assert result["errors"] == {"credential": "invalid_credential"}
    progress = (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE)
    with patch.object(
        SamstreamOptionsFlow, "_await_dial_in", new=AsyncMock(return_value=True)
    ):
        result = await options.async_configure(flow, {"credential": credential})
        while result["type"] in progress:
            await hass.async_block_till_done()
            result = await options.async_configure(flow)
        if result["type"] is FlowResultType.FORM:
            result = await options.async_configure(flow, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.data[CONF_OCF_OWNER_PSK] == "ab" * 16


async def test_options_release_hands_the_tv_back(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    """Turning local control off releases ownership and disables it."""
    hass.config_entries.async_update_entry(
        ocf_entry, data={**ocf_entry.data, CONF_OCF_OWNER_PSK: "cd" * 16}
    )
    options = hass.config_entries.options
    result = await options.async_init(ocf_entry.entry_id)
    result = await options.async_configure(
        result["flow_id"], {"next_step_id": "local_control"}
    )
    flow = result["flow_id"]
    assert "local_control_release" in result["menu_options"]
    result = await options.async_configure(
        flow, {"next_step_id": "local_control_release"}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.samstream.config_flow.release_tv"
    ) as release:
        result = await options.async_configure(flow, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    release.assert_called_once()
    await hass.async_block_till_done()
    assert ocf_entry.options[CONF_OCF] is False


async def test_entities_follow_the_tv(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    connected = _entity(hass, "binary_sensor", "local_control")
    assert hass.states.get(connected).state == "off"
    assert hass.states.get(_entity(hass, "select", "input_source")).state == (
        "unavailable"
    )

    _report(ocf_entry, REPORT)
    await hass.async_block_till_done()
    assert hass.states.get(connected).state == "on"
    inputs = hass.states.get(_entity(hass, "select", "input_source"))
    assert inputs.state == "TV"
    assert inputs.attributes["options"] == ["TV", "HDMI 1"]
    assert hass.states.get(_entity(hass, "select", "picture_mode")).state == "أفلام"
    assert hass.states.get(_entity(hass, "sensor", "ambient_light")).state == "12.0"
    assert hass.states.get(_entity(hass, "sensor", "sound_detected")).state == (
        "noSound"
    )
    assert hass.states.get(_entity(hass, "binary_sensor", "tv_camera")).state == "off"
    assert hass.states.get(_entity(hass, "binary_sensor", "energy_saving")).state == (
        "on"
    )
    # No battery reported: the sensor stays unavailable rather than wrong.
    assert hass.states.get(_entity(hass, "sensor", "remote_battery")).state == (
        "unavailable"
    )
    # The TV says an app is in front: the current app follows it, no channel.
    assert hass.states.get(_entity(hass, "sensor", "current_app")).state == "YouTube"
    assert hass.states.get(_entity(hass, "sensor", "channel")).state == "unknown"

    _report(ocf_entry, {ocf_state.CONTENT_INFO: {f"{TV}input": "dtv"}})
    await hass.async_block_till_done()
    channel = hass.states.get(_entity(hass, "sensor", "channel"))
    assert channel.state == "Al-Majd3"
    assert channel.attributes["number"] == "154"
    assert hass.states.get(_entity(hass, "sensor", "current_app")).state != "YouTube"


async def test_select_sends_the_id(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    _report(ocf_entry, REPORT)
    await hass.async_block_till_done()
    # 4.00 is what the TV answers even when it switches (protocol doc 14.7).
    with patch.object(CloudDevice, "post", AsyncMock(return_value=0x80)) as sent:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": _entity(hass, "select", "input_source"), "option": "HDMI 1"},
            blocking=True,
        )
    assert sent.await_args.args == (
        ocf_state.INPUT_SOURCE,
        {f"{TV}currentMode": "HDMI1"},
    )


async def test_port_in_use_raises_an_issue(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    cloud_port: int,
) -> None:
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", cloud_port))  # noqa: S104
        taken.listen()
        hass.config_entries.async_update_entry(
            mock_entry,
            data={**mock_entry.data, CONF_OCF_TOKEN: TOKEN},
            options={CONF_OCF: True},
        )
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_OCF_PORT)
    assert issue is not None
    assert issue.translation_key == "ocf_port_in_use"
    assert mock_entry.runtime_data.coordinator.ocf_device is None


async def test_docker_port_not_published(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    cloud_port: int,
) -> None:
    hass.config_entries.async_update_entry(
        mock_entry,
        data={**mock_entry.data, CONF_OCF_TOKEN: TOKEN},
        options={CONF_OCF: True},
    )
    with (
        patch(
            "custom_components.samstream.ocf.OcfService._async_reachable",
            AsyncMock(return_value=False),
        ),
        patch(
            "custom_components.samstream.ocf.async_get_system_info",
            AsyncMock(return_value={"installation_type": "Home Assistant Container"}),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_OCF_PORT)
    assert issue is not None
    assert issue.translation_key == "ocf_not_reachable_container"
    assert issue.translation_placeholders == {"port": str(cloud_port)}


async def test_diagnostics_hide_the_token(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    _report(ocf_entry, REPORT)
    diagnostics = await async_get_config_entry_diagnostics(hass, ocf_entry)
    assert diagnostics["entry"]["data"][CONF_OCF_TOKEN] == "**REDACTED**"
    assert TOKEN not in str(diagnostics)
    assert IDENTITY.ca_key_pem.decode() not in str(diagnostics)
    local = diagnostics["local_control"]
    assert local["listening"] is True
    assert local["state"]["input_source"] == "dtv"


async def test_unload_stops_the_cloud(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    service = async_get_service(hass)
    assert service.cloud is not None
    assert await hass.config_entries.async_unload(ocf_entry.entry_id)
    assert service.cloud is None
