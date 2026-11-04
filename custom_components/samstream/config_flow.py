"""Config flow for Samstream: find the TV, then pair once (the TV shows "Allow")."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Mapping
from functools import partial
from typing import Any
from urllib.parse import unquote, urlencode, urlparse

from aiosamstream import (
    DeviceInfo,
    OcfError,
    OcfTvOwnedError,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
    SamsungTV,
)
from aiosamstream.ocf import (
    CloudDevice,
    OnboardBundle,
    decode_credential,
    discover,
    encode_bundle,
    load_identity,
    onboard_tv,
    release_tv,
    trigger_pin,
)
from aiosamstream.samsung_cert import (
    SamsungCertError,
    new_state,
    parse_callback,
    sign_in_url,
)
from cryptography.exceptions import UnsupportedAlgorithm
from homeassistant.components import webhook
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryBaseFlow,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_CODE,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_NAME,
    CONF_PASSWORD,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from .app_signing import SigningSetup, async_load_signing
from .const import (
    CONF_AUTHOR_P12,
    CONF_AUTO_UPDATE,
    CONF_DISTRIBUTOR_P12,
    CONF_EXTRA_APPS,
    CONF_FRAME_POWER,
    CONF_LANGUAGE,
    CONF_OCF,
    CONF_OCF_DEVICE_UUID,
    CONF_OCF_HOST,
    CONF_OCF_OWNER_PSK,
    CONF_OCF_PORT,
    CONF_OCF_SECURE_PORT,
    CONF_OCF_TOKEN,
    CONF_OCF_WELCOME,
    CONF_RESUME,
    CONF_THEME,
    CONF_TOKEN,
    CONF_TV_CORNER,
    CONF_VOICE,
    CONF_VOICE_SHOW,
    CONF_VOICE_WEBHOOK,
    CONF_WOL_TARGET,
    CORNERS,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    DEFAULT_TV_CORNER,
    DOMAIN,
    FRAME_POWER_MODES,
    ISSUE_OCF_RELEASE,
    LANGUAGES,
    OCF_ONBOARD_TIMEOUT,
    THEMES,
)
from .coordinator import default_wol_target
from .installer import (
    async_import_certificates,
    async_obtain_samsung_certificates,
    ha_lan_host,
    ip_boxes,
    resolve_package_path,
)
from .ocf import CloudSettings, async_get_service, new_token
from .onboard_tool import LAUNCHER_FILE, TOOL_FILE, async_offer
from .signin import (
    SIGN_IN_TIMEOUT,
    PendingSignIn,
    cancel_sign_in,
    helper_command,
    start_sign_in,
)
from .validation import vol
from .voice import voice_webhook_url

_LOGGER = logging.getLogger(__name__)

# The access token identifies the TV to the local cloud: keep it unguessable.
MIN_OCF_TOKEN = 16
# PIN onboarding tries a few times: the TV's secure port rotates, so a handshake
# can land on a just-rotated port. Each attempt re-discovers the live port.
_ONBOARD_ATTEMPTS = 3
# Reconnect (Configure): wait for the TV before the restart, then for it to
# come back once the viewer allowed it on screen.
RECONNECT_WAIT = 30
RESTART_SETTLE = 3
RECONNECT_ALLOW_WAIT = 120

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class _LocalControlSteps(ConfigEntryBaseFlow):
    """Connect a TV for local control: PIN entry in HA, or the LAN helper.

    Shared by first-time setup (no config entry yet, so the cloud holds the TV
    for the flow) and the options flow. Subclasses say which TV, which token,
    and where the onboarding results go.
    """

    def _lc_init(self) -> None:
        self._onboard_task: asyncio.Task[str] | None = None
        self._lc_mode = "lan"  # "pin" when HA can reach the TV, else "lan" fallback
        self._lc_onboarded = False
        self._lc_done_shown = False
        self._ocf_pin = ""
        self._ocf_port: int | None = None
        self._ocf_device_uuid: str | None = None
        self._lc_error = ""  # the last onboarding error, shown on the failed screen

    def _lc_host(self) -> str:
        raise NotImplementedError

    def _lc_name(self) -> str:
        raise NotImplementedError

    def _lc_token(self) -> str:
        raise NotImplementedError

    def _lc_key(self) -> str:
        """Return the key the cloud serves this TV under."""
        raise NotImplementedError

    async def _lc_prepare(self) -> bool:
        """Make sure the cloud can serve this TV; False if HA has no address."""
        raise NotImplementedError

    def _lc_store(self, updates: dict[str, Any]) -> None:
        """Keep what onboarding learned (owner PSK, device, secure port)."""
        raise NotImplementedError

    def _lc_trouble_menu(self) -> list[str]:
        raise NotImplementedError

    async def async_step_local_control_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Decide the mode: PIN entry when HA can reach the TV, else LAN helper."""
        if not await self._lc_prepare():
            return await self.async_step_local_control_trouble()
        host = self._lc_host()
        if self._ocf_port is None:
            try:
                # Discover FIRST: a reply proves HA can reach the TV over plain
                # CoAP and yields the secure port + device UUID. Only then trigger
                # the PIN. This way an unreachable TV surfaces as OcfError (-> LAN
                # helper) and an owned TV as OcfTvOwnedError (-> "already owned"),
                # instead of an ambiguous PIN-trigger refusal being misread as
                # "service not found" and wrongly routed to the LAN helper.
                port, device_uuid = await self.hass.async_add_executor_job(
                    discover, host
                )
                await self.hass.async_add_executor_job(trigger_pin, host)
            except OcfTvOwnedError as err:
                _LOGGER.info("Local control: %s is owned (%s)", host, err)
                return await self.async_step_local_control_owned()
            except OcfError as err:
                _LOGGER.info("Local control: HA cannot reach %s (%s); LAN", host, err)
                self._lc_mode = "lan"
            else:
                self._ocf_port, self._ocf_device_uuid = port, device_uuid
                self._lc_mode = "pin"
        return self._lc_pin_form() if self._lc_mode == "pin" else self._lc_lan_form()

    async def async_step_local_control_lan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use the LAN helper (chosen after the direct way failed)."""
        self._lc_mode = "lan"
        return self._lc_lan_form()

    def _lc_pin_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="local_control_pin",
            data_schema=vol.Schema({vol.Required("pin"): str}),
            errors=errors or {},
            description_placeholders={"name": self._lc_name()},
            last_step=False,
        )

    def _lc_lan_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        tv_ip = self._lc_host()
        bundle = self._lc_bundle() or ""
        links = (
            async_offer(self.hass, tv_ip, bundle)
            if bundle
            else {"tool_url": "#", "launcher_url": "#"}
        )
        return self.async_show_form(
            step_id="local_control_connect_lan",
            data_schema=vol.Schema(
                {
                    vol.Optional("credential"): TextSelector(
                        TextSelectorConfig(multiline=True)
                    )
                }
            ),
            errors=errors or {},
            description_placeholders={
                "name": self._lc_name(),
                "tv_ip": tv_ip,
                "tool": TOOL_FILE,
                "launcher": LAUNCHER_FILE,
                "command": f"python3 {TOOL_FILE}",
                **links,
            },
            last_step=False,
        )

    def _lc_bundle(self) -> str | None:
        """Return the cloud details the LAN helper writes to the TV, as one string."""
        service = async_get_service(self.hass)
        settings = service.settings
        address, cis = service.cloud_address(), service.cis()
        if settings is None or address is None or cis is None:
            return None
        return encode_bundle(
            OnboardBundle(
                address=address,
                cis=cis,
                cloud_uuid=settings.identity.cloud_uuid,
                obt_uuid=settings.obt_uuid,
                token=self._lc_token(),
                ca_pem=settings.identity.ca_cert_pem.decode(),
            )
        )

    async def async_step_local_control_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """PIN mode: take the 8 digits, then onboard and wait."""
        pin = str((user_input or {}).get("pin", "")).strip()
        if not (pin.isdigit() and len(pin) == 8):  # noqa: PLR2004
            return self._lc_pin_form({"pin": "invalid_pin"})
        self._ocf_pin = pin
        self._onboard_task = None
        return await self.async_step_local_control_wait()

    async def async_step_local_control_connect_lan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """LAN mode: accept the credential the LAN tool printed, then wait."""
        credential = str((user_input or {}).get("credential", "")).strip()
        if credential:
            try:
                cred = decode_credential(credential)
            except ValueError, KeyError:
                return self._lc_lan_form({"credential": "invalid_credential"})
            self._lc_store(
                {
                    CONF_OCF_OWNER_PSK: cred.owner_psk_hex,
                    CONF_OCF_DEVICE_UUID: cred.device_uuid,
                    CONF_OCF_SECURE_PORT: cred.secure_port,
                }
            )
        self._lc_onboarded = True  # the user ran the helper
        self._onboard_task = None
        return await self.async_step_local_control_wait()

    async def async_step_local_control_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Onboard (PIN mode) and/or wait for the TV to dial in; paired on success."""
        if self._onboard_task is None:
            self._onboard_task = self.hass.async_create_task(self._run_connect())
        if not self._onboard_task.done():
            return self.async_show_progress(
                step_id="local_control_wait",
                progress_action="onboarding",
                progress_task=self._onboard_task,
                description_placeholders={"name": self._lc_name()},
            )
        outcome = self._onboard_task.result()
        self._onboard_task = None
        self._lc_done_shown = False
        return self.async_show_progress_done(next_step_id=f"local_control_{outcome}")

    async def _run_connect(self) -> str:
        """In PIN mode own the TV first; then wait for it to dial the cloud.

        Returns the next step: "done", "failed" (onboarding refused) or
        "trouble" (onboarded, but the TV never dialed in).
        """
        service = async_get_service(self.hass)
        settings = await service.async_load()
        cis = service.cis()
        if self._lc_mode == "pin" and cis is not None:
            # Reuse the secure port found on the connect screen: per the
            # protocol doc (ocf-local-protocol.md 2 and 10) it changes only on
            # power cycle / reset, not continuously, so it is still valid when
            # the user has typed the PIN. Re-discovery is flaky (the TV answers
            # plain CoAP only intermittently, worse after heavy OCF traffic),
            # so only fall back to it (secure_port=None) on later attempts if
            # the known port's handshake fails.
            result = None
            for attempt in range(_ONBOARD_ATTEMPTS):
                try:
                    result = await self.hass.async_add_executor_job(
                        partial(
                            onboard_tv,
                            self._lc_host(),
                            self._ocf_pin,
                            obt_uuid=settings.obt_uuid,
                            ca_der=settings.identity.ca_der,
                            cloud_uuid=settings.identity.cloud_uuid,
                            cis=cis,
                            access_token=self._lc_token(),
                            device_uuid=self._ocf_device_uuid,
                            secure_port=self._ocf_port if attempt == 0 else None,
                        )
                    )
                    break
                except OcfError as err:
                    self._lc_error = str(err)
                    if attempt + 1 < _ONBOARD_ATTEMPTS:
                        _LOGGER.info(
                            "Onboarding attempt %d failed (%s); retrying with a "
                            "fresh secure-port discovery",
                            attempt + 1,
                            err,
                        )
                        await asyncio.sleep(1)
                        continue
                    _LOGGER.warning("Local control onboarding failed: %s", err)
                    return "failed"
            if result is None:  # every attempt exhausted without a result
                return "failed"
            self._lc_onboarded = True
            self._lc_store(
                {
                    CONF_OCF_OWNER_PSK: result.owner_psk_hex,
                    CONF_OCF_DEVICE_UUID: result.device_uuid,
                    CONF_OCF_SECURE_PORT: result.secure_port,
                }
            )
        return "done" if await self._await_dial_in() else "trouble"

    async def _await_dial_in(self) -> bool:
        """Return True once the TV holds a connection to the cloud, else time out."""
        service = async_get_service(self.hass)
        key = self._lc_key()
        try:
            async with asyncio.timeout(OCF_ONBOARD_TIMEOUT):
                while True:
                    cloud = service.cloud
                    device = cloud.devices.get(key) if cloud is not None else None
                    if device is not None and device.connected:
                        return True
                    await asyncio.sleep(1)
        except TimeoutError:
            return False

    async def async_step_local_control_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Onboarding itself failed: the TV refused or stopped answering."""
        self._ocf_port = None  # re-decide PIN vs LAN and re-trigger the PIN on retry
        return self.async_show_menu(
            step_id="local_control_failed",
            menu_options=self._lc_trouble_menu(),
            description_placeholders={
                "name": self._lc_name(),
                # The exact reason from onboarding (e.g. the DTLS handshake error),
                # so the dialog says what went wrong instead of only generic hints.
                "error": self._lc_error or "the TV did not complete the connection",
            },
        )

    async def async_step_local_control_owned(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain that SmartThings still owns the TV, so it will not show a PIN."""
        self._ocf_port = None
        return self.async_show_menu(
            step_id="local_control_owned",
            menu_options=[
                option
                for option in self._lc_trouble_menu()
                if option != "local_control_lan"  # the helper hits the same wall
            ],
            description_placeholders={"name": self._lc_name()},
        )

    async def async_step_local_control_trouble(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show common reasons the TV did not connect, with a way to retry."""
        self._ocf_port = None
        return self.async_show_menu(
            step_id="local_control_trouble",
            menu_options=self._lc_trouble_menu(),
            description_placeholders={"name": self._lc_name()},
        )


class SamstreamConfigFlow(_LocalControlSteps, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samstream."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SamstreamOptionsFlow:
        """Options: where Wake-on-LAN packets are sent."""
        return SamstreamOptionsFlow()

    def __init__(self) -> None:
        """Start with nothing known about the TV."""
        self._host = ""
        self._info: DeviceInfo | None = None
        self._token: str | None = None
        self._pair_task: asyncio.Task[str | None] | None = None
        self._pair_error = ""
        self._retry_form_shown = False
        # Local control set up during first-time setup (see _LocalControlSteps).
        self._lc_init()
        self._lc_data: dict[str, Any] = {}
        self._lc_enabled = False
        # Show "Samstream is set up" on the TV once the new entry can.
        self._lc_welcome = False
        self._lc_holding = False
        self._ocf_token = new_token()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV host and check it answers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            info, error = await self._async_read_device_info()
            if info is None:
                errors["base"] = error or "unknown"
            else:
                await self.async_set_unique_id(info.uuid)
                # Same TV at a new address: just move the existing entry.
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                return await self.async_step_pair()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Offer to add a Samsung TV that announced itself on the network."""
        host = urlparse(discovery_info.ssdp_location or "").hostname
        if not host:
            return self.async_abort(reason="not_supported")
        self._host = host
        info, _error = await self._async_read_device_info()
        if info is None:
            # Pre-2016 models do not have the API Samstream needs.
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(info.uuid)
        # Known TV at a new address (DHCP): move the entry, nothing to confirm.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self.context["title_placeholders"] = {"name": info.name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered TV, then pair."""
        if user_input is not None:
            return await self.async_step_pair()
        self._set_confirm_only()
        info = self._info
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": info.name if info else self._host,
                "model": (info.model_name if info else None) or "",
                "host": self._host,
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait while the TV shows the "Allow" popup."""
        if self._pair_task is None:
            self._pair_task = self.hass.async_create_task(self._async_pair())
        if not self._pair_task.done():
            return self.async_show_progress(
                step_id="pair",
                progress_action="wait_for_allow",
                progress_task=self._pair_task,
                description_placeholders={"name": self._tv_name},
            )
        task, self._pair_task = self._pair_task, None
        self._pair_error = ""
        try:
            self._token = task.result()
        except SamstreamAuthError:
            self._pair_error = "pairing_denied"
        except SamstreamTimeoutError:
            self._pair_error = "pairing_timeout"
        except SamstreamConnectionError:
            self._pair_error = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while pairing with %s", self._host)
            self._pair_error = "unknown"
        if self._pair_error:
            return self.async_show_progress_done(next_step_id="pair_failed")
        if self.source == SOURCE_REAUTH:
            return self.async_show_progress_done(next_step_id="finish")
        return self.async_show_progress_done(next_step_id="developer_mode")

    async def async_step_developer_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Guidance: enable Developer Mode so HA can install the Samstream app."""
        if user_input is not None:
            return await self.async_step_local_offer()
        host = ha_lan_host(self.hass) or "?"
        return self.async_show_form(
            step_id="developer_mode",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._tv_name,
                # Show the exact IP (and RTL order for Arabic) to key into the
                # TV's four boxes, so it is never confused with another machine.
                "ha_host": host,
                "ha_host_boxes": ip_boxes(host),
                "ha_host_rtl": ip_boxes(host, reverse=True),
            },
            last_step=False,
        )

    async def async_step_local_offer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer local SmartThings right after pairing (set it up in options)."""
        if user_input is not None:
            if user_input.get("set_up"):
                return await self.async_step_local_control_connect()
            return await self.async_step_finish()
        return self.async_show_form(
            step_id="local_offer",
            data_schema=vol.Schema({vol.Required("set_up", default=False): bool}),
            description_placeholders={"name": self._tv_name},
            last_step=False,
        )

    async def async_step_pair_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain what went wrong and offer another try."""
        # After a progress step HA re-runs the next step with the input that started
        # it (e.g. the host form), so only a submit of *this* form means "retry".
        if user_input is not None and self._retry_form_shown:
            self._retry_form_shown = False
            return await self.async_step_pair()
        self._retry_form_shown = True
        return self.async_show_form(
            step_id="pair_failed",
            errors={"base": self._pair_error},
            description_placeholders={"name": self._tv_name},
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store the token (and what we learned about the TV)."""
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CONF_TOKEN: self._token}
            )
        info = self._info
        if info is None:  # finish is only reached after a successful device_info
            return self.async_abort(reason="unknown")
        data: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_TOKEN: self._token,
            CONF_MAC: info.mac,
            CONF_MODEL: info.model_name,
            CONF_NAME: info.name,
        }
        options: dict[str, Any] = {}
        if self._lc_enabled:
            data |= {CONF_OCF_TOKEN: self._ocf_token, **self._lc_data}
            options[CONF_OCF] = True
            if self._lc_welcome:
                data[CONF_OCF_WELCOME] = True
            self._lc_holding = False  # the new entry adopts the TV's connection
        return self.async_create_entry(title=info.name, data=data, options=options)

    # Local control during first-time setup: no entry yet, the cloud holds the TV.
    def _lc_host(self) -> str:
        return self._host

    def _lc_name(self) -> str:
        return self._tv_name

    def _lc_token(self) -> str:
        return self._ocf_token

    def _lc_key(self) -> str:
        return self.flow_id

    async def _lc_prepare(self) -> bool:
        service = async_get_service(self.hass)
        await service.async_load()
        if service.cis() is None:
            return False
        if not self._lc_holding:
            await service.async_hold(self.flow_id, self._ocf_token)
            self._lc_holding = True
        return True

    def _lc_store(self, updates: dict[str, Any]) -> None:
        self._lc_data.update(updates)

    def _lc_trouble_menu(self) -> list[str]:
        return ["local_control_connect", "local_control_lan", "local_control_skip"]

    async def async_step_local_control_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paired: show the success screen, then add the TV with local control."""
        if user_input is not None and self._lc_done_shown:
            self._lc_enabled = self._lc_welcome = True
            return await self.async_step_finish()
        self._lc_done_shown = True
        return self.async_show_form(
            step_id="local_control_done",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._tv_name},
        )

    async def async_step_local_control_skip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the TV now; keep local control on if the TV was onboarded."""
        self._lc_enabled = self._lc_onboarded
        return await self.async_step_finish()

    @callback
    def async_remove(self) -> None:
        """Stop holding the TV in the cloud when setup is abandoned."""
        if self._lc_holding:
            async_get_service(self.hass).async_release_hold(self.flow_id)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start pairing again because the TV no longer accepts our token."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to be at the TV before pairing again."""
        if user_input is not None:
            return await self.async_step_pair()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"name": self._tv_name},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the TV's address; it must still be the same TV."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            info, error = await self._async_read_device_info()
            if info is None:
                errors["base"] = error or "unknown"
            else:
                await self.async_set_unique_id(info.uuid)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: self._host}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )

    @property
    def _tv_name(self) -> str:
        if self._info:
            return self._info.name
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry().title
        return self._host

    def _client(self) -> SamsungTV:
        # Never send a stored token here: during reauth it is the revoked one, and
        # connecting without a token is what makes the TV show a fresh popup.
        return SamsungTV(self._host, async_get_clientsession(self.hass))

    async def _async_read_device_info(self) -> tuple[DeviceInfo | None, str | None]:
        """Return (info, None), or (None, error key) when the TV does not answer."""
        try:
            self._info = await self._client().device_info()
        except SamstreamConnectionError:
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error reading %s", self._host)
            return None, "unknown"
        return self._info, None

    async def _async_pair(self) -> str | None:
        return await self._client().pair()


class SamstreamOptionsFlow(_LocalControlSteps, OptionsFlow):
    """Network options and app signing."""

    def __init__(self) -> None:
        """Start without a sign-in in progress."""
        self._sign_in: PendingSignIn | None = None
        self._sign_in_task: asyncio.Task[SigningSetup] | None = None
        self._paste_state = ""
        self._setup: SigningSetup | None = None
        self._error = ""
        self._retry_form_shown = False
        self._voice_webhook = ""
        self._ocf_token = ""
        self._reconnect_task: asyncio.Task[bool] | None = None
        self._lc_init()

    @callback
    def async_remove(self) -> None:
        """Stop a pending sign-in when the flow is closed (invalidates the code)."""
        if self._sign_in_task is not None:
            self._sign_in_task.cancel()
        if self._sign_in is not None:
            cancel_sign_in(self.hass, self._sign_in)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "tv_app",
                "network",
                "voice_bridge",
                "local_control",
                "app_signing",
            ],
        )

    async def async_step_tv_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Language, theme and automatic updates of the Samstream app on the TV."""
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        options = self.config_entry.options
        fields: dict[Any, Any] = {}
        if _is_frame(self.config_entry):
            fields[
                vol.Required(
                    CONF_FRAME_POWER, default=options.get(CONF_FRAME_POWER, "art")
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=list(FRAME_POWER_MODES),
                    translation_key=CONF_FRAME_POWER,
                    mode=SelectSelectorMode.LIST,
                )
            )
        return self.async_show_form(
            step_id="tv_app",
            data_schema=vol.Schema(
                {
                    **fields,
                    vol.Required(
                        CONF_LANGUAGE,
                        default=options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(LANGUAGES),
                            translation_key=CONF_LANGUAGE,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_THEME, default=options.get(CONF_THEME, DEFAULT_THEME)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(THEMES),
                            translation_key=CONF_THEME,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_TV_CORNER,
                        default=options.get(CONF_TV_CORNER, DEFAULT_TV_CORNER),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(CORNERS),
                            translation_key=CONF_TV_CORNER,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_RESUME, default=options.get(CONF_RESUME, True)
                    ): bool,
                    vol.Required(
                        CONF_AUTO_UPDATE, default=options.get(CONF_AUTO_UPDATE, True)
                    ): bool,
                }
            ),
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where Wake-on-LAN packets go (the apps come from the TV itself)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            target = user_input[CONF_WOL_TARGET].strip()
            try:
                ipaddress.IPv4Address(target)
            except ValueError:
                errors[CONF_WOL_TARGET] = "invalid_address"
            else:
                # Drop any stored extra-app IDs: Developer Mode lists every app.
                options = {
                    key: value
                    for key, value in self.config_entry.options.items()
                    if key != CONF_EXTRA_APPS
                }
                return self.async_create_entry(
                    data={**options, CONF_WOL_TARGET: target}
                )
        current = self.config_entry.options.get(CONF_WOL_TARGET) or default_wol_target(
            self.config_entry.data[CONF_HOST]
        )
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema(
                {vol.Required(CONF_WOL_TARGET, default=current): str}
            ),
            errors=errors,
        )

    async def async_step_voice_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Turn the voice webhook on and show its (secret) address."""
        options = self.config_entry.options
        webhook_id = options.get(CONF_VOICE_WEBHOOK) or self._voice_webhook
        if not webhook_id:
            self._voice_webhook = webhook.async_generate_id()
            webhook_id = self._voice_webhook
        if user_input is not None:
            return self.async_create_entry(
                data={**options, **user_input, CONF_VOICE_WEBHOOK: webhook_id}
            )
        return self.async_show_form(
            step_id="voice_bridge",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_VOICE, default=options.get(CONF_VOICE, False)
                    ): bool,
                    vol.Required(
                        CONF_VOICE_SHOW, default=options.get(CONF_VOICE_SHOW, True)
                    ): bool,
                }
            ),
            description_placeholders={"url": voice_webhook_url(self.hass, webhook_id)},
        )

    async def async_step_local_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Intro: local control vs SmartThings, and the way back."""
        menu = ["local_control_settings"]
        if self.config_entry.options.get(CONF_OCF):
            menu += ["local_control_reconnect", "local_control_release"]
        return self.async_show_menu(step_id="local_control", menu_options=menu)

    async def async_step_local_control_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the cloud the TV will dial, then start it so the TV can connect."""
        service = async_get_service(self.hass)
        settings = await service.async_load()
        entry = self.config_entry
        token = entry.data.get(CONF_OCF_TOKEN) or self._ocf_token or new_token()
        self._ocf_token = token
        errors: dict[str, str] = {}
        if user_input is not None:
            new_settings, error = await self._async_cloud_settings(settings, user_input)
            token = str(user_input.get(CONF_OCF_TOKEN, "")).strip()
            if error:
                errors["base"] = error
            elif len(token) < MIN_OCF_TOKEN:
                errors[CONF_OCF_TOKEN] = "token_too_short"
            else:
                self._ocf_token = token
                if new_settings != settings:
                    await service.async_save(new_settings)
                # Turn local control on now, so the cloud is listening while the
                # user runs the onboarding tool and the TV dials in.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_OCF_TOKEN: token},
                    options={**entry.options, CONF_OCF: True},
                )
                return await self.async_step_local_control_connect()
        return self.async_show_form(
            step_id="local_control_settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OCF_TOKEN, default=token): TextSelector(),
                    vol.Required(CONF_OCF_PORT, default=settings.port): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Optional(
                        CONF_OCF_HOST,
                        description={"suggested_value": settings.host or ""},
                    ): str,
                    vol.Optional("import_cloud"): section(
                        vol.Schema(
                            {
                                vol.Optional("cloud_uuid"): str,
                                vol.Optional("ca_certificate"): TextSelector(
                                    TextSelectorConfig(multiline=True)
                                ),
                                vol.Optional("ca_key"): TextSelector(
                                    TextSelectorConfig(multiline=True)
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "address": service.cis() or "-",
                "cloud_uuid": settings.identity.cloud_uuid,
            },
        )

    def _lc_host(self) -> str:
        return str(self.config_entry.data[CONF_HOST])

    def _lc_name(self) -> str:
        return self.config_entry.title

    def _lc_token(self) -> str:
        return str(self.config_entry.data.get(CONF_OCF_TOKEN) or self._ocf_token)

    def _lc_key(self) -> str:
        return self.config_entry.entry_id

    async def _lc_prepare(self) -> bool:
        service = async_get_service(self.hass)
        await service.async_load()
        return service.cis() is not None

    def _lc_store(self, updates: dict[str, Any]) -> None:
        entry = self.config_entry
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **updates}
        )

    def _lc_trouble_menu(self) -> list[str]:
        return [
            "local_control_connect",
            "local_control_lan",
            "local_control_settings",
        ]

    async def async_step_local_control_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paired — show the success screen and finish."""
        if user_input is not None and self._lc_done_shown:
            entry = self.config_entry
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_OCF_WELCOME: True}
            )
            return self.async_create_entry(data={**entry.options})
        self._lc_done_shown = True
        return self.async_show_form(
            step_id="local_control_done",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self.config_entry.title},
        )

    async def async_step_local_control_reconnect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Restart the TV's SmartThings service: it re-dials Home Assistant.

        For a TV that stopped reporting. The TV asks on screen to allow it.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="local_control_reconnect",
                data_schema=vol.Schema({}),
                description_placeholders={"name": self.config_entry.title},
            )
        self._reconnect_task = None
        return await self.async_step_local_control_reconnect_wait()

    async def async_step_local_control_reconnect_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for the TV to come back after the restart."""
        if self._reconnect_task is None:
            self._reconnect_task = self.hass.async_create_task(self._run_reconnect())
        if not self._reconnect_task.done():
            return self.async_show_progress(
                step_id="local_control_reconnect_wait",
                progress_action="reconnecting",
                progress_task=self._reconnect_task,
                description_placeholders={"name": self.config_entry.title},
            )
        back = self._reconnect_task.result()
        self._reconnect_task = None
        return self.async_show_progress_done(
            next_step_id="local_control_reconnected"
            if back
            else "local_control_trouble"
        )

    async def _run_reconnect(self) -> bool:
        """Send the restart; True once the TV has dialed back in."""
        device: CloudDevice | None = (
            self.config_entry.runtime_data.coordinator.ocf_device
        )
        if device is None:
            return False
        try:
            if not await device.wait_connected(RECONNECT_WAIT):
                return False
            await device.restart_agent()
        except OcfError:
            return False
        # It goes away while restarting, then dials in again once allowed.
        await asyncio.sleep(RESTART_SETTLE)
        return await device.wait_connected(RECONNECT_ALLOW_WAIT)

    async def async_step_local_control_reconnected(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Back: the paired screen, then close."""
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options})
        return self.async_show_form(
            step_id="local_control_reconnected",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self.config_entry.title},
        )

    async def async_step_local_control_release(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hand the TV back to SmartThings and turn local control off.

        If the onboarding credential was pasted in, release it here; otherwise
        the user releases it from the LAN tool (the screen explains this).
        """
        entry = self.config_entry
        if user_input is not None:
            settings = await async_get_service(self.hass).async_load()
            owner = entry.data.get(CONF_OCF_OWNER_PSK)
            if owner:
                try:
                    await self.hass.async_add_executor_job(
                        partial(
                            release_tv,
                            entry.data[CONF_HOST],
                            settings.obt_uuid,
                            owner,
                            entry.data.get(CONF_OCF_SECURE_PORT),
                        )
                    )
                except OcfError as err:
                    # Local control is still turned off below: nothing more to
                    # do from this flow, but a swallowed failure here would
                    # leave the TV believing it is still owned by this Home
                    # Assistant with no way back short of a TV-side reset.
                    _LOGGER.warning(
                        "Local control: could not confirm %s released ownership: %s",
                        entry.data[CONF_HOST],
                        err,
                    )
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"{ISSUE_OCF_RELEASE}_{entry.entry_id}",
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key=ISSUE_OCF_RELEASE,
                        translation_placeholders={"name": entry.title},
                    )
            return self.async_create_entry(data={**entry.options, CONF_OCF: False})
        return self.async_show_form(
            step_id="local_control_release",
            data_schema=vol.Schema({}),
            description_placeholders={"tv_ip": entry.data[CONF_HOST]},
        )

    async def _async_cloud_settings(
        self, settings: CloudSettings, user_input: dict[str, Any]
    ) -> tuple[CloudSettings, str | None]:
        """Build the cloud settings the form asks for, or return an error key."""
        identity = settings.identity
        imported = user_input.get("import_cloud") or {}
        if any(str(value).strip() for value in imported.values()):
            try:
                identity = await self.hass.async_add_executor_job(
                    load_identity,
                    str(imported.get("ca_certificate", "")).strip().encode(),
                    str(imported.get("ca_key", "")).strip().encode(),
                    str(imported.get("cloud_uuid", "")).strip(),
                )
            except ValueError, TypeError, UnsupportedAlgorithm:
                return settings, "invalid_cloud_identity"
        host = str(user_input.get(CONF_OCF_HOST) or "").strip() or None
        return CloudSettings(identity, int(user_input[CONF_OCF_PORT]), host), None

    async def async_step_app_signing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the signing status; offer Samsung sign-in or certificate import."""
        setup = await async_load_signing(self.hass)
        return self.async_show_menu(
            step_id="app_signing",
            menu_options=["samsung_sign_in", "samsung_paste", "import_certificates"],
            description_placeholders={"status": _signing_status(setup)},
        )

    async def async_step_samsung_sign_in(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait while the user signs in through `npx samstream-signin`."""
        if self._sign_in_task is None:
            self._sign_in = start_sign_in(self.hass)
            self._sign_in_task = self.hass.async_create_task(
                self._async_sign_in(self._sign_in)
            )
        pending = self._sign_in
        if pending is None:  # set together with the task just above
            return self.async_abort(reason="unknown")
        if not self._sign_in_task.done():
            return self.async_show_progress(
                step_id="samsung_sign_in",
                progress_action="samsung_sign_in",
                progress_task=self._sign_in_task,
                description_placeholders={
                    "command": helper_command(self.hass, pending.code)
                },
            )
        task, self._sign_in_task = self._sign_in_task, None
        cancel_sign_in(self.hass, pending)
        self._error = ""
        try:
            self._setup = task.result()
        except Exception as err:  # noqa: BLE001  # mapped to a form error below
            self._error = _error_key(err)
        if self._error:
            return self.async_show_progress_done(next_step_id="signing_failed")
        return self.async_show_progress_done(next_step_id="signing_done")

    async def async_step_samsung_paste(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in without the helper: paste the `code` from the browser's DevTools."""
        errors: dict[str, str] = {}
        if user_input is not None and self._paste_state:
            try:
                account = parse_callback(
                    callback_body(user_input[CONF_CODE]), self._paste_state
                )
                setup = await async_obtain_samsung_certificates(
                    self.hass, self.config_entry, account
                )
            except Exception as err:  # noqa: BLE001  # mapped to a form error
                errors["base"] = _error_key(err)
            else:
                return self.async_abort(
                    reason="signing_ready",
                    description_placeholders={"status": _signing_status(setup)},
                )
        if not self._paste_state:
            self._paste_state = new_state()
        return self.async_show_form(
            step_id="samsung_paste",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CODE): TextSelector(
                        TextSelectorConfig(multiline=True)
                    )
                }
            ),
            description_placeholders={"url": sign_in_url(self._paste_state)},
            errors=errors,
        )

    async def async_step_signing_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain the failure and offer another sign-in."""
        # HA re-runs the step after a progress step with the input that started it;
        # only a submit of this form means "retry".
        if user_input is not None and self._retry_form_shown:
            self._retry_form_shown = False
            return await self.async_step_samsung_sign_in()
        self._retry_form_shown = True
        return self.async_show_form(
            step_id="signing_failed", errors={"base": self._error}
        )

    async def async_step_signing_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Signing is ready; the options themselves are unchanged."""
        return self.async_abort(
            reason="signing_ready",
            description_placeholders={"status": _signing_status(self._setup)},
        )

    async def async_step_import_certificates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use existing author/distributor .p12 files stored under /config."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                files = (
                    resolve_package_path(self.hass, user_input[CONF_AUTHOR_P12]),
                    resolve_package_path(self.hass, user_input[CONF_DISTRIBUTOR_P12]),
                )
                setup = await async_import_certificates(
                    self.hass, self.config_entry, files, user_input[CONF_PASSWORD]
                )
            except HomeAssistantError as err:
                errors["base"] = err.translation_key or "unknown"
            else:
                return self.async_abort(
                    reason="signing_ready",
                    description_placeholders={"status": _signing_status(setup)},
                )
        return self.async_show_form(
            step_id="import_certificates",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTHOR_P12): str,
                    vol.Required(CONF_DISTRIBUTOR_P12): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_sign_in(self, pending: PendingSignIn) -> SigningSetup:
        async with asyncio.timeout(SIGN_IN_TIMEOUT):
            body = await pending.callback
        account = parse_callback(body, pending.state)
        return await async_obtain_samsung_certificates(
            self.hass, self.config_entry, account
        )


def callback_body(pasted: str) -> str:
    """Accept what users copy from DevTools: the `code` value or the whole payload.

    The whole payload (`code=...&state=...`, any order) is kept as is, so its
    `state` is checked against this sign-in.
    """
    text = pasted.strip()
    if text.startswith("code=") or "&code=" in text:
        return text
    if fields := _devtools_fields(text):
        return urlencode(fields)
    # The bare value, decoded (DevTools "view parsed") or still URL-encoded.
    value = unquote(text) if text.startswith("%7B") else text
    return urlencode({"code": value})


def _devtools_fields(text: str) -> dict[str, str]:
    """Parse DevTools' "Payload" view: `name` and `value` on separate lines.

    Firefox-style `name: value` lines are accepted too.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    index = 0
    while index < len(lines):
        name, sep, value = lines[index].partition(":")
        if sep and name in _CALLBACK_FIELDS and value.strip():
            fields[name] = value.strip()
            index += 1
        elif lines[index] in _CALLBACK_FIELDS and index + 1 < len(lines):
            fields[lines[index]] = lines[index + 1]
            index += 2
        else:
            index += 1
    return fields if "code" in fields else {}


_CALLBACK_FIELDS = ("code", "state")


def _error_key(err: BaseException) -> str:
    if isinstance(err, TimeoutError):
        return "sign_in_timeout"
    if isinstance(err, SamsungCertError):
        return "sign_in_failed"
    if isinstance(err, HomeAssistantError) and err.translation_key:
        return err.translation_key
    _LOGGER.error("Unexpected error during Samsung sign-in", exc_info=err)
    return "unknown"


def _signing_status(setup: SigningSetup | None) -> str:
    if setup is None:
        return "not set up"
    who = f" ({setup.email})" if setup.email else ""
    return (
        f"{setup.source}{who}, {len(setup.duids)} TV(s), "
        f"valid until {setup.expires.date().isoformat()}"
    )


def _is_frame(entry: ConfigEntry) -> bool:
    """Tell whether this is a Frame TV (from its last device info)."""
    runtime = getattr(entry, "runtime_data", None)
    info = (
        runtime.coordinator.data.info if runtime and runtime.coordinator.data else None
    )
    return bool(info and info.frame_tv)
