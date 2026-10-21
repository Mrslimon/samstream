"""Media player, remote and diagnostic entities driving the mocked TV."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiosamstream import SamstreamAuthError, SamstreamConnectionError
from homeassistant.components.media_player import (
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
)
from homeassistant.components.remote import ATTR_COMMAND, ATTR_NUM_REPEATS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.samstream.const import DOMAIN
from custom_components.samstream.coordinator import default_wol_target
from custom_components.samstream.remote import normalize_key

from .conftest import MAC, TV_INFO

TV = "media_player.65_neo_qled_8k"
REMOTE = "remote.65_neo_qled_8k_remote"
DEV_MODE = "binary_sensor.65_neo_qled_8k_developer_mode"
DEV_HOST = "sensor.65_neo_qled_8k_developer_host"


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "setup_entry")
async def test_states_when_on(hass: HomeAssistant) -> None:
    tv = hass.states.get(TV)
    assert tv.state == "on"
    assert tv.attributes["volume_level"] == 0.38
    assert tv.attributes["is_volume_muted"] is False
    assert tv.attributes["device_class"] == "tv"
    assert hass.states.get(REMOTE).state == "on"
    assert hass.states.get(DEV_MODE).state == "on"
    assert hass.states.get(DEV_HOST).state == "192.168.1.5"


@pytest.mark.usefixtures("setup_entry")
async def test_standby_then_unreachable(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.device_info.return_value = replace(TV_INFO, power_on=False)
    await _poll(hass)

    assert hass.states.get(TV).state == "off"
    assert "volume_level" not in hass.states.get(TV).attributes
    assert hass.states.get(REMOTE).state == "off"
    mock_tv.close.assert_awaited_once()

    mock_tv.device_info.side_effect = SamstreamConnectionError("gone")
    await _poll(hass)

    assert hass.states.get(TV).state == "off"
    # Last known info is kept, so the diagnostics stay readable.
    assert hass.states.get(DEV_MODE).state == "on"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_unknown_info_makes_diagnostics_unavailable(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    mock_tv.device_info.side_effect = SamstreamConnectionError("off")
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(DEV_MODE).state == "unavailable"
    assert hass.states.get(DEV_HOST).state == "unavailable"


@pytest.mark.usefixtures("setup_entry")
async def test_volume_through_upnp(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {ATTR_ENTITY_ID: TV, ATTR_MEDIA_VOLUME_LEVEL: 0.55},
        blocking=True,
    )
    mock_tv.rendering.set_volume.assert_awaited_once_with(55)
    assert hass.states.get(TV).attributes["volume_level"] == 0.55

    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {ATTR_ENTITY_ID: TV, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    mock_tv.rendering.set_mute.assert_awaited_once_with(mute=True)
    assert hass.states.get(TV).attributes["is_volume_muted"] is True


@pytest.mark.parametrize(
    ("service", "key"),
    [
        ("volume_up", "KEY_VOLUP"),
        ("volume_down", "KEY_VOLDOWN"),
        ("media_play", "KEY_PLAY"),
        ("media_pause", "KEY_PAUSE"),
        ("media_stop", "KEY_STOP"),
    ],
)
@pytest.mark.usefixtures("setup_entry")
async def test_key_services(
    hass: HomeAssistant, mock_tv: MagicMock, service: str, key: str
) -> None:
    await hass.services.async_call(
        "media_player", service, {ATTR_ENTITY_ID: TV}, blocking=True
    )
    mock_tv.send_keys.assert_awaited_once_with([key])


@pytest.mark.usefixtures("setup_entry")
async def test_play_pause_toggles(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    async def toggle() -> str:
        await hass.services.async_call(
            "media_player", "media_play_pause", {ATTR_ENTITY_ID: TV}, blocking=True
        )
        return mock_tv.send_keys.await_args.args[0][0]

    assert [await toggle(), await toggle(), await toggle()] == [
        "KEY_PAUSE",
        "KEY_PLAY",
        "KEY_PAUSE",
    ]
    # Another app on screen since the pause: it is playing, so pause it.
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator
    coordinator.async_set_updated_data(
        replace(coordinator.data, app_id="3201907018807")
    )
    assert await toggle() == "KEY_PAUSE"
    assert await toggle() == "KEY_PLAY"


@pytest.mark.parametrize("entity_id", [TV, REMOTE])
@pytest.mark.usefixtures("setup_entry")
async def test_power(hass: HomeAssistant, mock_tv: MagicMock, entity_id: str) -> None:
    domain = entity_id.split(".", maxsplit=1)[0]
    await hass.services.async_call(
        domain, "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_tv.power_on.assert_awaited_once_with(MAC, "192.168.1.255")

    await hass.services.async_call(
        domain, "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_tv.power_off.assert_awaited_once()


@pytest.mark.usefixtures("setup_entry")
async def test_turn_off_is_optimistic(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "media_player", "turn_off", {ATTR_ENTITY_ID: TV}, blocking=True
    )
    assert hass.states.get(TV).state == "off"


@pytest.mark.usefixtures("setup_entry")
async def test_remote_send_command(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    await hass.services.async_call(
        "remote",
        "send_command",
        {
            ATTR_ENTITY_ID: REMOTE,
            ATTR_COMMAND: ["home", "KEY_VOLUP"],
            ATTR_NUM_REPEATS: 2,
        },
        blocking=True,
    )
    mock_tv.send_keys.assert_awaited_once_with(
        ["KEY_HOME", "KEY_VOLUP"], repeats=2, delay=0.4, hold=0
    )


@pytest.mark.usefixtures("setup_entry")
async def test_action_error_is_translated(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.send_keys.side_effect = SamstreamConnectionError("refused")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "media_player", "media_play", {ATTR_ENTITY_ID: TV}, blocking=True
        )
    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders == {"error": "refused"}


async def test_revoked_token_starts_reauth(
    hass: HomeAssistant, setup_entry: MockConfigEntry, mock_tv: MagicMock
) -> None:
    mock_tv.send_keys.side_effect = SamstreamAuthError("revoked")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "media_player", "media_play", {ATTR_ENTITY_ID: TV}, blocking=True
        )
    assert err.value.translation_key == "auth_failed"
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.usefixtures("setup_entry")
async def test_volume_unknown_when_upnp_fails(
    hass: HomeAssistant, mock_tv: MagicMock
) -> None:
    mock_tv.rendering.get_volume.side_effect = SamstreamConnectionError("no upnp")
    await _poll(hass)

    tv = hass.states.get(TV)
    assert tv.state == "on"
    assert "volume_level" not in tv.attributes


def test_normalize_key() -> None:
    assert normalize_key(" home ") == "KEY_HOME"
    assert normalize_key("key_volup") == "KEY_VOLUP"
    assert normalize_key("KEY_POWER") == "KEY_POWER"


def test_default_wol_target() -> None:
    assert default_wol_target("192.168.1.11") == "192.168.1.255"
    assert default_wol_target("tv.local") == "255.255.255.255"


@pytest.mark.usefixtures("setup_entry")
async def test_text_hold_and_pointer(hass: HomeAssistant, mock_tv: MagicMock) -> None:
    mock_tv.send_text = AsyncMock()
    mock_tv.move_pointer = AsyncMock()
    mock_tv.click = AsyncMock()

    await hass.services.async_call(
        DOMAIN, "send_text", {ATTR_ENTITY_ID: TV, "text": "مرحبا"}, blocking=True
    )
    mock_tv.send_text.assert_awaited_once_with("مرحبا", done=True)

    await hass.services.async_call(
        DOMAIN, "hold_key", {ATTR_ENTITY_ID: TV, "key": "enter"}, blocking=True
    )
    mock_tv.send_keys.assert_awaited_once_with(["KEY_ENTER"], hold=1.5)

    await hass.services.async_call(
        DOMAIN,
        "pointer",
        {ATTR_ENTITY_ID: TV, "move_x": 30, "move_y": -10, "click": "right"},
        blocking=True,
    )
    mock_tv.move_pointer.assert_awaited_once_with(30, -10)
    mock_tv.click.assert_awaited_once_with("right")

    await hass.services.async_call(
        DOMAIN, "pointer", {ATTR_ENTITY_ID: TV, "click": "left"}, blocking=True
    )
    assert mock_tv.move_pointer.await_count == 1


@pytest.mark.usefixtures("setup_entry")
async def test_developer_host_disabled_by_default(hass: HomeAssistant) -> None:
    entry = er.async_get(hass).async_get(DEV_HOST)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(DEV_HOST) is None
