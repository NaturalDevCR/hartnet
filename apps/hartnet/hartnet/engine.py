"""One owner per DMX universe, with bounded output and optimistic state."""

import asyncio
import contextlib
import time
from copy import deepcopy

from .model import CURVES, ValidationError, integer, require, validate_project
from .protocol import PORT, art_dmx, art_poll, parse_poll_reply

LIGHT_KINDS = {"dimmer", "red", "green", "blue", "white", "cold_white", "warm_white"}
COLOR_KINDS = ["red", "green", "blue", "white", "cold_white", "warm_white"]


class Receiver(asyncio.DatagramProtocol):
    def __init__(self, engine):
        self.engine = engine

    def datagram_received(self, data, addr):
        reply = parse_poll_reply(data, addr[0])
        if reply:
            reply["last_seen"] = time.time()
            self.engine.discovered[f"{reply['host']}:{reply['bind_index']}"] = reply

    def error_received(self, exc):
        self.engine.last_error = str(exc)


class Engine:
    def __init__(self, project, bind_host="0.0.0.0", bind_port=PORT):
        self.bind_host, self.bind_port = bind_host, bind_port
        self.transport = self.task = None
        self.discovered = {}
        self.last_error = None
        self.frames_sent = 0
        self.load(project)

    @property
    def enabled(self):
        return self.task is not None and not self.task.done()

    def load(self, project):
        require(not self.enabled, "Detén la salida antes de modificar el patch")
        self.project = validate_project(project)
        self.profiles = {p["id"]: p for p in self.project["profiles"]}
        self.fixtures = {f["id"]: f for f in self.project["fixtures"]}
        self.states = {
            f["id"]: {
                "on": False,
                "brightness": 255,
                "color": [255] * len(self.color_controls(f)),
                "values": {c["id"]: c.get("default", 0) for c in self.controls(f)},
            }
            for f in self.project["fixtures"]
        }
        self.fades = {}
        self._last_frames = {}
        self._last_sent = {}

    def controls(self, fixture):
        return self.profiles[fixture["profile_id"]]["controls"]

    def color_controls(self, fixture):
        controls = self.controls(fixture)
        return sorted(
            (c for c in controls if c["kind"] in COLOR_KINDS), key=lambda c: COLOR_KINDS.index(c["kind"])
        )

    def command(self, fixture_id, command):
        require(fixture_id in self.fixtures, "Equipo inexistente")
        require(
            isinstance(command, dict)
            and not set(command) - {"on", "brightness", "color", "values", "transition"},
            "Comando inválido",
        )
        fixture = self.fixtures[fixture_id]
        state = deepcopy(self.states[fixture_id])
        if "on" in command:
            require(type(command["on"]) is bool, "on: booleano requerido")
            state["on"] = command["on"]
        if "brightness" in command:
            integer(command["brightness"], 0, 255, "brightness")
            state["brightness"] = command["brightness"]
        if "color" in command:
            color = command["color"]
            require(
                isinstance(color, list) and len(color) == len(self.color_controls(fixture)),
                "Color incompatible",
            )
            for value in color:
                integer(value, 0, 255, "color")
            state["color"] = color
        values = command.get("values", {})
        require(isinstance(values, dict), "values: objeto requerido")
        controls = {c["id"]: c for c in self.controls(fixture)}
        for key, value in values.items():
            require(
                key in controls and controls[key]["kind"] in {"number", "switch", "select"},
                "Control no editable",
            )
            control = controls[key]
            maximum = 256 ** len(control["slots"]) - 1
            integer(value, control.get("min", 0), control.get("max", maximum), key)
            if control["kind"] == "select":
                require(value in [o["value"] for o in control["options"]], "Opción desconocida")
            if control["kind"] == "switch":
                require(
                    value in (control.get("min", 0), control.get("max", maximum)),
                    "switch requiere mínimo o máximo",
                )
            state["values"][key] = value
        transition = command.get("transition", 0)
        require(type(transition) in (int, float) and 0 <= transition <= 999, "transition: 0–999 segundos")
        now = time.monotonic()
        previous = self.render_fixture(fixture, now)
        self.states[fixture_id] = state
        self.fades.pop(fixture_id, None)
        if transition:
            self.fades[fixture_id] = (now, transition, previous, self.render_fixture(fixture, now))

    def render_fixture(self, fixture, now=None):
        now = time.monotonic() if now is None else now
        state = self.states[fixture["id"]]
        colors = {
            c["id"]: value for c, value in zip(self.color_controls(fixture), state["color"], strict=True)
        }
        color_max = max(state["color"], default=255) or 255
        result = {}
        for control in self.controls(fixture):
            maximum = 256 ** len(control["slots"]) - 1
            kind = control["kind"]
            if kind in LIGHT_KINDS:
                if not state["on"]:
                    value = control.get("off_value", 0)
                else:
                    level = (
                        state["brightness"] / 255 if kind == "dimmer" else colors[control["id"]] / color_max
                    )
                    if kind != "dimmer" and control.get("scale_by_brightness", True):
                        level *= state["brightness"] / 255
                    value = round(level ** CURVES[control.get("curve", "linear")] * maximum)
            else:
                value = state["values"][control["id"]]
            result[control["id"]] = value
        fade = self.fades.get(fixture["id"])
        if fade:
            started, duration, before, target = fade
            amount = min(1, (now - started) / duration)
            for control in self.controls(fixture):
                key = control["id"]
                if control["kind"] in LIGHT_KINDS or control["kind"] == "number":
                    result[key] = round(before[key] + (target[key] - before[key]) * amount)
            if amount >= 1:
                self.fades.pop(fixture["id"], None)
        return result

    def frames(self):
        frames, lengths = {}, {}
        for fixture in self.project["fixtures"]:
            key = fixture["node_id"], fixture["universe"]
            frame = frames.setdefault(key, bytearray(512))
            values = self.render_fixture(fixture)
            for control in self.controls(fixture):
                data = values[control["id"]].to_bytes(len(control["slots"]), "big")
                for offset, byte in zip(control["slots"], data, strict=True):
                    slot = fixture["start_channel"] + offset - 2
                    frame[slot] = byte
                    lengths[key] = max(lengths.get(key, 0), slot + 1)
        nodes = {n["id"]: n for n in self.project["nodes"]}
        return {
            key: bytes(frame if nodes[key[0]].get("full_universe", True) else frame[: lengths[key]])
            for key, frame in frames.items()
        }

    async def open_socket(self):
        if self.transport is None:
            self.transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: Receiver(self), local_addr=(self.bind_host, self.bind_port), allow_broadcast=True
            )

    async def start(self):
        if self.enabled:
            return
        require(self.project["fixtures"], "Agrega equipos antes de activar la salida")
        await self.open_socket()
        self.last_error = None
        self._last_sent.clear()
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def close(self):
        await self.stop()
        if self.transport:
            self.transport.close()
            self.transport = None

    async def discover(self, target):
        # Discovery is explicit and does not change the output patch or enable DMX.
        await self.open_socket()
        self.transport.sendto(art_poll(), (target, PORT))
        await asyncio.sleep(1.2)
        return list(self.discovered.values())

    async def _run(self):
        nodes = {n["id"]: n for n in self.project["nodes"]}
        sequences = {}
        try:
            while True:
                now = time.monotonic()
                for key, frame in self.frames().items():
                    node = nodes[key[0]]
                    elapsed = now - self._last_sent.get(key, float("-inf"))
                    refresh = node.get("refresh_every", 1)
                    if elapsed < 1 / node.get("max_fps", 25):
                        continue
                    if frame == self._last_frames.get(key) and not (refresh and elapsed >= refresh):
                        continue
                    sequence = sequences.get(key, 0) % 255 + 1
                    self.transport.sendto(
                        art_dmx(key[1], frame, sequence), (node["host"], node.get("port", PORT))
                    )
                    sequences[key] = sequence
                    self._last_sent[key], self._last_frames[key] = now, frame
                    self.frames_sent += 1
                await asyncio.sleep(1 / 100)
        except (OSError, ValidationError) as err:
            self.last_error = str(err)

    def snapshot(self):
        return {
            "project": deepcopy(self.project),
            "states": deepcopy(self.states),
            "output_enabled": self.enabled,
            "frames_sent": self.frames_sent,
            "last_error": self.last_error,
            "discovered": list(self.discovered.values()),
            "assumed_state": True,
        }
