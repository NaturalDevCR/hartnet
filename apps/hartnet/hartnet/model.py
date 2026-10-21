"""Portable profiles and installation-specific patch validation.

Slot numbers are one-based, ordered most-significant byte first. They need
not be adjacent (e.g. pan coarse at 1 and pan fine at 8).
"""

import re
from copy import deepcopy
from ipaddress import IPv4Address
from uuid import uuid4

KINDS = {
    "dimmer",
    "red",
    "green",
    "blue",
    "white",
    "cold_white",
    "warm_white",
    "number",
    "switch",
    "select",
    "constant",
}
CURVES = {"linear": 1, "quadratic": 2, "cubic": 3, "quadruple": 4}


class ValidationError(ValueError):
    """An invalid user-supplied profile, patch, or command."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f"{label}: integer between {low} and {high}")


def name(value, label):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 160, f"{label}: text of 1–160 characters")


def keys(value, allowed, label):
    require(isinstance(value, dict), f"{label}: expected an object")
    require(
        not set(value) - set(allowed.split()),
        f"{label}: unknown fields {set(value) - set(allowed.split())}",
    )


def unique(items, label):
    ids = []
    for item in items:
        require(isinstance(item, dict), f"{label}: expected an object")
        name(item.get("id"), f"{label}.id")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", item["id"]), f"{label}.id: invalid characters")
        ids.append(item["id"])
    require(len(ids) == len(set(ids)), f"{label}: duplicate IDs")


def validate_profile(profile):
    keys(profile, "id name manufacturer model mode controls attribution min_kelvin max_kelvin", "profile")
    name(profile.get("id"), "profile.id")
    name(profile.get("name"), "profile.name")
    for field in ("manufacturer", "model", "mode", "attribution"):
        require(isinstance(profile.get(field, ""), str), f"profile.{field}: text required")
    integer(profile.get("min_kelvin", 2700), 1000, 20000, "min_kelvin")
    integer(profile.get("max_kelvin", 6500), profile.get("min_kelvin", 2700) + 1, 30000, "max_kelvin")
    controls = profile.get("controls")
    require(isinstance(controls, list) and 1 <= len(controls) <= 512, "profile: 1–512 controls required")
    unique(controls, "controls")
    used = set()
    colors = []
    for control in controls:
        keys(
            control,
            "id name kind slots default off_value min max options curve unit scale_by_brightness",
            "control",
        )
        name(control.get("name"), "control.name")
        kind = control.get("kind")
        require(isinstance(kind, str) and kind in KINDS, "invalid control.kind")
        slots = control.get("slots")
        require(isinstance(slots, list) and 1 <= len(slots) <= 4, "control.slots: 1–4 bytes")
        for slot in slots:
            integer(slot, 1, 512, "slot")
            require(slot not in used, f"Slot {slot} used more than once")
            used.add(slot)
        maximum = 256 ** len(slots) - 1
        for field in ("default", "off_value"):
            integer(control.get(field, 0), 0, maximum, field)
        low, high = control.get("min", 0), control.get("max", maximum)
        integer(low, 0, maximum, "min")
        integer(high, low, maximum, "max")
        if kind in {"number", "select", "switch"}:
            integer(control.get("default", 0), low, high, "default")
            require(control.get("curve", "linear") == "linear", "Curves only apply to light functions")
        if kind == "switch":
            require(control.get("default", 0) in (low, high), "switch.default requires minimum or maximum")
        require(control.get("curve", "linear") in CURVES, "Invalid curve")
        require(isinstance(control.get("unit", ""), str), "unit: text required")
        require(
            type(control.get("scale_by_brightness", True)) is bool, "scale_by_brightness: boolean required"
        )
        if kind in {"dimmer", "red", "green", "blue", "white", "cold_white", "warm_white"}:
            require(kind not in colors, f"Duplicate light function: {kind}")
            colors.append(kind)
        if kind == "select":
            options = control.get("options")
            require(isinstance(options, list) and 1 <= len(options) <= 256, "select: options required")
            labels = set()
            values = set()
            for option in options:
                keys(option, "label value", "option")
                name(option.get("label"), "option.label")
                integer(option.get("value"), low, high, "option.value")
                require(option["label"] not in labels and option["value"] not in values, "Duplicate options")
                labels.add(option["label"])
                values.add(option["value"])
            require(control.get("default", 0) in values, "select: default must match an option")
        else:
            require("options" not in control, "Only select supports options")
    rgb = set(colors) & {"red", "green", "blue"}
    require(not rgb or rgb == {"red", "green", "blue"}, "RGB requires red, green and blue")
    whites = set(colors) & {"cold_white", "warm_white"}
    require(not whites or whites == {"cold_white", "warm_white"}, "CCT requires both whites")
    require(not ("white" in colors and whites), "Use RGBW or RGBWW without mixing white and CCT")
    return deepcopy(profile)


def validate_project(project):
    keys(project, "schema_version id nodes profiles fixtures", "project")
    integer(project.get("schema_version"), 1, 1, "schema_version")
    name(project.get("id"), "project.id")
    for field, limit in (("nodes", 128), ("profiles", 1000), ("fixtures", 1000)):
        require(
            isinstance(project.get(field), list) and len(project[field]) <= limit, f"{field}: invalid list"
        )
        unique(project[field], field)
    for node in project["nodes"]:
        keys(node, "id name host port max_fps refresh_every full_universe", "node")
        name(node.get("name"), "node.name")
        try:
            ip = IPv4Address(node["host"])
        except (KeyError, ValueError, TypeError) as err:
            raise ValidationError("host: IPv4 address required") from err
        require(
            not ip.is_multicast and not ip.is_unspecified and str(ip) != "255.255.255.255",
            "DMX requires a unicast destination",
        )
        integer(node.get("port", 6454), 1, 65535, "port")
        integer(node.get("max_fps", 25), 1, 44, "max_fps")
        refresh = node.get("refresh_every", 1)
        require(type(refresh) in (int, float) and 0 <= refresh <= 120, "refresh_every: 0–120 seconds")
        require(type(node.get("full_universe", True)) is bool, "full_universe: boolean required")
    profiles = {p["id"]: validate_profile(p) for p in project["profiles"]}
    nodes = {n["id"] for n in project["nodes"]}
    occupied = {}
    for fixture in project["fixtures"]:
        keys(fixture, "id name node_id profile_id universe start_channel", "fixture")
        name(fixture.get("name"), "fixture.name")
        require(fixture.get("node_id") in nodes, "Node does not exist")
        require(fixture.get("profile_id") in profiles, "Profile does not exist")
        integer(fixture.get("universe"), 0, 32767, "universe")
        integer(fixture.get("start_channel"), 1, 512, "start_channel")
        for control in profiles[fixture["profile_id"]]["controls"]:
            for offset in control["slots"]:
                channel = fixture["start_channel"] + offset - 1
                require(channel <= 512, f"{fixture['name']}: exceeds channel 512")
                # Two node records pointing at the same endpoint are still one physical patch.
                node = next(n for n in project["nodes"] if n["id"] == fixture["node_id"])
                address = (node["host"], node.get("port", 6454), fixture["universe"], channel)
                require(
                    address not in occupied,
                    f"Overlap in universe {fixture['universe']}, channel {channel}",
                )
                occupied[address] = fixture["id"]
    return deepcopy(project)


def empty_project():
    return {"schema_version": 1, "id": str(uuid4()), "nodes": [], "profiles": [], "fixtures": []}


def export_profiles(project):
    """Profiles carry relative offsets only; installation addresses never leave here."""
    return {"format": "hartnet-profiles", "schema_version": 1, "profiles": deepcopy(project["profiles"])}
