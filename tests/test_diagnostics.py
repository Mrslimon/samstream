"""Diagnostics download: useful state, no secrets."""

import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.samstream.const import CONF_TV_SECRET, DOMAIN
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
