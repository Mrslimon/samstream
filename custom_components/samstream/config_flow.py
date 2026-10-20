"""Config flow for Samstream: find the TV, then pair once (the TV shows "Allow")."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiosamstream import (
    DeviceInfo,
    SamstreamAuthError,
    SamstreamConnectionError,
    SamstreamTimeoutError,
    SamsungTV,
)
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_MODEL, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_EXTRA_APPS, CONF_TOKEN, CONF_WOL_TARGET, DOMAIN
from .coordinator import default_wol_target, parse_app_ids

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
    """Wake-on-LAN address and extra app IDs."""

    async def async_step_init(
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
                    data={CONF_WOL_TARGET: target, CONF_EXTRA_APPS: extra}
                )
        current = self.config_entry.options.get(CONF_WOL_TARGET) or default_wol_target(
            self.config_entry.data[CONF_HOST]
        )
        return self.async_show_form(
            step_id="init",
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
