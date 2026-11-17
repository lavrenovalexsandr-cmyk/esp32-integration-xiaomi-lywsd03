"""Config flow for ESP32 Xiaomi LYWSD03MMC."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN, NAME


class Esp32XiaomiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the integration once; gateways are discovered over MQTT."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
