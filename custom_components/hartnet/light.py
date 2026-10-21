"""Native dimmer / RGB / RGBW / RGBWW entities."""

from homeassistant.components.light import ColorMode, LightEntity, LightEntityFeature

from .entity import HartNetEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_entities(hass, entry, async_add_entities, "light", HartNetLight)


class HartNetLight(HartNetEntity, LightEntity):
    _attr_supported_features = LightEntityFeature.TRANSITION

    def __init__(self, *args):
        super().__init__(*args)
        kinds = {c["kind"] for c in self.profile["controls"]}
        if "red" in kinds:
            mode = (
                ColorMode.RGBWW
                if "cold_white" in kinds
                else ColorMode.RGBW
                if "white" in kinds
                else ColorMode.RGB
            )
        elif "cold_white" in kinds:
            mode = ColorMode.COLOR_TEMP
        else:
            mode = ColorMode.BRIGHTNESS
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}
        self._attr_min_color_temp_kelvin = self.profile.get("min_kelvin", 2700)
        self._attr_max_color_temp_kelvin = self.profile.get("max_kelvin", 6500)

    @property
    def is_on(self):
        return self.fixture_state.get("on", False)

    @property
    def brightness(self):
        return self.fixture_state.get("brightness", 255)

    @property
    def rgb_color(self):
        return tuple(self.fixture_state.get("color", [])[:3]) if self.color_mode == ColorMode.RGB else None

    @property
    def rgbw_color(self):
        return tuple(self.fixture_state.get("color", [])) if self.color_mode == ColorMode.RGBW else None

    @property
    def rgbww_color(self):
        return tuple(self.fixture_state.get("color", [])) if self.color_mode == ColorMode.RGBWW else None

    @property
    def color_temp_kelvin(self):
        colors = self.fixture_state.get("color", [])
        if self.color_mode != ColorMode.COLOR_TEMP or len(colors) != 2:
            return None
        cold, warm = colors
        ratio = cold / (cold + warm) if cold + warm else 0.5
        return round(
            self.min_color_temp_kelvin + ratio * (self.max_color_temp_kelvin - self.min_color_temp_kelvin)
        )

    async def async_turn_on(self, **kwargs):
        command = {"on": True, "transition": kwargs.get("transition", 0)}
        if "brightness" in kwargs:
            command["brightness"] = kwargs["brightness"]
        for field in ("rgb_color", "rgbw_color", "rgbww_color"):
            if field in kwargs:
                command["color"] = list(kwargs[field])
        if "color_temp_kelvin" in kwargs and self.color_mode == ColorMode.COLOR_TEMP:
            ratio = max(
                0,
                min(
                    1,
                    (kwargs["color_temp_kelvin"] - self.min_color_temp_kelvin)
                    / (self.max_color_temp_kelvin - self.min_color_temp_kelvin),
                ),
            )
            command["color"] = [round(255 * ratio), round(255 * (1 - ratio))]
        await self.coordinator.command(self.fixture_id, command)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command(
            self.fixture_id, {"on": False, "transition": kwargs.get("transition", 0)}
        )
