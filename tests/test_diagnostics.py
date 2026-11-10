"""Diagnostics download: useful state, no secrets."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.const import CONF_TV_SECRET, CONF_VOICE_WEBHOOK, DOMAIN
from custom_components.samstream.tv_session import set_command


async def test_diagnostics_redact_secrets(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
) -> None:
    hass.config_entries.async_update_entry(
        setup_entry, data={**setup_entry.data, CONF_TV_SECRET: "s3cr3t-value"}
    )
    set_command(
        hass,
        setup_entry,
        {
            "action": "play",
            "stream": {"label": "Gate", "url": "ws://ha/s3cr3t-value/x"},
        },
    )
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)

    text = json.dumps(diagnostics)
    for secret in ("s3cr3t-value", setup_entry.data["mac"]):
        assert secret not in text
    assert diagnostics["entry"]["data"]["token"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["host"] == setup_entry.data["host"]
    assert diagnostics["tv"]["is_on"] is True
    assert diagnostics["tv"]["device_info"]["model_name"] == "QA65QN800CUXEG"
    assert diagnostics["apps"]["count"] == 2
    assert diagnostics["samstream_app"]["last_command"]["stream"]["label"] == "Gate"
    assert diagnostics["signing"] is None
    assert DOMAIN == "samstream"


async def test_diagnostics_redact_mjpeg_url_and_voice_webhook(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry: MockConfigEntry,
    mock_tv: MagicMock,
) -> None:
    """A camera played in a TV corner, and the voice webhook, must not leak."""
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, CONF_VOICE_WEBHOOK: "webhook-xyz"}
    )
    await hass.async_block_till_done()
    hass.states.async_set("camera.gate", "idle")
    with patch(
        "custom_components.samstream.media_player.async_get_stream_source",
        AsyncMock(return_value="rtsp://user:pass@192.168.1.6:554/ch1"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "play_stream",
            {
                "entity_id": "media_player.65_neo_qled_8k",
                "camera": "camera.gate",
                "tv_corner": "on",
            },
            blocking=True,
        )
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)

    text = json.dumps(diagnostics)
    secret = setup_entry.data[CONF_TV_SECRET]
    assert secret not in text
    assert "webhook-xyz" not in text
    assert "pass" not in text
    assert "mjpeg_url" in diagnostics["samstream_app"]["last_command"]["stream"]
