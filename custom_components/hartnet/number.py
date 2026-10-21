"""Arbitrary numeric attributes, e.g. speed, pan, tilt or raw macros."""

from homeassistant.components.number import NumberEntity, NumberMode

from .entity import HartNetEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_entities(hass, entry, async_add_entities, "number", HartNetNumber)


class HartNetNumber(HartNetEntity, NumberEntity):
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, *args):
        super().__init__(*args)
        self._attr_native_min_value = self.control.get("min", 0)
        self._attr_native_max_value = self.control.get("max", 256 ** len(self.control["slots"]) - 1)
        self._attr_native_unit_of_measurement = self.control.get("unit") or None

    @property
    def native_value(self):
        return self.control_value

    async def async_set_native_value(self, value):
        await self.set_control_value(round(value))
