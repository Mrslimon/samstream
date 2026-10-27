"""Local SmartThings control: Home Assistant runs the OCF cloud that TVs dial.

Once onboarding points a TV's cloud address at `coaps+tcp://<HA>:<port>` (and
installs this cloud's CA and access entry on it), the TV keeps a TLS connection
to us and reports its live state: input, app, channel, volume, picture and
sound mode. Off by default, and per TV; with it off nothing here runs.

One server serves every TV. Its identity (CA + cloud UUID), port and address
are shared, kept in `.storage` (never in the repo or the entry), and the TVs are
told apart by the access token each one presents.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import ssl
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from aiosamstream.ocf import (
    CloudDevice,
    CloudIdentity,
    OcfCloud,
    generate_identity,
    issue_server_certificate,
    load_identity,
    server_ssl_context,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.system_info import async_get_system_info

from .const import (
    CONF_OCF,
    CONF_OCF_TOKEN,
    DEFAULT_OCF_PORT,
    DOMAIN,
    ISSUE_OCF_PORT,
)

if TYPE_CHECKING:
    from . import SamstreamConfigEntry

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.ocf_cloud"
DATA_OCF = f"{DOMAIN}_ocf"
REACH_TIMEOUT = 3.0
# How to open the port depends on the install (each has its own repair text).
_INSTALL_SUFFIX = {
    "Home Assistant Container": "_container",
    "Home Assistant Core": "_core",
}


def new_token() -> str:
    """Make a fresh access token for onboarding to write to a TV."""
    return secrets.token_urlsafe(32)


@dataclass
class CloudSettings:
    """What the stored cloud is: identity, port, dialled address and owner UUID."""

    identity: CloudIdentity
    port: int = DEFAULT_OCF_PORT
    host: str | None = None  # None: the host of HA's internal URL
    # The OCF owner (controller) UUID HA takes ownership as; one per install.
    obt_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_store(self) -> dict[str, Any]:
        """JSON for `.storage` (the CA key stays on this machine only)."""
        return {
            "cloud_uuid": self.identity.cloud_uuid,
            "ca_cert": self.identity.ca_cert_pem.decode(),
            "ca_key": self.identity.ca_key_pem.decode(),
            "port": self.port,
            "host": self.host,
            "obt_uuid": self.obt_uuid,
        }

    @classmethod
    def from_store(cls, data: dict[str, Any]) -> CloudSettings:
        """Load what `to_store` wrote (older stores lack an owner UUID; mint one)."""
        identity = load_identity(
            data["ca_cert"].encode(), data["ca_key"].encode(), data["cloud_uuid"]
        )
        return cls(
            identity,
            int(data.get("port") or DEFAULT_OCF_PORT),
            data.get("host"),
            data.get("obt_uuid") or str(uuid.uuid4()),
        )


@dataclass
class OcfService:
    """The shared cloud and the TVs registered with it."""

    hass: HomeAssistant
    store: Store[dict[str, Any]]
    settings: CloudSettings | None = None
    cloud: OcfCloud | None = None
    # Why the cloud is not listening (port taken / not reachable), for the UI.
    problem: str | None = None
    listeners: dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def cloud_address(self) -> str | None:
        """Return the host TVs dial: the stored override, else the internal URL host."""
        if self.settings and self.settings.host:
            return self.settings.host
        try:
            url = get_url(self.hass, allow_external=False, allow_cloud=False)
        except NoURLAvailableError:
            return None
        return urlparse(url).hostname

    def cis(self) -> str | None:
        """Return the cloud address to write to a TV: `coaps+tcp://host:port`."""
        host = self.cloud_address()
        if host is None or self.settings is None:
            return None
        return f"coaps+tcp://{host}:{self.settings.port}"

    async def async_load(self) -> CloudSettings:
        """Load the stored cloud, creating it (new CA, new UUID) the first time."""
        if self.settings is None:
            data = await self.store.async_load()
            if data:
                self.settings = await self.hass.async_add_executor_job(
                    CloudSettings.from_store, data
                )
            else:
                identity = await self.hass.async_add_executor_job(generate_identity)
                self.settings = CloudSettings(identity)
                await self.store.async_save(self.settings.to_store())
        return self.settings

    async def async_save(self, settings: CloudSettings) -> None:
        """Store new settings; the TVs using the cloud reload onto them."""
        async with self._lock:
            self.settings = settings
            await self.store.async_save(settings.to_store())
            await self._async_stop()
        for entry_id in list(self.listeners):
            self.hass.config_entries.async_schedule_reload(entry_id)

    async def async_register(
        self, entry: SamstreamConfigEntry, on_update: Any
    ) -> CloudDevice | None:
        """Serve this TV (when its options enable local control)."""
        token = entry.data.get(CONF_OCF_TOKEN)
        if not entry.options.get(CONF_OCF) or not token:
            return None
        self.listeners[entry.entry_id] = on_update
        await self.async_refresh()
        if self.cloud is None:
            return None
        return self.cloud.allow(entry.entry_id, token)

    async def async_unregister(self, entry: SamstreamConfigEntry) -> None:
        """Stop serving this TV; stop the server after the last one."""
        self.listeners.pop(entry.entry_id, None)
        if self.cloud is not None:
            self.cloud.forget(entry.entry_id)
        if not self.listeners:
            async with self._lock:
                await self._async_stop()

    @callback
    def _notify(self, device: CloudDevice) -> None:
        if self.cloud is None:
            return
        for key, known in self.cloud.devices.items():
            if known is device and (listener := self.listeners.get(key)):
                listener(device)

    async def async_refresh(self) -> None:
        """Start the server if a TV wants it and it is not running."""
        async with self._lock:
            if self.cloud is not None or not self.listeners:
                return
            settings = await self.async_load()
            cis = self.cis()
            host = self.cloud_address()
            if cis is None or host is None:
                self._set_problem("no_address")
                return
            chain, key = await self.hass.async_add_executor_job(
                issue_server_certificate, settings.identity, host
            )
            context = await self.hass.async_add_executor_job(
                server_ssl_context, chain, key
            )
            cloud = OcfCloud(
                context,
                cloud_uuid=settings.identity.cloud_uuid,
                ca_der=settings.identity.ca_der,
                cis=cis,
                listener=self._notify,
            )
            try:
                await cloud.start(settings.port)
            except OSError as err:
                _LOGGER.warning(
                    "Local control cannot listen on %s: %s", settings.port, err
                )
                self._set_problem("port_in_use")
                return
            self.cloud = cloud
            if await self._async_reachable(host, cloud.port or settings.port):
                self._set_problem(None)
            else:
                self._set_problem("not_reachable")

    async def _async_reachable(self, host: str, port: int) -> bool:
        """Whether a connection to the address TVs dial gets through to us.

        From inside a Docker bridge network this fails when the port is not
        published, which is the usual reason TVs cannot reach the cloud. It
        completes the TLS handshake (without checking our own certificate), so
        the server does not log a dropped handshake.
        """
        probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # no CA files to load
        probe.check_hostname = False
        probe.verify_mode = ssl.CERT_NONE
        try:
            async with asyncio.timeout(REACH_TIMEOUT):
                _, writer = await asyncio.open_connection(host, port, ssl=probe)
        except (OSError, TimeoutError):
            return False
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return True

    def _set_problem(self, problem: str | None) -> None:
        self.problem = problem
        if problem is None:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_OCF_PORT)
            return
        self.hass.async_create_task(self._async_raise_issue(problem))

    async def _async_raise_issue(self, problem: str) -> None:
        key = f"ocf_{problem}"
        if problem == "not_reachable":
            info = await async_get_system_info(self.hass)
            install = info.get("installation_type")
            key += _INSTALL_SUFFIX.get(str(install), "")
        port = str(self.settings.port if self.settings else DEFAULT_OCF_PORT)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_OCF_PORT,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={"port": port},
        )

    async def _async_stop(self) -> None:
        if self.cloud is not None:
            await self.cloud.stop()
            self.cloud = None


def async_get_service(hass: HomeAssistant) -> OcfService:
    """Return the one OCF service of this HA."""
    service: OcfService | None = hass.data.get(DATA_OCF)
    if service is None:
        service = OcfService(hass, Store(hass, STORE_VERSION, STORE_KEY, private=True))
        hass.data[DATA_OCF] = service
    return service
