"""The "Samstream is set up" screen on the TV once local control is connected.

The flow only marks the entry (`CONF_OCF_WELCOME`): on first setup the
Samstream TV app is installed after local control, so the screen waits until
the TV is on and the app is there, then shows once.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiosamstream import SAMSTREAM_APP_ID
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import CONF_OCF_WELCOME, DOMAIN

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

# Long enough to read, then the TV goes back to what was on.
WELCOME_SECONDS = 10
_TEXT = {
    "en": (
        "Samstream is set up",
        "Home Assistant can now control this TV.",
    ),
    "ar": (
        "تم إعداد Samstream",
        "يمكن لـ Home Assistant الآن التحكم في هذا التلفاز.",
    ),
}


@callback
def async_setup_welcome(hass: HomeAssistant, entry: SamstreamConfigEntry) -> None:
    """Show the welcome screen as soon as the entry asks for it and the TV can."""
    coordinator = entry.runtime_data.coordinator

    @callback
    def _check() -> None:
        data = coordinator.data
        if (
            not entry.data.get(CONF_OCF_WELCOME)
            or data is None
            or not data.is_on
            or SAMSTREAM_APP_ID not in coordinator.apps
        ):
            return
        # Once only, even if the TV is busy: a missed welcome is not worth a retry.
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k != CONF_OCF_WELCOME},
        )
        entry.async_create_background_task(
            hass, _async_show(hass, entry), "samstream welcome"
        )

    entry.async_on_unload(coordinator.async_add_listener(_check))
    _check()


async def _async_show(hass: HomeAssistant, entry: SamstreamConfigEntry) -> None:
    unique_id = f"{entry.unique_id or entry.entry_id}_media_player"
    entity_id = er.async_get(hass).async_get_entity_id(
        MEDIA_PLAYER_DOMAIN, DOMAIN, unique_id
    )
    if entity_id is None:
        return
    title, message = _TEXT["ar" if hass.config.language.startswith("ar") else "en"]
    try:
        await hass.services.async_call(
            DOMAIN,
            "show_message",
            {
                "entity_id": entity_id,
                "title": title,
                "message": message,
                "severity": "success",
                "duration": WELCOME_SECONDS,
                "return_to_previous": True,
            },
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.debug("Welcome screen not shown on %s: %s", entity_id, err)
