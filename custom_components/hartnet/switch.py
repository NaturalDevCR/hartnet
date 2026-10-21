"""Two-state DMX controls with explicit minimum/maximum values."""

from homeassistant.components.switch import SwitchEntity

from .entity import HartNetEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_entities(hass, entry, async_add_entities, "switch", HartNetSwitch)


class HartNetSwitch(HartNetEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.control_value == self.control.get("max", 256 ** len(self.control["slots"]) - 1)

    async def async_turn_on(self, **kwargs):
        await self.set_control_value(self.control.get("max", 256 ** len(self.control["slots"]) - 1))

    async def async_turn_off(self, **kwargs):
        await self.set_control_value(self.control.get("min", 0))
