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
    require(isinstance(text, str) and len(text) <= 1_000_000, "YAML demasiado grande")
    try:
        source = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError) as err:
        raise ValidationError("YAML inválido. Pega solo el bloque light, sin !include.") from err
    require(isinstance(source, dict) and isinstance(source.get("light"), list), "Se requiere una lista light")
    project, warnings = empty_project(), []
    profiles = {}
    require(len(source["light"]) <= 128, "Demasiados nodos")
    for entry in source["light"]:
        require(isinstance(entry, dict), "Entrada light inválida")
        if entry.get("platform") != "artnet_led":
            continue
        require(
            entry.get("node_type", "artnet-direct") == "artnet-direct",
            "Esta primera versión importa artnet-direct; otros transportes requieren conversión explícita",
        )
        require(
            not entry.get("host_override") and not entry.get("port_override"),
            "Resuelve host_override/port_override antes de importar",
        )
        node_id = stable_id(f"node:{entry.get('host')}:{entry.get('port', 6454)}")
        universes = entry.get("universes")
        require(isinstance(universes, dict), "universes debe ser un objeto")
        full_modes = {
            not u.get("send_partial_universe", True) for u in universes.values() if isinstance(u, dict)
        }
        require(
            len(full_modes) <= 1, "Se requieren nodos separados si se mezclan tramas parciales y completas"
        )
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
            require(isinstance(config, dict) and isinstance(config.get("devices"), list), "devices inválido")
            if universe == 0:
                warnings.append("Universo 0 conservado por compatibilidad con tu nodo; no se renumera.")
            for device in config["devices"]:
                require(isinstance(device, dict), "Dispositivo inválido")
                fixture_type = device.get("type", "dimmer")
                require(fixture_type in DEFAULT_LAYOUTS, f"Tipo legacy aún no soportado: {fixture_type}")
                byte_size = {"8bit": 1, "16bit": 2, "24bit": 3, "32bit": 4}.get(
                    device.get("channel_size", "8bit")
                )
                require(byte_size is not None, "channel_size inválido")
                order = device.get("byte_order", "big")
                require(order in ("big", "little"), "byte_order inválido")
                layout = device.get("channel_setup") or DEFAULT_LAYOUTS[fixture_type]
                require(isinstance(layout, (list, str)) and 1 <= len(layout) <= 512, "channel_setup inválido")
                controls = []
                for index, item in enumerate(layout):
                    slots = list(range(index * byte_size + 1, (index + 1) * byte_size + 1))
                    if order == "little":
                        slots.reverse()
                    if type(item) is int:
                        require(0 <= item <= 255, "Constante legacy fuera de rango")
                        # Legacy scales 8-bit constants by 256**(byte_size-1).
                        value = item * 256 ** (byte_size - 1)
                        control = {
                            "id": f"constant_{index + 1}",
                            "name": f"Fijo {index + 1}",
                            "kind": "constant",
                            "slots": slots,
                            "default": value,
                            "off_value": value,
                        }
                    else:
                        require(
                            isinstance(item, str) and item.lower() in FUNCTIONS,
                            f"Función legacy aún no soportada: {item}. No se importará parcialmente.",
                        )
                        kind = FUNCTIONS[item.lower()]
                        if fixture_type == "dimmer" and scalars_as_numbers:
                            kind = "number"
                        if fixture_type == "binary":
                            kind = "switch"
                        control = {
                            "id": f"{kind}_{index + 1}",
                            "name": "Valor" if kind == "number" else kind.replace("_", " ").title(),
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
                        "RGB con blanco calculado requiere un perfil explícito en esta versión"
                    )
                profile = {
                    "name": f"Legacy {fixture_type.upper()} · {len(layout) * byte_size} canales",
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
                        "Valores dinámicos de alta resolución usan todo el rango; legacy usa pasos de 8 bits."
                    )
                if device.get("transition", 0):
                    warnings.append(
                        f"{device.get('name')}: transición predeterminada pendiente; se admite por comando."
                    )
    require(project["fixtures"], "No hay dispositivos artnet_led para importar")
    project["profiles"] = list(profiles.values())
    warnings.extend(
        [
            "Los huecos sin mapear se emiten a 0; el YAML no documenta su función.",
            "Los IDs de entidades de la integración anterior no se adoptan automáticamente.",
        ]
    )
    if scalars_as_numbers:
        warnings.append("Los dimmers independientes se convierten a number por elección del importador.")
    return {"project": validate_project(project), "warnings": list(dict.fromkeys(warnings))}
