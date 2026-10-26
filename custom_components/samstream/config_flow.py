"""Config flow for Samstream: find the TV, then pair once (the TV shows "Allow")."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlencode, urlparse

import voluptuous as vol
from aiosamstream import (
    DeviceInfo,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
    SamsungTV,
)
from aiosamstream.samsung_cert import (
    SamsungCertError,
    new_state,
    parse_callback,
    sign_in_url,
)
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
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
from homeassistant.exceptions import HomeAssistantError
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
    CONF_RESUME,
    CONF_THEME,
    CONF_TOKEN,
    CONF_TV_CORNER,
    CONF_WOL_TARGET,
    CORNERS,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    DEFAULT_TV_CORNER,
    DOMAIN,
    FRAME_POWER_MODES,
    LANGUAGES,
    THEMES,
)
from .coordinator import default_wol_target, parse_app_ids
from .installer import (
    async_import_certificates,
    async_obtain_samsung_certificates,
    resolve_package_path,
)
from .signin import (
    SIGN_IN_TIMEOUT,
    PendingSignIn,
    cancel_sign_in,
    helper_command,
    start_sign_in,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class SamstreamConfigFlow(ConfigFlow, domain=DOMAIN):
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
        return self.async_show_progress_done(next_step_id="finish")

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
        return self.async_create_entry(
            title=info.name,
            data={
                CONF_HOST: self._host,
                CONF_TOKEN: self._token,
                CONF_MAC: info.mac,
                CONF_MODEL: info.model_name,
                CONF_NAME: info.name,
            },
        )

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


class SamstreamOptionsFlow(OptionsFlow):
    """Network options and app signing."""

    def __init__(self) -> None:
        """Start without a sign-in in progress."""
        self._sign_in: PendingSignIn | None = None
        self._sign_in_task: asyncio.Task[SigningSetup] | None = None
        self._paste_state = ""
        self._setup: SigningSetup | None = None
        self._error = ""
        self._retry_form_shown = False

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
            step_id="init", menu_options=["tv_app", "network", "app_signing"]
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
        """Ask for the Wake-on-LAN target and apps missing from the catalog."""
        errors: dict[str, str] = {}
        if user_input is not None:
            target = user_input[CONF_WOL_TARGET].strip()
            try:
                ipaddress.IPv4Address(target)
            except ValueError:
                errors[CONF_WOL_TARGET] = "invalid_address"
            else:
                extra = " ".join(parse_app_ids(user_input.get(CONF_EXTRA_APPS, "")))
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_WOL_TARGET: target,
                        CONF_EXTRA_APPS: extra,
                    }
                )
        current = self.config_entry.options.get(CONF_WOL_TARGET) or default_wol_target(
            self.config_entry.data[CONF_HOST]
        )
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_WOL_TARGET, default=current): str,
                    vol.Optional(
                        CONF_EXTRA_APPS,
                        default=self.config_entry.options.get(CONF_EXTRA_APPS, ""),
                    ): str,
                }
            ),
            errors=errors,
        )

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
