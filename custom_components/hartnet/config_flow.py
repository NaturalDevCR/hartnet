"""Configure the app connection entirely from Home Assistant's UI."""

from ipaddress import IPv4Address

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import HartNetClient


def ipv4(value):
    try:
        return str(IPv4Address(value))
    except ValueError as err:
        raise vol.Invalid("IPv4 requerida") from err


class HartNetConfigFlow(config_entries.ConfigFlow, domain="hartnet"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                ipv4(user_input["host"])
                client = HartNetClient(async_get_clientsession(self.hass), **user_input)
                info = await client.request("info")
                await self.async_set_unique_id(info["id"])
                self._abort_if_unique_id_configured()
            except (ClientError, TimeoutError, ValueError, KeyError, vol.Invalid):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="HartNet", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default="127.0.0.1"): str,
                    vol.Required("port", default=8099): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Required("token"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        errors = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                ipv4(user_input["host"])
                client = HartNetClient(async_get_clientsession(self.hass), **user_input)
                info = await client.request("info")
                if info["id"] != entry.unique_id:
                    errors["base"] = "wrong_app"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=user_input)
            except (ClientError, TimeoutError, ValueError, KeyError, vol.Invalid):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=entry.data["host"]): str,
                    vol.Required("port", default=entry.data["port"]): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Required("token"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )
