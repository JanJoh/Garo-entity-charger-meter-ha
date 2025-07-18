import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN

class GaroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Garo Entity Charger Meter", data={}, options=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host"): str,
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Optional("scan_interval", default=15): int,
                vol.Optional("ignore_tls_errors", default=True): bool,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        from .options import GaroOptionsFlowHandler
        return GaroOptionsFlowHandler(config_entry)

