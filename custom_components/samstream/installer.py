"""Install the Samstream TV app over sdb, signed by HA, the way Tizen Studio would."""

from __future__ import annotations

import contextlib
import logging
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiosamstream import (
    SAMSTREAM_APP_ID,
    InstallResult,
    ListedApp,
    SdbClient,
    SdbConnectionError,
    SdbError,
    generate_key,
)
from aiosamstream.samsung_cert import (
    SamsungAccount,
    SamsungCertError,
    request_author,
    request_distributor,
)
from aiosamstream.signing import (
    SigningError,
    SigningIdentity,
    package_version,
    sign_wgt,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store

from .app_signing import (
    SOURCE_IMPORT,
    SOURCE_SAMSUNG,
    SigningSetup,
    async_check_certificate_expiry,
    async_load_signing,
    async_save_signing,
)
from .const import DOMAIN
from .tv_settings import add_package_settings, package_settings

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

_KEY_STORE_VERSION = 1
_KEY_STORE = f"{DOMAIN}.sdb_key"
BUNDLED_PACKAGE = Path(__file__).parent / "bundled" / "samstream.wgt"
# What vd_appinstall reports when the installed copy has another author.
AUTHOR_MISMATCH = "Author certificate not match"


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
    """Resolve a file path inside the HA config dir (or another allowed dir)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(hass.config.path(path))
    resolved = candidate.resolve()
    config_dir = Path(hass.config.config_dir).resolve()
    allowed = resolved.is_relative_to(config_dir) or hass.config.is_allowed_path(
        str(resolved)
    )
    if not allowed:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_allowed",
            translation_placeholders={"path": path},
        )
    return resolved


@contextlib.asynccontextmanager
async def _sdb(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> AsyncIterator[SdbClient]:
    """Yield a connected sdb client; a refused connection raises the repair issue."""
    key = await async_get_sdb_key(hass)
    client = SdbClient(entry.data[CONF_HOST], key)
    try:
        await client.connect()
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
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))
    try:
        yield client
    finally:
        await client.close()


async def async_list_apps(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> list[ListedApp] | None:
    """Return the TV's full app list over sdb; None when sdb is not available.

    Background use: no repair issue here (the install path raises that).
    """
    key = await async_get_sdb_key(hass)
    try:
        async with SdbClient(entry.data[CONF_HOST], key) as sdb:
            return await sdb.installed_apps()
    except SdbError as err:
        _LOGGER.debug("No sdb app list from %s: %s", entry.title, err)
        return None


async def async_read_duid(hass: HomeAssistant, entry: SamstreamConfigEntry) -> str:
    """Read the TV's DUID, which a distributor certificate must list."""
    async with _sdb(hass, entry) as sdb:
        try:
            return await sdb.duid()
        except SdbError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err


async def async_install_package(
    hass: HomeAssistant, entry: SamstreamConfigEntry, package: Path | None
) -> InstallResult:
    """Sign (when signing is set up) and install a .wgt; None = the bundled app.

    Only one install runs per TV; the install button is unavailable meanwhile.
    """
    coordinator = entry.runtime_data.coordinator
    if coordinator.installing:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="install_in_progress"
        )
    coordinator.installing = True
    coordinator.async_update_listeners()
    try:
        return await _async_install(hass, entry, package)
    finally:
        coordinator.installing = False
        coordinator.async_update_listeners()


async def _async_install(
    hass: HomeAssistant, entry: SamstreamConfigEntry, package: Path | None
) -> InstallResult:
    setup = await async_load_signing(hass)
    if package is None:
        if setup is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="signing_not_set_up"
            )
        package = BUNDLED_PACKAGE
    try:
        wgt = await hass.async_add_executor_job(package.read_bytes)
    except OSError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_found",
            translation_placeholders={"path": str(package)},
        ) from err
    # HA's URL, the TV secret and the current settings travel with the package.
    payload = package_settings(hass, entry)
    try:
        wgt = await hass.async_add_executor_job(add_package_settings, wgt, payload)
    except zipfile.BadZipFile as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="install_failed",
            translation_placeholders={"error": f"{package.name} is not a .wgt package"},
        ) from err
    if setup is not None:
        try:
            wgt = await hass.async_add_executor_job(
                sign_wgt, wgt, setup.author, setup.distributor
            )
        except SigningError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async with _sdb(hass, entry) as sdb:
        try:
            result = await _install_replacing_other_author(sdb, wgt, entry)
        except SdbError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err
    _LOGGER.info("Installed %s on %s", SAMSTREAM_APP_ID, entry.title)
    await entry.runtime_data.coordinator.async_rescan_apps()
    return result


async def _install_replacing_other_author(
    sdb: SdbClient, wgt: bytes, entry: SamstreamConfigEntry
) -> InstallResult:
    """Install; if the TV has Samstream from another author, remove it first.

    Tizen only upgrades an app signed by the same author certificate. A copy
    installed earlier with another tool (Tizen Studio, Apps2Samsung) is replaced:
    it is our own app and holds no data worth keeping.
    """
    try:
        return await sdb.install(wgt, SAMSTREAM_APP_ID)
    except SdbError as err:
        if AUTHOR_MISMATCH not in str(err):
            raise
    _LOGGER.warning(
        "Samstream on %s was signed by another author certificate; reinstalling",
        entry.title,
    )
    await sdb.uninstall(SAMSTREAM_APP_ID)
    return await sdb.install(wgt, SAMSTREAM_APP_ID)


async def async_obtain_samsung_certificates(
    hass: HomeAssistant, entry: SamstreamConfigEntry, account: SamsungAccount
) -> SigningSetup:
    """Get, extend (new TV) or renew (expiring) Samsung certificates.

    The key is kept in every case, so apps already installed can still be updated.
    """
    duid = await async_read_duid(hass, entry)
    current = await async_load_signing(hass)
    session = async_get_clientsession(hass)
    try:
        if current is not None and current.source == SOURCE_SAMSUNG:
            renew = current.needs_renewal()
            if current.covers(duid) and not renew:
                return current
            key = current.author.key
            author = (
                await request_author(session, account, key) if renew else current.author
            )
        else:
            key = await hass.async_add_executor_job(_new_signing_key)
            author = await request_author(session, account, key)
        duids = sorted({*(current.duids if current else []), duid})
        distributor, _profile = await request_distributor(session, account, key, duids)
    except SamsungCertError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="samsung_refused",
            translation_placeholders={"error": str(err)},
        ) from err
    setup = SigningSetup(
        author=author,
        distributor=distributor,
        source=SOURCE_SAMSUNG,
        email=account.email,
    )
    await async_save_signing(hass, setup)
    await async_check_certificate_expiry(hass)
    return setup


async def async_import_certificates(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    p12_files: tuple[Path, Path],
    password: str,
) -> SigningSetup:
    """Use existing author.p12 / distributor.p12 (Tizen Studio, Apps2Samsung)."""
    try:
        author, distributor = await hass.async_add_executor_job(
            _load_p12_pair, p12_files, password
        )
    except OSError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="file_not_found",
            translation_placeholders={"path": str(err.filename or p12_files[0])},
        ) from err
    except SigningError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="bad_certificate",
            translation_placeholders={"error": str(err)},
        ) from err
    setup = SigningSetup(author=author, distributor=distributor, source=SOURCE_IMPORT)
    duid = await async_read_duid(hass, entry)
    if not setup.covers(duid):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="duid_not_covered",
            translation_placeholders={"duid": duid},
        )
    await async_save_signing(hass, setup)
    await async_check_certificate_expiry(hass)
    return setup


async def async_bundled_version(hass: HomeAssistant) -> str | None:
    """Version of the TV app shipped with the integration (None if missing)."""
    try:
        wgt = await hass.async_add_executor_job(BUNDLED_PACKAGE.read_bytes)
        return package_version(wgt)
    except OSError, SigningError:
        _LOGGER.warning("No usable bundled Samstream app at %s", BUNDLED_PACKAGE)
        return None


def _new_signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _load_p12_pair(
    p12_files: tuple[Path, Path], password: str
) -> tuple[SigningIdentity, SigningIdentity]:
    author, distributor = p12_files
    return (
        SigningIdentity.from_p12(author.read_bytes(), password),
        SigningIdentity.from_p12(distributor.read_bytes(), password),
    )


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
