"""Voice bridge: options step, webhook through Assist, event, reply on the TV."""

import dataclasses
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.const import (
    CONF_VOICE,
    CONF_VOICE_SHOW,
    CONF_VOICE_WEBHOOK,
    EVENT_VOICE,
)

WEBHOOK = "voicewebhook0123"
SHOW = (
    "custom_components.samstream.media_player.SamstreamMediaPlayer.async_show_message"
)


@pytest.fixture
def converse() -> Generator[AsyncMock]:
    result = SimpleNamespace(
        response=SimpleNamespace(
            speech={"plain": {"speech": "Turned on the kitchen lights"}}
        ),
        conversation_id="conv-1",
    )
    with patch(
        "custom_components.samstream.voice.async_converse",
        AsyncMock(return_value=result),
    ) as mock:
        yield mock


@pytest.fixture
async def voice_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_tv: MagicMock
) -> MockConfigEntry:
    hass.config_entries.async_update_entry(
        mock_entry,
        options={CONF_VOICE: True, CONF_VOICE_SHOW: True, CONF_VOICE_WEBHOOK: WEBHOOK},
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry


async def test_options_step_keeps_one_address(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert "voice_bridge" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "voice_bridge"}
    )
    assert result["type"] is FlowResultType.FORM
    assert "/api/webhook/" in result["description_placeholders"]["url"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_VOICE: True, CONF_VOICE_SHOW: False}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    webhook_id = setup_entry.options[CONF_VOICE_WEBHOOK]
    assert len(webhook_id) == 64
    assert setup_entry.options[CONF_VOICE] is True

    # Turning it off and on again keeps the same address.
    for enabled in (False, True):
        result = await hass.config_entries.options.async_init(setup_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "voice_bridge"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_VOICE: enabled, CONF_VOICE_SHOW: True}
        )
        await hass.async_block_till_done()
    assert setup_entry.options[CONF_VOICE_WEBHOOK] == webhook_id


async def test_text_goes_through_assist(
    hass: HomeAssistant,
    voice_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    converse: AsyncMock,
) -> None:
    events = async_capture_events(hass, EVENT_VOICE)
    client = await hass_client_no_auth()
    with patch(SHOW, AsyncMock()) as call:
        response = await client.post(
            f"/api/webhook/{WEBHOOK}",
            json={"text": "turn on the kitchen lights", "language": "en"},
        )
        assert response.status == 200
        assert await response.json() == {
            "speech": "Turned on the kitchen lights",
            "conversation_id": "conv-1",
        }
    args = converse.await_args
    assert args.args[1] == "turn on the kitchen lights"
    assert args.kwargs["language"] == "en"
    assert args.kwargs["device_id"] is not None
    assert events[0].data["text"] == "turn on the kitchen lights"
    kwargs = call.await_args.kwargs
    assert kwargs["message"] == "Turned on the kitchen lights"
    assert kwargs["title"] == "turn on the kitchen lights"


async def test_form_fields_and_no_reply_when_off(
    hass: HomeAssistant,
    voice_entry: MockConfigEntry,
    mock_tv: MagicMock,
    hass_client_no_auth: ClientSessionGenerator,
    converse: AsyncMock,
) -> None:
    coordinator = voice_entry.runtime_data.coordinator
    coordinator.data = dataclasses.replace(coordinator.data, is_on=False)
    client = await hass_client_no_auth()
    with patch(SHOW, AsyncMock()) as call:
        response = await client.post(
            f"/api/webhook/{WEBHOOK}", data={"text": "what time is it"}
        )
    assert response.status == 200
    assert converse.await_args.args[1] == "what time is it"
    call.assert_not_awaited()


async def test_empty_text_is_rejected(
    hass: HomeAssistant,
    voice_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    converse: AsyncMock,
) -> None:
    client = await hass_client_no_auth()
    response = await client.post(f"/api/webhook/{WEBHOOK}", json={"text": " "})
    assert response.status == 400
    converse.assert_not_awaited()


async def test_off_means_no_webhook(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    converse: AsyncMock,
) -> None:
    client = await hass_client_no_auth()
    response = await client.post(f"/api/webhook/{WEBHOOK}", json={"text": "hi"})
    assert response.status == 200  # HA answers unknown webhooks with 200, unhandled.
    converse.assert_not_awaited()
