"""One owner per DMX universe, with bounded output and optimistic state."""

import asyncio
import contextlib
import logging
import time
from copy import deepcopy

from .model import CURVES, integer, require, validate_project
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
        self.engine.socket_error = exc


class Engine:
    def __init__(self, project, bind_host="0.0.0.0", bind_port=PORT):
        self.bind_host, self.bind_port = bind_host, bind_port
        self.transport = self.task = None
        self.output_requested = False
        self.discovered = {}
        self.last_error = None
        self.socket_error = None
        self.frames_sent = 0
        self.load(project)

    @property
    def enabled(self):
        return self.task is not None and not self.task.done()

    def load(self, project):
        require(not self.enabled, "Stop output before editing the patch")
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

    def restore_runtime(self, runtime):
        require(
            isinstance(runtime, dict) and set(runtime) == {"states", "output_enabled"},
            "Invalid saved runtime",
        )
        require(type(runtime["output_enabled"]) is bool, "Invalid saved output intent")
        states = runtime["states"]
        require(
            isinstance(states, dict) and set(states) == set(self.fixtures),
            "Saved state does not match the project",
        )
        validated = {}
        for fixture_id, state in states.items():
            require(
                isinstance(state, dict) and set(state) == {"on", "brightness", "color", "values"},
                "Invalid saved fixture state",
            )
            values = state["values"]
            controls = self.controls(self.fixtures[fixture_id])
            require(
                isinstance(values, dict) and set(values) == {c["id"] for c in controls},
                "Invalid saved control values",
            )
            editable = {c["id"] for c in controls if c["kind"] in {"number", "switch", "select"}}
            for control in controls:
                if control["id"] not in editable:
                    require(
                        type(values[control["id"]]) is int
                        and values[control["id"]] == control.get("default", 0),
                        "Saved fixed value does not match the profile",
                    )
            command = {**state, "values": {k: v for k, v in values.items() if k in editable}}
            validated[fixture_id], _ = self.prepare_command(fixture_id, command)
        require(not runtime["output_enabled"] or self.fixtures, "Saved output requires fixtures")
        self.states = validated
        self.output_requested = runtime["output_enabled"]

    def carry_states_from(self, previous):
        # Names, units and device metadata do not change the stored DMX meaning.
        def signature(profile):
            return {
                c["id"]: {k: v for k, v in c.items() if k not in {"name", "unit"}}
                for c in profile["controls"]
            }

        for fixture_id, fixture in self.fixtures.items():
            old = previous.fixtures.get(fixture_id)
            if old and all(
                fixture[k] == old[k] for k in ("node_id", "profile_id", "universe", "start_channel")
            ):
                if signature(self.profiles[fixture["profile_id"]]) == signature(
                    previous.profiles[old["profile_id"]]
                ):
                    self.states[fixture_id] = deepcopy(previous.states[fixture_id])

    def controls(self, fixture):
        return self.profiles[fixture["profile_id"]]["controls"]

    def color_controls(self, fixture):
        controls = self.controls(fixture)
        return sorted(
            (c for c in controls if c["kind"] in COLOR_KINDS), key=lambda c: COLOR_KINDS.index(c["kind"])
        )

    def prepare_command(self, fixture_id, command):
        require(fixture_id in self.fixtures, "Fixture does not exist")
        require(
            isinstance(command, dict)
            and not set(command) - {"on", "brightness", "color", "values", "transition"},
            "Invalid command",
        )
        fixture = self.fixtures[fixture_id]
        state = deepcopy(self.states[fixture_id])
        if "on" in command:
            require(type(command["on"]) is bool, "on: boolean required")
            state["on"] = command["on"]
        if "brightness" in command:
            integer(command["brightness"], 0, 255, "brightness")
            state["brightness"] = command["brightness"]
        if "color" in command:
            color = command["color"]
            require(
                isinstance(color, list) and len(color) == len(self.color_controls(fixture)),
                "Incompatible color",
            )
            for value in color:
                integer(value, 0, 255, "color")
            state["color"] = color
        values = command.get("values", {})
        require(isinstance(values, dict), "values: object required")
        controls = {c["id"]: c for c in self.controls(fixture)}
        for key, value in values.items():
            require(
                key in controls and controls[key]["kind"] in {"number", "switch", "select"},
                "Control is not editable",
            )
            control = controls[key]
            maximum = 256 ** len(control["slots"]) - 1
            integer(value, control.get("min", 0), control.get("max", maximum), key)
            if control["kind"] == "select":
                require(value in [o["value"] for o in control["options"]], "Unknown option")
            if control["kind"] == "switch":
                require(
                    value in (control.get("min", 0), control.get("max", maximum)),
                    "switch requires minimum or maximum",
                )
            state["values"][key] = value
        transition = command.get("transition", 0)
        require(type(transition) in (int, float) and 0 <= transition <= 999, "transition: 0–999 seconds")
        return state, transition

    def apply_command(self, fixture_id, state, transition):
        fixture = self.fixtures[fixture_id]
        now = time.monotonic()
        previous = self.render_fixture(fixture, now)
        self.states[fixture_id] = state
        self.fades.pop(fixture_id, None)
        if transition:
            self.fades[fixture_id] = (now, transition, previous, self.render_fixture(fixture, now))

    def command(self, fixture_id, command):
        state, transition = self.prepare_command(fixture_id, command)
        self.apply_command(fixture_id, state, transition)

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
        require(self.project["fixtures"], "Add fixtures before enabling output")
        self.output_requested = True
        self.last_error = None
        self._last_sent.clear()
        self._last_frames.clear()
        self.task = asyncio.create_task(self._run())
        self.task.add_done_callback(self._output_done)

    def _output_done(self, task):
        if not task.cancelled() and (error := task.exception()) is not None:
            self.last_error = str(error)
            logging.getLogger(__name__).error("Art-Net sender failed", exc_info=error)

    async def stop(self):
        self.output_requested = False
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None
        self.last_error = None

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
        retry_delay = 0.5
        retries, failures = {}, {}
        while True:
            try:
                if self.socket_error is not None:
                    error, self.socket_error = self.socket_error, None
                    raise OSError(str(error))
                await self.open_socket()
                now = time.monotonic()
                for key, frame in self.frames().items():
                    if now < retries.get(key, (0, 0.5))[0]:
                        continue
                    node = nodes[key[0]]
                    elapsed = now - self._last_sent.get(key, float("-inf"))
                    refresh = node.get("refresh_every", 1)
                    if elapsed < 1 / node.get("max_fps", 25):
                        continue
                    if frame == self._last_frames.get(key) and not (refresh and elapsed >= refresh):
                        continue
                    sequence = sequences.get(key, 0) % 255 + 1
                    try:
                        self.transport.sendto(
                            art_dmx(key[1], frame, sequence), (node["host"], node.get("port", PORT))
                        )
                    except OSError as err:
                        delay = retries.get(key, (0, 0.5))[1]
                        retries[key] = now + delay, min(delay * 2, 10)
                        failures[key] = str(err)
                        continue
                    retries.pop(key, None)
                    failures.pop(key, None)
                    sequences[key] = sequence
                    self._last_sent[key], self._last_frames[key] = now, frame
                    self.frames_sent += 1
                self.last_error = next(iter(failures.values()), None)
                retry_delay = 0.5
                await asyncio.sleep(1 / 100)
            except OSError as err:
                self.last_error = str(err)
                if self.transport:
                    self.transport.close()
                    self.transport = None
                self._last_sent.clear()
                self._last_frames.clear()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10)

    @property
    def output_status(self):
        if not self.output_requested:
            return "stopped"
        if not self.enabled:
            return "error"
        if self.last_error:
            return "retrying"
        return "active" if self.transport else "starting"

    def snapshot(self):
        return {
            "project": deepcopy(self.project),
            "states": deepcopy(self.states),
            "output_enabled": self.enabled,
            "output_requested": self.output_requested,
            "output_status": self.output_status,
            "frames_sent": self.frames_sent,
            "last_error": self.last_error,
            "discovered": list(self.discovered.values()),
            "assumed_state": True,
        }
