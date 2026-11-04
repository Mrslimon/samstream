"""The Samstream integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from aiosamstream import OcfError, SamsungTV
from aiosamstream.ocf import release_tv
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, VolDictType

from .app_signing import async_check_certificate_expiry
from .art_gallery import (
    CONTENT_ID,
    MATTE,
    SamstreamArtThumbnailView,
    SamstreamArtUploadView,
)
from .art_gallery import forget as forget_art_gallery
from .const import (
    ATTR_APP_ID,
    ATTR_PATH,
    CERT_CHECK_INTERVAL,
    CONF_OCF_OWNER_PSK,
    CONF_OCF_SECURE_PORT,
    CONF_TOKEN,
    DOMAIN,
    ISSUE_OCF_RELEASE,
    TV_CORNERS,
)
from .coordinator import SamstreamCoordinator
from .frontend import async_setup_frontend
from .installer import async_bundled_version
from .ocf import async_get_service as async_get_ocf_service
from .onboard_tool import SamstreamOnboardToolView
from .signin import SamstreamSignInView
from .stream_relay import SamstreamMjpegView, SamstreamStreamView
from .tv_session import SamstreamTvSessionView
from .tv_settings import SamstreamTvSettingsView
from .validation import vol
from .voice import async_setup_voice
from .welcome import async_setup_welcome

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


@dataclass
class SamstreamData:
    """Runtime objects for one TV."""

    tv: SamsungTV
    coordinator: SamstreamCoordinator
    # Version of the TV app bundled with the integration (the update target).
    bundled_version: str | None = None
    # Options at setup: a data-only update (e.g. the TV secret) must not reload.
    options: dict[str, Any] = field(default_factory=dict)


type SamstreamConfigEntry = ConfigEntry[SamstreamData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and the sign-in hand-off view once."""
    hass.http.register_view(SamstreamSignInView())
    await async_setup_frontend(hass)
    hass.http.register_view(SamstreamTvSettingsView())
    hass.http.register_view(SamstreamStreamView())
    hass.http.register_view(SamstreamMjpegView())
    hass.http.register_view(SamstreamTvSessionView())
    hass.http.register_view(SamstreamOnboardToolView())
    hass.http.register_view(SamstreamArtThumbnailView())
    hass.http.register_view(SamstreamArtUploadView())
    app_schema: VolDictType = {vol.Required(ATTR_APP_ID): cv.string}
    for name, method in (
        ("launch_app", "async_launch_app"),
        ("close_app", "async_close_app"),
    ):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=MEDIA_PLAYER_DOMAIN,
            schema=app_schema,
            func=method,
        )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "play_stream",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Exclusive("camera", "source"): cv.entity_id,
            vol.Exclusive("url", "source"): cv.string,
            vol.Optional("label"): cv.string,
            vol.Optional("message"): cv.string,
            vol.Optional("duration"): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=86400)
            ),
            vol.Optional("return_to_previous", default=True): cv.boolean,
            vol.Optional("tv_corner", default="off"): vol.In(TV_CORNERS),
        },
        func="async_play_stream",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "show_message",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Optional("title", default=""): cv.string,
            vol.Optional("message", default=""): cv.string,
            vol.Optional("severity", default="info"): vol.In(
                ["info", "warning", "alert", "success"]
            ),
            vol.Optional("sound"): vol.Any(
                cv.string,
                vol.Schema(
                    {vol.Required("media_content_id"): cv.string}, extra=vol.ALLOW_EXTRA
                ),
            ),
            vol.Optional("duration"): vol.All(
                vol.Coerce(float), vol.Range(min=1, max=86400)
            ),
            vol.Optional("return_to_previous", default=True): cv.boolean,
        },
        func="async_show_message",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "update_message",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required("message"): cv.string},
        func="async_update_message",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "send_keys",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required("keys"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("repeats", default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=50)
            ),
            vol.Optional("delay", default=0.4): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=5)
            ),
            vol.Optional("hold", default=0): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=30)
            ),
        },
        func="async_send_keys",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "send_text",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required("text"): cv.string,
            vol.Optional("done", default=True): cv.boolean,
        },
        func="async_send_text",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "hold_key",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required("key"): cv.string,
            vol.Optional("seconds", default=1.5): vol.All(
                vol.Coerce(float), vol.Range(min=0.1, max=30)
            ),
        },
        func="async_hold_key",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "pointer",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Optional("move_x", default=0): vol.All(
                vol.Coerce(int), vol.Range(min=-1920, max=1920)
            ),
            vol.Optional("move_y", default=0): vol.All(
                vol.Coerce(int), vol.Range(min=-1080, max=1080)
            ),
            vol.Optional("click"): vol.In(["left", "right"]),
        },
        func="async_pointer",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "stop_stream",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={},
        func="async_stop_stream",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "art_mode",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={},
        func="async_art_mode",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "open_url",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required("url"): cv.string},
        func="async_open_url",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "install_app",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Optional(ATTR_PATH): cv.string},
        func="async_install_app",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "uninstall_app",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={},
        func="async_uninstall_app",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "upload_art",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required(ATTR_PATH): cv.string,
            vol.Optional("show", default=False): cv.boolean,
        },
        func="async_upload_art",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "select_art",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required("content_id"): vol.All(cv.string, vol.Match(CONTENT_ID)),
            vol.Optional("matte"): vol.All(cv.string, vol.Match(MATTE)),
        },
        func="async_select_art",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_art",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Optional("category"): vol.All(cv.string, vol.Match(CONTENT_ID))},
        func="async_list_art",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "local_control_request",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
            vol.Required("method"): vol.In(["get", "post", "push", "reply"]),
            vol.Required("resource"): vol.All(cv.string, vol.Match(r"^/")),
            vol.Optional("body"): dict,
        },
        func="async_local_control_request",
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Set up Samstream from a config entry.

    A TV that is off is a normal state, not a setup failure: the device and
    entities come from what the config flow stored, and show "off".
    """
    _remove_old_remote(hass, entry)
    tv = SamsungTV(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        token=entry.data.get(CONF_TOKEN),
    )
    coordinator = SamstreamCoordinator(hass, entry, tv)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SamstreamData(
        tv=tv,
        coordinator=coordinator,
        bundled_version=await async_bundled_version(hass),
        options=dict(entry.options),
    )

    connections = set()
    if mac := entry.data.get(CONF_MAC):
        connections.add((dr.CONNECTION_NETWORK_MAC, mac))
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        connections=connections,
        manufacturer="Samsung",
        model=entry.data.get(CONF_MODEL),
        name=entry.data.get(CONF_NAME) or entry.title,
    )

    coordinator.ocf_device = await async_get_ocf_service(hass).async_register(
        entry, coordinator.async_ocf_updated
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_voice(hass, entry)
    async_setup_welcome(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _check_certificates(_now: object = None) -> None:
        await async_check_certificate_expiry(hass)

    await _check_certificates()
    entry.async_on_unload(
        async_track_time_interval(hass, _check_certificates, CERT_CHECK_INTERVAL)
    )
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> None:
    """Reload for new options; ignore data-only updates (TV secret, token)."""
    if dict(entry.options) != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Unload a config entry and close the TV connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await async_get_ocf_service(hass).async_unregister(entry)
        forget_art_gallery(hass, entry.entry_id)
        await entry.runtime_data.tv.close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> None:
    """Release the TV from local control before deleting it for good.

    Runs after `async_unload_entry`, when the user deletes the device/entry
    rather than just disabling or reloading it. If this Home Assistant holds
    an OCF owner credential for the TV, hand it back to SmartThings first; a
    device removed without that leaves the TV still owned by this HA with no
    way back short of a TV-side reset (see the `ocf_release` repair issue).
    HA removes the entry regardless of what happens here, so this is
    best-effort: failures are logged and surfaced as a repair issue, not
    raised.
    """
    owner = entry.data.get(CONF_OCF_OWNER_PSK)
    if not owner:
        return
    settings = await async_get_ocf_service(hass).async_load()
    try:
        await hass.async_add_executor_job(
            partial(
                release_tv,
                entry.data[CONF_HOST],
                settings.obt_uuid,
                owner,
                entry.data.get(CONF_OCF_SECURE_PORT),
            )
        )
    except OcfError as err:
        _LOGGER.warning(
            "Local control: could not release %s while removing it: %s",
            entry.data[CONF_HOST],
            err,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_OCF_RELEASE}_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_OCF_RELEASE,
            translation_placeholders={"name": entry.title},
        )


def _remove_old_remote(hass: HomeAssistant, entry: SamstreamConfigEntry) -> None:
    """Remove the remote entity of earlier versions (keys: samstream.send_keys)."""
    registry = er.async_get(hass)
    unique_id = f"{entry.unique_id or entry.entry_id}_remote"
    if entity_id := registry.async_get_entity_id("remote", DOMAIN, unique_id):
        registry.async_remove(entity_id)
