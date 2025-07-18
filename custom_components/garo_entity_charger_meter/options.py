import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN

class GaroOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self.config_entry.data
        options = self.config_entry.options

        def get(key, default):
            return options.get(key, data.get(key, default))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("host", default=get("host", "")): str,
                vol.Required("username", default=get("username", "")): str,
                vol.Required("password", default=get("password", "")): str,
                vol.Optional("scan_interval", default=get("scan_interval", 15)): int,
                vol.Optional("ignore_tls_errors", default=get("ignore_tls_errors", True)): bool,
            }),
        )

@callback
def async_get_options_flow(config_entry):
    return GaroOptionsFlowHandler(config_entry)

