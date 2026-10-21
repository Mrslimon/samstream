"""Install the Samstream TV app over sdb, the way Tizen Studio would, from HA."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiosamstream import (
    SAMSTREAM_APP_ID,
    InstallResult,
    SdbClient,
    SdbConnectionError,
    SdbError,
    generate_key,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store

from .const import DOMAIN

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

_KEY_STORE_VERSION = 1
_KEY_STORE = f"{DOMAIN}.sdb_key"


def ha_lan_host(hass: HomeAssistant) -> str | None:
    """Return the host the TV should see for Home Assistant (internal URL).

    Inside Docker the container's own interface address is not what the TV sees,
    so the configured internal URL is the reliable source.
    """
    try:
        url = get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        return None
    return urlparse(url).hostname


async def async_get_sdb_key(hass: HomeAssistant) -> bytes:
    """Return the RSA key HA authenticates to sdbd with (created once, then reused)."""
    store: Store[dict[str, str]] = Store(
        hass, _KEY_STORE_VERSION, _KEY_STORE, private=True
    )
    if (data := await store.async_load()) and (pem := data.get("pem")):
        return pem.encode()
    key = await hass.async_add_executor_job(generate_key)
    await store.async_save({"pem": key.decode()})
    return key


def issue_id(entry: SamstreamConfigEntry) -> str:
    """Return the repair issue ID used while sdb cannot reach this TV."""
    return f"developer_mode_{entry.entry_id}"


def resolve_package_path(hass: HomeAssistant, path: str) -> Path:
    """Resolve a .wgt path inside the HA config dir (or another allowed dir)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(hass.config.path(path))
    resolved = candidate.resolve()
    config_dir = Path(hass.config.config_dir).resolve()
    if not (
        resolved.is_relative_to(config_dir)
        or hass.config.is_allowed_path(str(resolved))
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_allowed",
            translation_placeholders={"path": path},
        )
    return resolved


async def async_install_package(
    hass: HomeAssistant, entry: SamstreamConfigEntry, package: Path
) -> InstallResult:
    """Push and install a signed .wgt, raising translated errors."""
    try:
        wgt = await hass.async_add_executor_job(package.read_bytes)
    except OSError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_found",
            translation_placeholders={"path": str(package)},
        ) from err

    key = await async_get_sdb_key(hass)
    try:
        async with SdbClient(entry.data[CONF_HOST], key) as sdb:
            result = await sdb.install(wgt, SAMSTREAM_APP_ID)
    except SdbConnectionError as err:
        placeholders = _developer_placeholders(hass, entry)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id(entry),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="developer_mode",
            translation_placeholders=placeholders,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="sdb_unreachable",
            translation_placeholders=placeholders,
        ) from err
    except SdbError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="install_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))
    _LOGGER.info("Installed %s on %s", SAMSTREAM_APP_ID, entry.title)
    await entry.runtime_data.coordinator.async_rescan_apps()
    return result


def _developer_placeholders(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, str]:
    data = entry.runtime_data.coordinator.data
    info = data.info if data else None
    if info is None or not info.developer_mode:
        current = "off"
    else:
        current = info.developer_ip or "?"
    return {
        "name": entry.title,
        "ha_host": ha_lan_host(hass) or "?",
        "developer_host": current,
    }
