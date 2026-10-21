"""The Samstream integration."""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol
from aiosamstream import SamsungTV
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, VolDictType

from .app_signing import async_check_certificate_expiry
from .const import ATTR_APP_ID, ATTR_PATH, CERT_CHECK_INTERVAL, CONF_TOKEN, DOMAIN
from .coordinator import SamstreamCoordinator
from .installer import async_bundled_version
from .signin import SamstreamSignInView

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SENSOR,
    Platform.UPDATE,
]


@dataclass
class SamstreamData:
    """Runtime objects for one TV."""

    tv: SamsungTV
    coordinator: SamstreamCoordinator
    # Version of the TV app bundled with the integration (the update target).
    bundled_version: str | None = None


type SamstreamConfigEntry = ConfigEntry[SamstreamData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and the sign-in hand-off view once."""
    hass.http.register_view(SamstreamSignInView())
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
        "install_app",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Optional(ATTR_PATH): cv.string},
        func="async_install_app",
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Set up Samstream from a config entry.

    A TV that is off is a normal state, not a setup failure: the device and
    entities come from what the config flow stored, and show "off".
    """
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SamstreamConfigEntry) -> bool:
    """Unload a config entry and close the TV connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.tv.close()
    return unloaded
