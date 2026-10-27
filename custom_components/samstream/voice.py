"""Voice bridge: text said to Bixby, Alexa or the TV app, run through HA Assist.

Each TV gets its own webhook (Configure > Voice bridge). Whatever calls it (a
Bixby capsule on the phone, the Samstream TV app's voice screen, a script)
posts `{"text": "turn on the kitchen lights"}`; HA Assist handles it with the
TV's device (so its area) as context, a `samstream_voice` event lets
automations react to any phrase, and the answer comes back as `{"speech": ...}`
and, when set, as a message on that TV.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.components.conversation import async_converse
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError

from .const import (
    CONF_VOICE,
    CONF_VOICE_SHOW,
    CONF_VOICE_WEBHOOK,
    DOMAIN,
    EVENT_VOICE,
    VOICE_REPLY_SECONDS,
)

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)
_MAX_TEXT = 500


def voice_webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """Full URL of a voice webhook (prefers the external one), or its path."""
    try:
        return webhook.async_generate_url(hass, webhook_id)
    except NoURLAvailableError:
        return webhook.async_generate_path(webhook_id)


def async_setup_voice(hass: HomeAssistant, entry: SamstreamConfigEntry) -> None:
    """Register this TV's voice webhook when the bridge is on."""
    webhook_id = entry.options.get(CONF_VOICE_WEBHOOK)
    if not entry.options.get(CONF_VOICE) or not webhook_id:
        return

    async def _handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        return await _async_handle(hass, entry, request)

    webhook.async_register(
        hass,
        DOMAIN,
        f"{entry.title} voice",
        webhook_id,
        _handle,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))


async def _request_fields(request: web.Request) -> dict[str, Any]:
    """JSON body, else form fields, else the query string."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        return body
    form = await request.post()
    if form:
        return dict(form)
    return dict(request.query)


async def _async_handle(
    hass: HomeAssistant, entry: SamstreamConfigEntry, request: web.Request
) -> web.Response:
    fields = await _request_fields(request)
    text = str(fields.get("text") or "").strip()[:_MAX_TEXT]
    if not text:
        return web.json_response({"error": "no text"}, status=400)
    language = fields.get("language") or None
    conversation_id = fields.get("conversation_id") or None

    # The entry's own TV device (identifier lookups changed in 2026.10).
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    device_id = devices[0].id if devices else None
    hass.bus.async_fire(
        EVENT_VOICE, {"text": text, "device_id": device_id, "entry_id": entry.entry_id}
    )
    result = await async_converse(
        hass,
        text,
        str(conversation_id) if conversation_id else None,
        Context(),
        language=str(language) if language else None,
        device_id=device_id,
    )
    speech = result.response.speech.get("plain", {}).get("speech", "")
    if speech and entry.options.get(CONF_VOICE_SHOW, True):
        await _async_show_reply(hass, entry, text, speech)
    return web.json_response(
        {"speech": speech, "conversation_id": result.conversation_id}
    )


async def _async_show_reply(
    hass: HomeAssistant, entry: SamstreamConfigEntry, text: str, speech: str
) -> None:
    """Show Assist's answer on this TV, only while it is on (never wakes it)."""
    if not entry.runtime_data.coordinator.data.is_on:
        return
    unique_id = f"{entry.unique_id or entry.entry_id}_media_player"
    entity_id = er.async_get(hass).async_get_entity_id(
        "media_player", DOMAIN, unique_id
    )
    if entity_id is None:
        return
    try:
        await hass.services.async_call(
            DOMAIN,
            "show_message",
            {
                "entity_id": entity_id,
                "title": text,
                "message": speech,
                "duration": VOICE_REPLY_SECONDS,
            },
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.debug("Could not show the voice reply on %s: %s", entity_id, err)
