"""Oppsett i Home Assistant: én oppføring per agent (navn, adresse, port, token)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import DiskmapAuthError, DiskmapClient, DiskmapError
from .const import CONF_SCAN_INTERVAL, CONF_TOKEN, CONF_TOP_SENSORS, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DEFAULT_TOP_SENSORS, DOMAIN

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
PORT = vol.All(vol.Coerce(int), vol.Range(1, 65535))


async def _check(hass: HomeAssistant, host: str, port: int, token: str) -> tuple[dict | None, str | None]:
    """Prøver /api/info. Gir (info, None) eller (None, feilnøkkel)."""
    try:
        return await DiskmapClient(async_get_clientsession(hass), host, port, token).info(), None
    except DiskmapAuthError:
        return None, "invalid_auth"
    except DiskmapError:
        return None, "cannot_connect"


class DiskmapConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]})
            info, err = await _check(self.hass, user_input[CONF_HOST], user_input[CONF_PORT], user_input[CONF_TOKEN])
            if err:
                errors["base"] = err
            else:
                name = user_input.get(CONF_NAME) or info.get("name") or user_input[CONF_HOST]
                data = {k: user_input[k] for k in (CONF_HOST, CONF_PORT, CONF_TOKEN)}
                return self.async_create_entry(title=name, data=data)
        schema = vol.Schema({
            vol.Optional(CONF_NAME): str,
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): PORT,
            vol.Required(CONF_TOKEN): PASSWORD,
        })
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ny IP-adresse, port eller token uten å slette oppføringen (sensorene og historikken beholdes)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input.get(CONF_TOKEN) or entry.data[CONF_TOKEN]  # tomt felt = behold tokenet
            _, err = await _check(self.hass, user_input[CONF_HOST], user_input[CONF_PORT], token)
            if err:
                errors["base"] = err
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT], CONF_TOKEN: token})
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
            vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): PORT,
            vol.Optional(CONF_TOKEN): PASSWORD,
        })
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Agenten har fått nytt token: be om det nye."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _, err = await _check(self.hass, entry.data[CONF_HOST], entry.data[CONF_PORT], user_input[CONF_TOKEN])
            if err:
                errors["base"] = err
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]})
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_TOKEN): PASSWORD}),
                                    errors=errors, description_placeholders={"name": entry.title})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DiskmapOptionsFlow()


class DiskmapOptionsFlow(OptionsFlow):
    """Hvor ofte HA spør agenten, og hvor mange toppmapper som blir sensorer."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=60, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)),
            vol.Required(CONF_TOP_SENSORS, default=o.get(CONF_TOP_SENSORS, DEFAULT_TOP_SENSORS)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=40, step=1, mode=selector.NumberSelectorMode.BOX)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
