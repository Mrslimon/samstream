"""Local control (OCF): options, the shared cloud, entities fed by the TV, issues."""

import socket
import subprocess
import sys
import zipfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from aiosamstream import OcfError, OcfTvOwnedError
from aiosamstream.ocf import (
    CloudDevice,
    OnboardResult,
    encode_credential,
    generate_identity,
)
from aiosamstream.ocf import state as ocf_state
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samstream.config_flow import (
    SamstreamConfigFlow,
    SamstreamOptionsFlow,
)
from custom_components.samstream.const import (
    CONF_OCF,
    CONF_OCF_HOST,
    CONF_OCF_OWNER_PSK,
    CONF_OCF_PORT,
    CONF_OCF_TOKEN,
    CONF_OCF_WELCOME,
    DOMAIN,
    ISSUE_OCF_PORT,
)
from custom_components.samstream.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.samstream.ocf import CloudSettings, async_get_service
from custom_components.samstream.onboard_tool import (
    LAUNCHER_FILE,
    TOOL_FILE,
    async_offer,
    build_tool,
)

from .conftest import HOST, TV_INFO, UUID

# The `socket_enabled` fixture, not the `enable_socket` marker: HA's plugin
# re-disables sockets after the marker. The cloud listens on a real local port.
pytestmark = pytest.mark.usefixtures("socket_enabled")

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
async def cloud_port(
    hass: HomeAssistant,
    socket_enabled: None,  # before the port probe opens a socket
) -> AsyncIterator[int]:
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
    # The TV shows "Samstream is set up" once the app is there.
    assert setup_entry.data[CONF_OCF_WELCOME] is True


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
    placeholders = result["description_placeholders"]
    assert placeholders["tool_url"].startswith("/api/samstream/onboard/")
    assert placeholders["command"] == f"python3 {TOOL_FILE}"

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
    with patch("custom_components.samstream.config_flow.release_tv") as release:
        result = await options.async_configure(flow, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    release.assert_called_once()
    await hass.async_block_till_done()
    assert ocf_entry.options[CONF_OCF] is False


async def test_options_release_raises_an_issue_when_it_fails(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    """A release that fails still turns local control off, but is not silent."""
    hass.config_entries.async_update_entry(
        ocf_entry, data={**ocf_entry.data, CONF_OCF_OWNER_PSK: "cd" * 16}
    )
    options = hass.config_entries.options
    result = await options.async_init(ocf_entry.entry_id)
    result = await options.async_configure(
        result["flow_id"], {"next_step_id": "local_control"}
    )
    flow = result["flow_id"]
    result = await options.async_configure(
        flow, {"next_step_id": "local_control_release"}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.samstream.config_flow.release_tv",
        side_effect=OcfError("no reply"),
    ):
        result = await options.async_configure(flow, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert ocf_entry.options[CONF_OCF] is False
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"ocf_release_{ocf_entry.entry_id}"
    )
    assert issue is not None


async def test_removing_the_device_releases_the_tv_first(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    """Deleting the device hands the TV back before the entry is gone."""
    hass.config_entries.async_update_entry(
        ocf_entry, data={**ocf_entry.data, CONF_OCF_OWNER_PSK: "cd" * 16}
    )
    with patch("custom_components.samstream.release_tv") as release:
        assert await hass.config_entries.async_remove(ocf_entry.entry_id)
    release.assert_called_once()
    assert release.call_args.args[0] == HOST
    assert release.call_args.args[2] == "cd" * 16


async def test_removing_the_device_without_a_credential_skips_release(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    """A device never paired for local control has nothing to release."""
    with patch("custom_components.samstream.release_tv") as release:
        assert await hass.config_entries.async_remove(ocf_entry.entry_id)
    release.assert_not_called()


async def test_removing_the_device_raises_an_issue_when_release_fails(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    """A release that fails does not block removal, but it is not silent."""
    hass.config_entries.async_update_entry(
        ocf_entry, data={**ocf_entry.data, CONF_OCF_OWNER_PSK: "cd" * 16}
    )
    entry_id = ocf_entry.entry_id
    with patch(
        "custom_components.samstream.release_tv", side_effect=OcfError("no reply")
    ):
        assert await hass.config_entries.async_remove(entry_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"ocf_release_{entry_id}")
    assert issue is not None


@pytest.mark.parametrize(
    ("back", "step"),
    [(True, "local_control_reconnected"), (False, "local_control_trouble")],
)
async def test_options_reconnect_restarts_the_tv_service(
    hass: HomeAssistant,
    ocf_entry: MockConfigEntry,
    back: bool,  # noqa: FBT001
    step: str,
) -> None:
    options = hass.config_entries.options
    result = await options.async_init(ocf_entry.entry_id)
    flow = result["flow_id"]
    result = await options.async_configure(flow, {"next_step_id": "local_control"})
    assert "local_control_reconnect" in result["menu_options"]
    result = await options.async_configure(
        flow, {"next_step_id": "local_control_reconnect"}
    )
    assert result["type"] is FlowResultType.FORM  # "watch the TV, press Allow"
    restart = AsyncMock()
    with (
        patch("custom_components.samstream.config_flow.RESTART_SETTLE", 0),
        patch.object(CloudDevice, "restart_agent", restart),
        patch.object(
            CloudDevice, "wait_connected", AsyncMock(side_effect=[True, back])
        ),
    ):
        result = await options.async_configure(flow, {})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()
        result = await options.async_configure(flow)
    restart.assert_awaited_once()
    assert result["step_id"] == step
    if back:
        result = await options.async_configure(flow, {})
        assert result["type"] is FlowResultType.CREATE_ENTRY


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
    _report(
        ocf_entry,
        {
            ocf_state.ORIENTATION: {"orientation": 1},
            ocf_state.SHOW_MENU: {
                f"{TV}accessibility": [{"menuid": "grayscale", "value": "1"}]
            },
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(_entity(hass, "sensor", "screen_orientation")).state == (
        "landscape"
    )
    assert hass.states.get(_entity(hass, "binary_sensor", "grayscale")).state == "on"
    assert hass.states.get(_entity(hass, "binary_sensor", "voice_guide")).state == (
        "unavailable"
    )
    # Motion detection off and nothing reported: no motion sensor value yet.
    motion = _entity(hass, "binary_sensor", "motion")
    assert hass.states.get(motion).state == "unavailable"
    _report(
        ocf_entry,
        {
            ocf_state.SENSOR_STATES: {
                "x.com.samsung.vd.sensorType": [
                    {"name": "CameraMotion", "enabled": True}
                ]
            }
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(motion).state == "off"
    _report(ocf_entry, {ocf_state.MOTION: {"motion": "active"}})
    await hass.async_block_till_done()
    assert hass.states.get(motion).state == "on"
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

    # An app that is not in the installed list (the Frame's home: "Smart Hub")
    # is still a valid state, not an ENUM error.
    _report(
        ocf_entry,
        {
            ocf_state.CONTENT_INFO: {
                f"{TV}input": "webapp",
                f"{TV}title": "Smart Hub",
                f"{TV}subtitle": "com.samsung.tv.smarthub",
            }
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(_entity(hass, "sensor", "current_app")).state == "Smart Hub"


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


async def test_media_player_uses_what_the_tv_reports(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    player = _entity(hass, "media_player", "media_player")
    _report(ocf_entry, REPORT)
    await hass.async_block_till_done()
    state = hass.states.get(player)
    # An app in front: the app is the source, no channel.
    assert state.attributes["source"] == "YouTube"
    assert state.attributes["source_list"][:3] == ["Home", "TV", "HDMI 1"]
    assert "media_channel" not in state.attributes

    _report(
        ocf_entry,
        {ocf_state.CONTENT_INFO: {f"{TV}input": "dtv", f"{TV}title": "News at 9"}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(player)
    assert state.attributes["source"] == "TV"
    assert state.attributes["media_channel"] == "Al-Majd3"
    assert state.attributes["media_title"] == "News at 9"
    assert state.attributes["media_content_type"] == "channel"

    # Picking an input the TV listed switches it by id, not by a remote key.
    tv = ocf_entry.runtime_data.coordinator.tv
    with patch.object(CloudDevice, "post", AsyncMock(return_value=0x80)) as sent:
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": player, "source": "HDMI 1"},
            blocking=True,
        )
    assert sent.await_args.args == (
        ocf_state.INPUT_SOURCE,
        {f"{TV}currentMode": "HDMI1"},
    )
    tv.send_keys.assert_not_called()


async def test_local_control_request_reads_and_writes(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    player = _entity(hass, "media_player", "media_player")
    answer = AsyncMock(return_value=(0x45, {"orientation": 1, "raw": b""}))
    with (
        patch.object(CloudDevice, "wait_connected", AsyncMock(return_value=True)),
        patch.object(CloudDevice, "request", answer),
    ):
        got = await hass.services.async_call(
            DOMAIN,
            "local_control_request",
            {"entity_id": player, "method": "get", "resource": "/sec/tv/x"},
            blocking=True,
            return_response=True,
        )
        assert got[player] == {"code": "2.05", "body": {"orientation": 1, "raw": "01"}}
        await hass.services.async_call(
            DOMAIN,
            "local_control_request",
            {
                "entity_id": player,
                "method": "post",
                "resource": "/sec/tv/x",
                "body": {"a": 1},
            },
            blocking=True,
            return_response=True,
        )
    assert answer.await_args.args == (0x02, "/sec/tv/x", {"a": 1})

    # Not connected: a clear error, not a hang.
    with (
        patch("custom_components.samstream.media_player.RECONNECT_WAIT_SECONDS", 0.01),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN,
            "local_control_request",
            {"entity_id": player, "method": "get", "resource": "/sec/tv/x"},
            blocking=True,
            return_response=True,
        )


async def test_frame_art_mode_switch(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_tv: MagicMock,
    cloud_port: int,
) -> None:
    mock_tv.device_info = AsyncMock(return_value=replace(TV_INFO, frame_tv=True))
    mock_tv.toggle_art_mode = AsyncMock()
    hass.config_entries.async_update_entry(
        mock_entry,
        data={**mock_entry.data, CONF_OCF_TOKEN: TOKEN},
        options={CONF_OCF: True},
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    art = _entity(hass, "switch", "art_mode")
    hub = {f"{TV}input": "webapp", f"{TV}subtitle": "com.samsung.tv.csfs"}
    _report(mock_entry, {ocf_state.CONTENT_INFO: hub})
    await hass.async_block_till_done()
    assert hass.states.get(art).state == "off"

    with patch.object(CloudDevice, "post", AsyncMock(return_value=0x44)) as sent:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": art}, blocking=True
        )
    assert sent.await_args.args[0] == ocf_state.SWITCH_ART
    # Off when not in Art Mode does nothing (the power key would enter it).
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": art}, blocking=True
    )
    mock_tv.toggle_art_mode.assert_not_called()

    _report(
        mock_entry,
        {ocf_state.CONTENT_INFO: {**hub, f"{TV}subtitle": "art"}},
    )
    await hass.async_block_till_done()
    assert hass.states.get(art).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": art}, blocking=True
    )
    mock_tv.toggle_art_mode.assert_awaited_once()


async def test_no_art_mode_switch_on_other_tvs(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", DOMAIN, f"{UUID}_art_mode") is None


async def test_screen_buttons_press_keys(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity(hass, "button", "open_guide")},
        blocking=True,
    )
    mock_tv.send_keys.assert_awaited_with(["KEY_GUIDE"])


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

    # The raw dump holds the token the TV keeps for the cloud: never shown.
    dump = {
        "resources": {
            "/CoapCloudConfResURI": {"at": TOKEN, "x.com.samsung.refreshtoken": TOKEN},
            "/sec/tv/deviceinfo": {"x.com.samsung.tv.wifimac": "2c:99:75:be:33:bc"},
            "/DevConfResURI": {
                "x.com.samsung.account": "someone@example.com",
                "x.com.samsung.plainserial": "09HG3K4X700025",
            },
        }
    }
    with (
        patch.object(CloudDevice, "connected", PropertyMock(return_value=True)),
        patch.object(CloudDevice, "read_all", AsyncMock(return_value=dump)),
    ):
        diagnostics = await async_get_config_entry_diagnostics(hass, ocf_entry)
    raw = str(diagnostics["local_control"]["resources"])
    assert TOKEN not in raw
    assert "2c:99:75" not in raw
    assert "someone@example.com" not in raw
    assert "09HG3K4X700025" not in raw


async def test_unload_stops_the_cloud(
    hass: HomeAssistant, ocf_entry: MockConfigEntry
) -> None:
    service = async_get_service(hass)
    assert service.cloud is not None
    assert await hass.config_entries.async_unload(ocf_entry.entry_id)
    assert service.cloud is None


ONBOARDED = OnboardResult(
    device_uuid=UUID,
    obt_uuid="5f3d8a21-1c7b-4e62-9a40-7e2b1d6c8f33",
    owner_psk_hex="ab" * 16,
    secure_port=40000,
)
PROGRESS = (FlowResultType.SHOW_PROGRESS, FlowResultType.SHOW_PROGRESS_DONE)
FLOW = "custom_components.samstream.config_flow"


async def _to_local_offer(hass: HomeAssistant) -> str:
    """Add a TV up to the local-control offer; return the flow id."""
    flows = hass.config_entries.flow
    result = await flows.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow = result["flow_id"]
    result = await flows.async_configure(flow, {CONF_HOST: HOST})
    while result["type"] in PROGRESS:
        await hass.async_block_till_done()
        result = await flows.async_configure(flow)
    if result["step_id"] == "developer_mode":  # skipped when already enabled
        result = await flows.async_configure(flow, {})
    assert result["step_id"] == "local_offer"
    return flow


@pytest.fixture
def pairing_tv() -> Iterator[MagicMock]:
    """The client the config flow pairs with."""
    client = MagicMock()
    client.device_info = AsyncMock(return_value=TV_INFO)
    client.pair = AsyncMock(return_value="token-1")
    with patch(f"{FLOW}.SamsungTV", return_value=client):
        yield client


@pytest.mark.usefixtures("mock_tv", "pairing_tv", "cloud_port")
async def test_first_setup_includes_local_control(hass: HomeAssistant) -> None:
    """Ticking local control on a new TV: PIN -> paired -> entry adopts the TV."""
    flows = hass.config_entries.flow
    flow = await _to_local_offer(hass)
    with (
        patch(f"{FLOW}.discover", return_value=(40000, UUID)),
        patch(f"{FLOW}.trigger_pin") as trigger,
    ):
        result = await flows.async_configure(flow, {"set_up": True})
    trigger.assert_called_once_with(HOST)
    assert result["step_id"] == "local_control_pin"
    service = async_get_service(hass)
    assert service.cloud is not None  # listening for the TV before the entry exists
    assert flow in service.cloud.devices

    with (
        patch(f"{FLOW}.onboard_tv", return_value=ONBOARDED),
        patch.object(
            SamstreamConfigFlow, "_await_dial_in", new=AsyncMock(return_value=True)
        ),
    ):
        result = await flows.async_configure(flow, {"pin": "12345678"})
        while result["type"] in PROGRESS:
            await hass.async_block_till_done()
            result = await flows.async_configure(flow)
        assert result["step_id"] == "local_control_done"
        result = await flows.async_configure(flow, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.options == {CONF_OCF: True}
    assert entry.data[CONF_OCF_OWNER_PSK] == "ab" * 16
    assert len(entry.data[CONF_OCF_TOKEN]) >= 16
    assert entry.data[CONF_OCF_WELCOME] is True
    # The entry took over the device the flow held (and its connection).
    assert service.held == {}
    assert flow not in service.cloud.devices
    assert entry.runtime_data.coordinator.ocf_device is not None


@pytest.mark.usefixtures("mock_tv", "pairing_tv", "cloud_port")
async def test_first_setup_failure_offers_the_lan_helper(hass: HomeAssistant) -> None:
    """A refused onboarding offers retry / LAN helper / finish; abandoning frees."""
    flows = hass.config_entries.flow
    flow = await _to_local_offer(hass)
    with (
        patch(f"{FLOW}.discover", return_value=(40000, UUID)),
        patch(f"{FLOW}.trigger_pin"),
    ):
        await flows.async_configure(flow, {"set_up": True})
    with patch(f"{FLOW}.onboard_tv", side_effect=OcfError("no answer")):
        result = await flows.async_configure(flow, {"pin": "12345678"})
        while result["type"] in PROGRESS:
            await hass.async_block_till_done()
            result = await flows.async_configure(flow)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "local_control_failed"
    assert result["menu_options"] == [
        "local_control_connect",
        "local_control_lan",
        "local_control_skip",
    ]
    result = await flows.async_configure(flow, {"next_step_id": "local_control_lan"})
    assert result["step_id"] == "local_control_connect_lan"
    assert result["description_placeholders"]["launcher_url"].startswith(
        "/api/samstream/onboard/"
    )

    service = async_get_service(hass)
    flows.async_abort(flow)
    await hass.async_block_till_done()
    assert service.held == {}
    assert service.cloud is None  # nothing else wanted it


@pytest.mark.usefixtures("mock_tv", "pairing_tv", "cloud_port")
async def test_first_setup_unreachable_tv_uses_the_lan_helper(
    hass: HomeAssistant,
) -> None:
    """HA cannot find the TV: LAN helper; finishing anyway keeps local control."""
    flows = hass.config_entries.flow
    flow = await _to_local_offer(hass)
    # Unreachable surfaces at discovery (tried first); the PIN trigger never runs.
    with (
        patch(f"{FLOW}.trigger_pin", side_effect=OcfError("no answer")),
        patch(f"{FLOW}.discover", side_effect=OcfError("no answer")),
    ):
        result = await flows.async_configure(flow, {"set_up": True})
    assert result["step_id"] == "local_control_connect_lan"
    with patch.object(
        SamstreamConfigFlow, "_await_dial_in", new=AsyncMock(return_value=False)
    ):
        result = await flows.async_configure(flow, {})
        while result["type"] in PROGRESS:
            await hass.async_block_till_done()
            result = await flows.async_configure(flow)
    assert result["step_id"] == "local_control_trouble"
    result = await flows.async_configure(flow, {"next_step_id": "local_control_skip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options == {CONF_OCF: True}
    await hass.async_block_till_done()


@pytest.mark.usefixtures("mock_tv", "pairing_tv", "cloud_port")
async def test_first_setup_owned_tv_says_remove_it_from_smartthings(
    hass: HomeAssistant,
) -> None:
    """A TV still owned by SmartThings gets its own screen, not the LAN helper."""
    flows = hass.config_entries.flow
    flow = await _to_local_offer(hass)
    with (
        patch(f"{FLOW}.discover", return_value=(40000, UUID)),
        patch(f"{FLOW}.trigger_pin", side_effect=OcfTvOwnedError("owned")),
    ):
        result = await flows.async_configure(flow, {"set_up": True})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "local_control_owned"
    assert result["menu_options"] == ["local_control_connect", "local_control_skip"]
    with (
        patch(f"{FLOW}.discover", return_value=(40000, UUID)),
        patch(f"{FLOW}.trigger_pin") as trigger,
    ):
        result = await flows.async_configure(
            flow, {"next_step_id": "local_control_connect"}
        )
    trigger.assert_called_once_with(HOST)  # retrying asks for the PIN again
    assert result["step_id"] == "local_control_pin"


def test_helper_runs_without_the_library(tmp_path: Path) -> None:
    """The downloaded zip app imports only its own modules (no aiohttp etc.)."""
    tool = tmp_path / TOOL_FILE
    tool.write_bytes(build_tool(HOST, "YnVuZGxl"))
    with zipfile.ZipFile(tool) as archive:
        names = archive.namelist()
    assert "aiosamstream/ocf/onboard_cli.py" in names
    assert "aiosamstream/tv.py" not in names
    run = subprocess.run(  # noqa: S603 - our own interpreter and file
        [sys.executable, "-I", str(tool), "release", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert run.returncode == 0, run.stderr
    assert "--credential" in run.stdout


async def test_helper_download(
    hass: HomeAssistant, setup_entry: MockConfigEntry, hass_client: Any
) -> None:
    """The signed links serve the zip app and the Windows launcher."""
    links = async_offer(hass, HOST, "YnVuZGxl")
    client = await hass_client()
    tool = await client.get(links["tool_url"])
    assert tool.status == 200
    assert (await tool.read()).startswith(b"#!/usr/bin/env python3")
    launcher = await client.get(links["launcher_url"])
    assert TOOL_FILE in await launcher.text()
    assert LAUNCHER_FILE in launcher.headers["Content-Disposition"]
    missing = await client.get(f"/api/samstream/onboard/nope/{TOOL_FILE}")
    assert missing.status == 404
