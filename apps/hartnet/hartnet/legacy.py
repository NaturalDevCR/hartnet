"""Explicit conversion of supported ha-artnet-led YAML; no fixture guessing."""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

import yaml

from .model import ValidationError, empty_project, require, validate_project

DEFAULT_LAYOUTS = {
    "dimmer": "d",
    "binary": "d",
    "fixed": [255],
    "rgb": "rgb",
    "rgbw": "rgbw",
    "rgbww": "rgbch",
    "color_temp": "ch",
}
FUNCTIONS = {
    "d": "dimmer",
    "r": "red",
    "g": "green",
    "b": "blue",
    "w": "white",
    "c": "cold_white",
    "h": "warm_white",
}


def stable_id(text):
    return str(uuid5(NAMESPACE_URL, f"hartnet:{text}"))


def import_legacy(text, scalars_as_numbers=False):
    require(isinstance(text, str) and len(text) <= 1_000_000, "YAML too large")
    try:
        source = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as err:
        raise ValidationError("Invalid YAML. Paste only the light block, without !include.") from err
    require(isinstance(source, dict) and isinstance(source.get("light"), list), "A light list is required")
    project, warnings = empty_project(), []
    profiles = {}
    require(len(source["light"]) <= 128, "Too many nodes")
    for entry in source["light"]:
        require(isinstance(entry, dict), "Invalid light entry")
        if entry.get("platform") != "artnet_led":
            continue
        require(
            entry.get("node_type", "artnet-direct") == "artnet-direct",
            "This first version imports artnet-direct; other transports require explicit conversion",
        )
        require(
            not entry.get("host_override") and not entry.get("port_override"),
            "Resolve host_override/port_override before importing",
        )
        node_id = stable_id(f"node:{entry.get('host')}:{entry.get('port', 6454)}")
        universes = entry.get("universes")
        require(isinstance(universes, dict), "universes must be an object")
        full_modes = {
            not u.get("send_partial_universe", True) for u in universes.values() if isinstance(u, dict)
        }
        require(len(full_modes) <= 1, "Separate nodes are required when mixing partial and full frames")
        project["nodes"].append(
            {
                "id": node_id,
                "name": f"Art-Net · {entry.get('host')}",
                "host": entry.get("host"),
                "port": entry.get("port", 6454),
                "max_fps": entry.get("max_fps", 25),
                "refresh_every": entry.get("refresh_every", 120),
                "full_universe": next(iter(full_modes), True),
            }
        )
        for universe, config in universes.items():
            require(isinstance(config, dict) and isinstance(config.get("devices"), list), "invalid devices")
            if universe == 0:
                warnings.append("Universe 0 is preserved for node compatibility; no renumbering.")
            for device in config["devices"]:
                require(isinstance(device, dict), "Invalid fixture")
                fixture_type = device.get("type", "dimmer")
                require(fixture_type in DEFAULT_LAYOUTS, f"Unsupported legacy type: {fixture_type}")
                byte_size = {"8bit": 1, "16bit": 2, "24bit": 3, "32bit": 4}.get(
                    device.get("channel_size", "8bit")
                )
                require(byte_size is not None, "invalid channel_size")
                order = device.get("byte_order", "big")
                require(order in ("big", "little"), "invalid byte_order")
                layout = device.get("channel_setup") or DEFAULT_LAYOUTS[fixture_type]
                require(isinstance(layout, (list, str)) and 1 <= len(layout) <= 512, "invalid channel_setup")
                controls = []
                for index, item in enumerate(layout):
                    slots = list(range(index * byte_size + 1, (index + 1) * byte_size + 1))
                    if order == "little":
                        slots.reverse()
                    if type(item) is int:
                        require(0 <= item <= 255, "Legacy constant out of range")
                        # Legacy scales 8-bit constants by 256**(byte_size-1).
                        value = item * 256 ** (byte_size - 1)
                        control = {
                            "id": f"constant_{index + 1}",
                            "name": f"Fixed {index + 1}",
                            "kind": "constant",
                            "slots": slots,
                            "default": value,
                            "off_value": value,
                        }
                    else:
                        require(
                            isinstance(item, str) and item.lower() in FUNCTIONS,
                            f"Unsupported legacy function: {item}. Partial import is not allowed.",
                        )
                        kind = FUNCTIONS[item.lower()]
                        if fixture_type == "dimmer" and scalars_as_numbers:
                            kind = "number"
                        if fixture_type == "binary":
                            kind = "switch"
                        control = {
                            "id": f"{kind}_{index + 1}",
                            "name": "Value" if kind == "number" else kind.replace("_", " ").title(),
                            "kind": kind,
                            "slots": slots,
                            "default": 0,
                            "scale_by_brightness": item.islower(),
                        }
                        curve = device.get("output_correction") or config.get("output_correction", "linear")
                        if kind not in ("number", "switch"):
                            control["curve"] = curve or "linear"
                    controls.append(control)
                if fixture_type == "rgb" and any(c["kind"] == "white" for c in controls):
                    raise ValidationError(
                        "RGB with calculated white requires an explicit profile in this version"
                    )
                profile = {
                    "name": f"Legacy {fixture_type.upper()} · {len(layout) * byte_size} channels",
                    "mode": f"{len(layout) * byte_size}ch",
                    "controls": controls,
                    "min_kelvin": int(str(device.get("min_temp", "2700K")).rstrip("kK")),
                    "max_kelvin": int(str(device.get("max_temp", "6500K")).rstrip("kK")),
                }
                digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]
                profile["id"] = f"legacy-{digest}"
                profiles[profile["id"]] = profile
                project["fixtures"].append(
                    {
                        "id": stable_id(f"fixture:{node_id}:{universe}:{device.get('channel')}"),
                        "name": device.get("name"),
                        "node_id": node_id,
                        "profile_id": profile["id"],
                        "universe": universe,
                        "start_channel": device.get("channel"),
                    }
                )
                if byte_size > 1:
                    warnings.append(
                        "High-resolution dynamic values use the full range; legacy uses 8-bit steps."
                    )
                if device.get("transition", 0):
                    warnings.append(
                        f"{device.get('name')}: default transition is not imported; "
                        "per-command transitions are supported."
                    )
    require(project["fixtures"], "No artnet_led fixtures to import")
    project["profiles"] = list(profiles.values())
    warnings.extend(
        [
            "Unmapped slots are sent as 0; YAML does not document their function.",
            "Entity IDs from the previous integration are not adopted automatically.",
        ]
    )
    if scalars_as_numbers:
        warnings.append("Standalone dimmers become number entities as selected in the importer.")
    return {"project": validate_project(project), "warnings": list(dict.fromkeys(warnings))}
