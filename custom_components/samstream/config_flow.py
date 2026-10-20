"""Config flow for Samstream."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class SamstreamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Samstream."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV host. Pairing is added in milestone 4."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
