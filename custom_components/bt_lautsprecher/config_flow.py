"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .bluez import adapter_liste
from .const import CONF_ADAPTER, CONF_AUTO_RECONNECT, CONF_DEFAULT_OUTPUT, CONF_KEEPALIVE_NOISE, DOMAIN


class BtLautsprecherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Adapter auswählen."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        try:
            adapter = await adapter_liste()
        except Exception:  # noqa: BLE001
            adapter = {}
        if not adapter:
            return self.async_abort(reason="no_adapter")
        if user_input is not None:
            pfad = user_input[CONF_ADAPTER]
            await self.async_set_unique_id(adapter[pfad]["adresse"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Bluetooth-Lautsprecher ({adapter[pfad]['name']})", data={CONF_ADAPTER: pfad}
            )
        auswahl = {pfad: f"{a['name']} ({a['adresse']})" for pfad, a in adapter.items()}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADAPTER, default=next(iter(auswahl))): vol.In(auswahl)}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BtLautsprecherOptionsFlow()


class BtLautsprecherOptionsFlow(OptionsFlow):
    """Optionen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        optionen = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTO_RECONNECT, default=optionen.get(CONF_AUTO_RECONNECT, True)): bool,
                    vol.Required(CONF_DEFAULT_OUTPUT, default=optionen.get(CONF_DEFAULT_OUTPUT, True)): bool,
                    vol.Required(CONF_KEEPALIVE_NOISE, default=optionen.get(CONF_KEEPALIVE_NOISE, False)): bool,
                }
            ),
        )
