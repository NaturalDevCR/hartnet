"""Stable identifiers, fixture devices and dynamic entity creation."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

DOMAIN = "hartnet"
LIGHT_KINDS = {"dimmer", "red", "green", "blue", "white", "cold_white", "warm_white"}


def descriptors(data, platform):
    project = data["project"]
    profiles = {p["id"]: p for p in project["profiles"]}
    for fixture in project["fixtures"]:
        profile = profiles[fixture["profile_id"]]
        if platform == "light" and any(c["kind"] in LIGHT_KINDS for c in profile["controls"]):
            yield fixture, profile, None
        for control in profile["controls"]:
            if control["kind"] == platform:
                yield fixture, profile, control


async def setup_entities(hass, entry, async_add_entities, platform, cls):
    coordinator = entry.runtime_data
    known = set()

    def update():
        added = []
        for fixture, profile, control in descriptors(coordinator.data, platform):
            key = fixture["id"], control["id"] if control else "light"
            if key in known:
                continue
            known.add(key)
            added.append(cls(coordinator, entry, fixture, profile, control))
        if added:
            async_add_entities(added)

    update()
    entry.async_on_unload(coordinator.async_add_listener(update))


class HartNetEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(self, coordinator, entry, fixture, profile, control=None):
        super().__init__(coordinator)
        self.fixture_id, self.control_id = fixture["id"], control["id"] if control else None
        self.profile, self.control = profile, control
        self._attr_unique_id = f"{entry.unique_id}:{fixture['id']}:{self.control_id or 'light'}"
        self._attr_name = control["name"] if control else None
        editable = [c for c in profile["controls"] if c["kind"] != "constant"]
        if control and len(editable) == 1:
            self._attr_name = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.unique_id}:{fixture['id']}")},
            name=fixture["name"],
            manufacturer=profile.get("manufacturer") or "Art-Net",
            model=profile.get("model") or profile["name"],
        )

    @property
    def available(self):
        if not super().available or not self.coordinator.data.get("output_enabled"):
            return False
        return any(
            f["id"] == self.fixture_id
            and (self.control_id is None or any(c["id"] == self.control_id for c in p["controls"]))
            for f in self.coordinator.data["project"]["fixtures"]
            for p in self.coordinator.data["project"]["profiles"]
            if p["id"] == f["profile_id"] and p == self.profile
        )

    @property
    def fixture_state(self):
        return self.coordinator.data["states"].get(self.fixture_id, {})

    @property
    def control_value(self):
        return self.fixture_state.get("values", {}).get(self.control_id)

    async def set_control_value(self, value):
        await self.coordinator.command(self.fixture_id, {"values": {self.control_id: value}})
