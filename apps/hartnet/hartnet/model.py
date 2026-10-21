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
    require(type(value) is int and low <= value <= high, f"{label}: entero entre {low} y {high}")


def name(value, label):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 160, f"{label}: texto de 1–160 caracteres")


def keys(value, allowed, label):
    require(isinstance(value, dict), f"{label}: se esperaba un objeto")
    require(
        not set(value) - set(allowed.split()),
        f"{label}: campos desconocidos {set(value) - set(allowed.split())}",
    )


def unique(items, label):
    ids = []
    for item in items:
        require(isinstance(item, dict), f"{label}: se esperaba un objeto")
        name(item.get("id"), f"{label}.id")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", item["id"]), f"{label}.id: caracteres inválidos")
        ids.append(item["id"])
    require(len(ids) == len(set(ids)), f"{label}: IDs duplicados")


def validate_profile(profile):
    keys(profile, "id name manufacturer model mode controls attribution min_kelvin max_kelvin", "perfil")
    name(profile.get("id"), "perfil.id")
    name(profile.get("name"), "perfil.name")
    for field in ("manufacturer", "model", "mode", "attribution"):
        require(isinstance(profile.get(field, ""), str), f"perfil.{field}: texto requerido")
    integer(profile.get("min_kelvin", 2700), 1000, 20000, "min_kelvin")
    integer(profile.get("max_kelvin", 6500), profile.get("min_kelvin", 2700) + 1, 30000, "max_kelvin")
    controls = profile.get("controls")
    require(isinstance(controls, list) and 1 <= len(controls) <= 512, "perfil: 1–512 controles requeridos")
    unique(controls, "controles")
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
        require(isinstance(kind, str) and kind in KINDS, "control.kind inválido")
        slots = control.get("slots")
        require(isinstance(slots, list) and 1 <= len(slots) <= 4, "control.slots: 1–4 bytes")
        for slot in slots:
            integer(slot, 1, 512, "slot")
            require(slot not in used, f"Slot {slot} usado más de una vez")
            used.add(slot)
        maximum = 256 ** len(slots) - 1
        for field in ("default", "off_value"):
            integer(control.get(field, 0), 0, maximum, field)
        low, high = control.get("min", 0), control.get("max", maximum)
        integer(low, 0, maximum, "min")
        integer(high, low, maximum, "max")
        if kind in {"number", "select", "switch"}:
            integer(control.get("default", 0), low, high, "default")
            require(
                control.get("curve", "linear") == "linear", "Las curvas solo se aplican a funciones de luz"
            )
        if kind == "switch":
            require(control.get("default", 0) in (low, high), "switch.default requiere mínimo o máximo")
        require(control.get("curve", "linear") in CURVES, "Curva inválida")
        require(isinstance(control.get("unit", ""), str), "unit: texto requerido")
        require(
            type(control.get("scale_by_brightness", True)) is bool, "scale_by_brightness: booleano requerido"
        )
        if kind in {"dimmer", "red", "green", "blue", "white", "cold_white", "warm_white"}:
            require(kind not in colors, f"Función de luz duplicada: {kind}")
            colors.append(kind)
        if kind == "select":
            options = control.get("options")
            require(isinstance(options, list) and 1 <= len(options) <= 256, "select: opciones requeridas")
            labels = set()
            values = set()
            for option in options:
                keys(option, "label value", "opción")
                name(option.get("label"), "opción.label")
                integer(option.get("value"), low, high, "opción.value")
                require(
                    option["label"] not in labels and option["value"] not in values, "Opciones duplicadas"
                )
                labels.add(option["label"])
                values.add(option["value"])
            require(control.get("default", 0) in values, "select: default debe coincidir con una opción")
        else:
            require("options" not in control, "Solo select admite options")
    rgb = set(colors) & {"red", "green", "blue"}
    require(not rgb or rgb == {"red", "green", "blue"}, "RGB requiere red, green y blue")
    whites = set(colors) & {"cold_white", "warm_white"}
    require(not whites or whites == {"cold_white", "warm_white"}, "CCT requiere ambos blancos")
    require(not ("white" in colors and whites), "Usa RGBW o RGBWW, sin mezclar white con CCT")
    return deepcopy(profile)


def validate_project(project):
    keys(project, "schema_version id nodes profiles fixtures", "proyecto")
    integer(project.get("schema_version"), 1, 1, "schema_version")
    name(project.get("id"), "proyecto.id")
    for field, limit in (("nodes", 128), ("profiles", 1000), ("fixtures", 1000)):
        require(
            isinstance(project.get(field), list) and len(project[field]) <= limit, f"{field}: lista inválida"
        )
        unique(project[field], field)
    for node in project["nodes"]:
        keys(node, "id name host port max_fps refresh_every full_universe", "nodo")
        name(node.get("name"), "nodo.name")
        try:
            ip = IPv4Address(node["host"])
        except (KeyError, ValueError, TypeError) as err:
            raise ValidationError("host: dirección IPv4 requerida") from err
        require(
            not ip.is_multicast and not ip.is_unspecified and str(ip) != "255.255.255.255",
            "DMX requiere un destino unicast",
        )
        integer(node.get("port", 6454), 1, 65535, "port")
        integer(node.get("max_fps", 25), 1, 44, "max_fps")
        refresh = node.get("refresh_every", 1)
        require(type(refresh) in (int, float) and 0 <= refresh <= 120, "refresh_every: 0–120 segundos")
        require(type(node.get("full_universe", True)) is bool, "full_universe: booleano requerido")
    profiles = {p["id"]: validate_profile(p) for p in project["profiles"]}
    nodes = {n["id"] for n in project["nodes"]}
    occupied = {}
    for fixture in project["fixtures"]:
        keys(fixture, "id name node_id profile_id universe start_channel", "equipo")
        name(fixture.get("name"), "equipo.name")
        require(fixture.get("node_id") in nodes, "Nodo inexistente")
        require(fixture.get("profile_id") in profiles, "Perfil inexistente")
        integer(fixture.get("universe"), 0, 32767, "universe")
        integer(fixture.get("start_channel"), 1, 512, "start_channel")
        for control in profiles[fixture["profile_id"]]["controls"]:
            for offset in control["slots"]:
                channel = fixture["start_channel"] + offset - 1
                require(channel <= 512, f"{fixture['name']}: desborda el canal 512")
                # Two node records pointing at the same endpoint are still one physical patch.
                node = next(n for n in project["nodes"] if n["id"] == fixture["node_id"])
                address = (node["host"], node.get("port", 6454), fixture["universe"], channel)
                require(
                    address not in occupied,
                    f"Solapamiento en universo {fixture['universe']}, canal {channel}",
                )
                occupied[address] = fixture["id"]
    return deepcopy(project)


def empty_project():
    return {"schema_version": 1, "id": str(uuid4()), "nodes": [], "profiles": [], "fixtures": []}


def export_profiles(project):
    """Profiles carry relative offsets only; installation addresses never leave here."""
    return {"format": "hartnet-profiles", "schema_version": 1, "profiles": deepcopy(project["profiles"])}
