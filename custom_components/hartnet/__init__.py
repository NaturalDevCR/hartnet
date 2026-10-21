"""Native entities for the independent HartNet Art-Net engine."""

from datetime import timedelta

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HartNetClient

DOMAIN = "hartnet"
PLATFORMS = ["light", "number", "select", "switch"]


class HartNetCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        import logging

        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=entry,
            name="HartNet",
            update_interval=timedelta(seconds=2),
        )
        self.client = HartNetClient(async_get_clientsession(hass), **entry.data)

    async def _async_update_data(self):
        try:
            return await self.client.request("state")
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed("No se pudo conectar con la app HartNet") from err

    async def command(self, fixture_id, command):
        from homeassistant.exceptions import HomeAssistantError

        try:
            state = await self.client.request(f"fixtures/{fixture_id}/command", command)
        except (ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError("La app HartNet rechazó el comando") from err
        self.async_set_updated_data(state)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HartNetCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
