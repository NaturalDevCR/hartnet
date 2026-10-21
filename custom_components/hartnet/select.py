"""Explicit named values for documented macro ranges."""

from homeassistant.components.select import SelectEntity

from .entity import HartNetEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_entities(hass, entry, async_add_entities, "select", HartNetSelect)


class HartNetSelect(HartNetEntity, SelectEntity):
    def __init__(self, *args):
        super().__init__(*args)
        self._attr_options = [o["label"] for o in self.control["options"]]

    @property
    def current_option(self):
        return next((o["label"] for o in self.control["options"] if o["value"] == self.control_value), None)

    async def async_select_option(self, option):
        value = next(o["value"] for o in self.control["options"] if o["label"] == option)
        await self.set_control_value(value)
