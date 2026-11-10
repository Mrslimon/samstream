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
from .const import CONF_DUID, DOMAIN
from .notifier import NOTIFIER_APP_ID, stamp_notifier_key
from .tv_settings import (
    add_package_settings,
    ensure_tv_secret,
    package_settings,
)

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

_KEY_STORE_VERSION = 1
_KEY_STORE = f"{DOMAIN}.sdb_key"
BUNDLED_PACKAGE = Path(__file__).parent / "bundled" / "samstream.wgt"
# The native notifier (.NET, nodisplay) ships alongside the web app and is
# installed in the same sdb session. It is signed with the same HA identity.
BUNDLED_NOTIFIER = Path(__file__).parent / "bundled" / "notifier.tpk"
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


async def resolve_package_path(hass: HomeAssistant, path: str) -> Path:
    """Resolve a file path, allowed only where HA itself allows reading files.

    `install_app` and `upload_art` take this path from any non-admin caller.
    Resolving it anywhere under the config directory would let that caller
    read and push to the TV anything there, including `secrets.yaml` and
    `.storage` (every other integration's tokens and credentials) - so
    `hass.config.is_allowed_path` (`allowlist_external_dirs` in
    `configuration.yaml`) is the only gate, the same one HA itself uses for
    letting an action read an arbitrary local file.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(hass.config.path(path))
    resolved = await hass.async_add_executor_job(candidate.resolve)
    if not hass.config.is_allowed_path(str(resolved)):
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
        issue, error = developer_problem(
            placeholders["developer_host"], placeholders["ha_host"]
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id(entry),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=issue,
            translation_placeholders=placeholders,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=error,
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
        return await _read_duid(hass, entry, sdb)


async def _read_duid(
    hass: HomeAssistant, entry: SamstreamConfigEntry, sdb: SdbClient
) -> str:
    try:
        duid = await sdb.duid()
    except SdbError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="install_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    if entry.data.get(CONF_DUID) != duid:
        # Data only: the update listener reloads on option changes, not this.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DUID: duid}
        )
    return duid


def known_duids(hass: HomeAssistant) -> set[str]:
    """DUIDs of every Samstream TV seen so far (one certificate covers them all)."""
    return {
        str(other.data[CONF_DUID])
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.data.get(CONF_DUID)
    }


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


# Both apps Samstream installs, removed together by the uninstall action.
SAMSTREAM_APP_IDS = (SAMSTREAM_APP_ID, NOTIFIER_APP_ID)


async def async_uninstall_package(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> list[str]:
    """Remove both Samstream apps from the TV; return the app IDs removed.

    The counterpart to install: the two-package design means the web app and the
    notifier both come off. sdb must be reachable (Developer Mode on) — an
    unreachable TV raises the repair issue via `_sdb`. Each app is best-effort:
    one that is already gone is not an error, so the other is still removed.
    """
    coordinator = entry.runtime_data.coordinator
    if coordinator.installing:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="install_in_progress"
        )
    coordinator.installing = True
    coordinator.async_update_listeners()
    try:
        removed: list[str] = []
        async with _sdb(hass, entry) as sdb:
            for app_id in SAMSTREAM_APP_IDS:
                try:
                    output = await sdb.uninstall(app_id)
                except SdbError as err:
                    _LOGGER.warning(
                        "Could not uninstall %s from %s: %s", app_id, entry.title, err
                    )
                    continue
                if "uninstall completed" in output:
                    removed.append(app_id)
                    _LOGGER.info("Uninstalled %s from %s", app_id, entry.title)
                else:
                    _LOGGER.debug(
                        "%s was not installed on %s: %s", app_id, entry.title, output
                    )
        await coordinator.async_rescan_apps()
        return removed
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
        duid = await _read_duid(hass, entry, sdb)
        if setup is not None and not setup.covers(duid):
            # The TV would only say "Invalid format of certificate in signature".
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"duid_not_covered_{entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="duid_not_covered",
                translation_placeholders={"name": entry.title, "duid": duid},
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="certificate_missing_tv",
                translation_placeholders={"name": entry.title, "duid": duid},
            )
        ir.async_delete_issue(hass, DOMAIN, f"duid_not_covered_{entry.entry_id}")
        try:
            result = await _install_replacing_other_author(sdb, wgt, entry)
        except SdbError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The notifier rides on the same session. It is best-effort: the web
        # app's on-screen notice is the fallback, so a notifier failure must
        # not fail the install the user asked for.
        await _async_install_notifier(hass, entry, sdb, setup)
    _LOGGER.info("Installed %s on %s", SAMSTREAM_APP_ID, entry.title)
    await entry.runtime_data.coordinator.async_rescan_apps()
    return result


async def _async_install_notifier(
    hass: HomeAssistant,
    entry: SamstreamConfigEntry,
    sdb: SdbClient,
    setup: SigningSetup | None,
) -> None:
    """Stamp the TV secret, sign, and install the bundled notifier .tpk.

    Shares the caller's sdb session (DUID already checked there). Never raises:
    a missing package or an install error is logged and the web app stands on
    its own.
    """
    if setup is None:
        # A retail TV refuses an unsigned package, so there is nothing to try.
        _LOGGER.debug("No signing set up; skipping the notifier install")
        return
    try:
        tpk = await hass.async_add_executor_job(BUNDLED_NOTIFIER.read_bytes)
    except OSError:
        _LOGGER.warning("No bundled notifier at %s; skipping", BUNDLED_NOTIFIER)
        return
    # Stamp the TV secret first, then sign, so the signature covers the key.
    secret = ensure_tv_secret(hass, entry)
    tpk = await hass.async_add_executor_job(stamp_notifier_key, tpk, secret)
    try:
        tpk = await hass.async_add_executor_job(
            sign_wgt, tpk, setup.author, setup.distributor
        )
    except SigningError as err:
        _LOGGER.warning("Could not sign the notifier for %s: %s", entry.title, err)
        return
    try:
        await _install_notifier_replacing_other_author(sdb, tpk, entry)
    except SdbError as err:
        _LOGGER.warning(
            "Notifier install on %s failed (web-app notice still works): %s",
            entry.title,
            err,
        )
        return
    _LOGGER.info("Installed %s on %s", NOTIFIER_APP_ID, entry.title)


async def _install_notifier_replacing_other_author(
    sdb: SdbClient, tpk: bytes, entry: SamstreamConfigEntry
) -> InstallResult:
    """Install the notifier; replace a copy signed by another author first."""
    try:
        return await sdb.install(tpk, NOTIFIER_APP_ID)
    except SdbError as err:
        if AUTHOR_MISMATCH not in str(err):
            raise
    _LOGGER.warning(
        "Notifier on %s was signed by another author certificate; reinstalling",
        entry.title,
    )
    await sdb.uninstall(NOTIFIER_APP_ID)
    return await sdb.install(tpk, NOTIFIER_APP_ID)


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
            missing = {duid, *known_duids(hass)} - set(current.duids)
            if not missing and not renew:
                return current
            key = current.author.key
            author = (
                await request_author(session, account, key) if renew else current.author
            )
        else:
            key = await hass.async_add_executor_job(_new_signing_key)
            author = await request_author(session, account, key)
        # Every Samstream TV seen so far, so one sign-in covers them all.
        duids = sorted({*(current.duids if current else []), *known_duids(hass), duid})
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


def developer_problem(developer_host: str, ha_host: str) -> tuple[str, str]:
    """(repair issue, error) keys for an sdb connection the TV refused.

    - Host is HA's: set up right but not listening yet; the TV starts its
      developer service only after a full restart.
    - Host is HA's address backwards (5.1.168.192): some TVs mirror the IP field
      when the menu language is right-to-left, so the digits were stored reversed.
    - Otherwise Developer Mode is off or points at another computer.
    """
    if developer_host == ha_host:
        return "developer_restart", "sdb_restart_needed"
    if developer_host == ".".join(reversed(ha_host.split("."))) != ha_host:
        return "developer_reversed", "sdb_host_reversed"
    return "developer_mode", "sdb_unreachable"


# Unicode isolates: keep a run left-to-right inside right-to-left text.
LRI, PDI = chr(0x2066), chr(0x2069)


def ip_boxes(host: str, *, reverse: bool = False) -> str:
    """Write the IP as the TV's four boxes take it: `192 | 168 | 1 | 5`.

    `reverse` is the order an Arabic (right-to-left) TV menu needs. The text is
    isolated left-to-right, so an Arabic page does not reorder the numbers.
    """
    parts = host.split(".")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):  # noqa: PLR2004
        return host
    if reverse:
        parts.reverse()
    return LRI + "  |  ".join(parts) + PDI


def _developer_placeholders(
    hass: HomeAssistant, entry: SamstreamConfigEntry
) -> dict[str, str]:
    data = entry.runtime_data.coordinator.data
    info = data.info if data else None
    if info is None or not info.developer_mode:
        current = "off"
    else:
        current = info.developer_ip or "?"
    host = ha_lan_host(hass) or "?"
    return {
        "name": entry.title,
        "ha_host": host,
        "ha_host_boxes": ip_boxes(host),
        "ha_host_rtl": ip_boxes(host, reverse=True),
        "developer_host": current,
    }
