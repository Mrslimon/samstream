"""TV notifications: `notify.send_message` shows the message on the TV screen.

Uses the same path as the `show_message` action (the Samstream TV app over what
is playing), shown for a short while, then the TV goes back to what was on.
"""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.components.notify.const import NotifyEntityFeature
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SamstreamConfigEntry
from .const import DOMAIN
from .coordinator import SamstreamCoordinator
from .entity import SamstreamEntity
from .notifier import async_post_native
from .tv_settings import ensure_tv_secret

PARALLEL_UPDATES = 1
NOTICE_SECONDS = 10.0
# Don't repeat a byte-identical message while its notice could still be on screen:
# a flood of the same "motion detected" collapses to one, distinct events still get
# through, and the same text sent again after the window shows again.
DEDUP_SECONDS = NOTICE_SECONDS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the TV's notify entity."""
    async_add_entities([SamstreamNotify(entry.runtime_data.coordinator)])


class SamstreamNotify(SamstreamEntity, NotifyEntity):
    """Show a notification on the TV, then return to what was playing."""

    _attr_translation_key = "notifications"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, coordinator: SamstreamCoordinator) -> None:
        """Create the notify entity for the coordinator's TV."""
        super().__init__(coordinator, "notify")
        self._last: tuple[str, str] | None = None
        self._last_at = 0.0

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Post a native TV notification; fall back to the on-screen notice.

        The native notifier (the sideloaded .NET app) overlays a real Samsung
        notification with a chime over whatever is playing, without interrupting
        it. When it is not installed or not reachable, show the message on the
        Samstream app instead, which briefly takes the screen and returns.

        A byte-identical message repeated within `DEDUP_SECONDS` is dropped, so an
        automation firing on every motion frame does not flood the screen.
        """
        signature = (title or "", message)
        now = self.hass.loop.time()
        if signature == self._last and now - self._last_at < DEDUP_SECONDS:
            return
        self._last, self._last_at = signature, now

        entry = self.coordinator.config_entry
        host = entry.data.get(CONF_HOST)
        if host:
            secret = ensure_tv_secret(self.hass, entry)
            if await async_post_native(
                self.hass, host, secret, title or "Samstream", message
            ):
                return

        player = er.async_get(self.hass).async_get_entity_id(
            "media_player", DOMAIN, f"{entry.unique_id or entry.entry_id}_media_player"
        )
        if player is None:  # pragma: no cover - the media player is always added
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": "no media player"},
            )
        await self.hass.services.async_call(
            DOMAIN,
            "show_message",
            {
                "entity_id": player,
                "message": message,
                "title": title or "",
                "duration": NOTICE_SECONDS,
            },
            blocking=True,
        )
