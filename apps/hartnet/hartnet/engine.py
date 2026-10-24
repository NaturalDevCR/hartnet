"""One owner per DMX universe, with bounded output and optimistic state."""

import asyncio
import contextlib
import logging
import random
import socket
import time
from copy import deepcopy

from .model import CURVES, integer, require, validate_project
from .protocol import PORT, art_dmx, art_poll, controller_reply, parse_poll, parse_poll_reply

POLL_INTERVAL = 2.75
# Allow one polling interval plus the specification's three-second response window.
SUBSCRIPTION_TIMEOUT = POLL_INTERVAL + 3
MAX_DISCOVERED = 4096

LIGHT_KINDS = {"dimmer", "red", "green", "blue", "white", "cold_white", "warm_white"}
COLOR_KINDS = ["red", "green", "blue", "white", "cold_white", "warm_white"]


class Receiver(asyncio.DatagramProtocol):
    def __init__(self, engine):
        self.engine = engine

    def datagram_received(self, data, addr):
        self.engine.receive(data, addr)

    def error_received(self, exc):
        self.engine.last_error = str(exc)
        self.engine.socket_error = exc


class Engine:
    def __init__(self, project, bind_host="0.0.0.0", bind_port=PORT):
        self.bind_host, self.bind_port = bind_host, bind_port
        self.transport = self.task = None
        self.output_requested = False
        self.discovered = {}
        self._seen = {}
        self._reply_handles = {}
        self._reply_counter = 0
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
        self._last_poll = {}
        self._controller_errors = {}
        self.discovered.clear()
        self._seen.clear()

    @property
    def subscription_mode(self):
        return any(n.get("output_mode") == "subscribed" for n in self.project["nodes"])

    def expire_discovered(self, now=None):
        now = time.monotonic() if now is None else now
        for key, seen in list(self._seen.items()):
            if now - seen >= SUBSCRIPTION_TIMEOUT:
                self._seen.pop(key, None)
                self.discovered.pop(key, None)

    def receive(self, data, addr):
        reply = parse_poll_reply(data, addr[0])
        if reply:
            self.expire_discovered()
            key = f"{reply['host']}:{reply['bind_index']}"
            if key not in self.discovered and len(self.discovered) >= MAX_DISCOVERED:
                return
            previous = self.discovered.get(key, {}).get("subscriptions", [])
            if previous != reply["subscriptions"]:
                for node in self.project["nodes"]:
                    if node["host"] == reply["host"] and node.get("output_mode") == "subscribed":
                        for universe in set(previous + reply["subscriptions"]):
                            self._last_frames.pop((node["id"], universe), None)
                            self._last_sent.pop((node["id"], universe), None)
            reply.update(last_seen=time.time(), source=addr[0])
            self.discovered[key] = reply
            self._seen[key] = time.monotonic()
            return
        poll = parse_poll(data)
        if not poll or poll["targeted"] or not self.enabled or not self.subscription_mode:
            return
        # Controllers have no input/output subscriptions to match a targeted poll.
        # Coalesce requests and bound delayed replies, including on a busy network.
        if addr[0] in self._reply_handles or len(self._reply_handles) >= 32:
            return
        self._reply_handles[addr[0]] = asyncio.get_running_loop().call_later(
            random.uniform(0, 1), self._reply_to_poll, addr[0]
        )

    def _local_address(self, peer):
        if self.bind_host != "0.0.0.0":
            return self.bind_host
        # UDP connect selects the outgoing interface without sending a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((peer, PORT))
            return route.getsockname()[0]

    def _reply_to_poll(self, peer):
        self._reply_handles.pop(peer, None)
        if not self.enabled or not self.transport:
            return
        try:
            self._reply_counter += 1
            self.transport.sendto(
                controller_reply(self._local_address(peer), self._reply_counter), (peer, PORT)
            )
            self._controller_errors.pop(peer, None)
        except OSError as err:
            self._controller_errors[peer] = str(err)

    def _poll_subscribers(self, now):
        self.expire_discovered(now)
        endpoints = {}
        nodes = {n["id"]: n for n in self.project["nodes"]}
        for fixture in self.project["fixtures"]:
            node = nodes[fixture["node_id"]]
            if node.get("output_mode") == "subscribed":
                endpoint = node["host"], node.get("port", PORT)
                endpoints.setdefault(endpoint, set()).add(fixture["universe"])
        for endpoint, universes in endpoints.items():
            if now - self._last_poll.get(endpoint, float("-inf")) < POLL_INTERVAL:
                continue
            self._last_poll[endpoint] = now
            try:
                self.transport.sendto(art_poll(bottom=min(universes), top=max(universes)), endpoint)
                # A controller also announces itself to its own address when polling.
                local = self._local_address(endpoint[0])
                self._reply_counter += 1
                local_port = self.bind_port or self.transport.get_extra_info("sockname")[1]
                self.transport.sendto(controller_reply(local, self._reply_counter), (local, local_port))
                self._controller_errors.pop(endpoint[0], None)
            except OSError as err:
                self._controller_errors[endpoint[0]] = str(err)

    def subscribed(self, node, universe):
        now = time.monotonic()
        return any(
            reply["host"] == node["host"]
            and reply["source"] == node["host"]
            and universe in reply["subscriptions"]
            and now - self._seen[key] < SUBSCRIPTION_TIMEOUT
            for key, reply in self.discovered.items()
        )

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
        self._last_poll.clear()
        self._controller_errors.clear()
        self.task = asyncio.create_task(self._run())
        self.task.add_done_callback(self._output_done)

    def _output_done(self, task):
        if not task.cancelled() and (error := task.exception()) is not None:
            self.last_error = str(error)
            logging.getLogger(__name__).error("Art-Net sender failed", exc_info=error)

    async def stop(self):
        self.output_requested = False
        for handle in self._reply_handles.values():
            handle.cancel()
        self._reply_handles.clear()
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
        self.transport.sendto(art_poll(bottom=0, top=32767), (target, PORT))
        await asyncio.sleep(3)
        self.expire_discovered()
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
                self._poll_subscribers(now)
                for key, frame in self.frames().items():
                    if now < retries.get(key, (0, 0.5))[0]:
                        continue
                    node = nodes[key[0]]
                    if node.get("output_mode") == "subscribed" and not self.subscribed(node, key[1]):
                        # Resubscription must send a fresh first frame even with refresh=0.
                        self._last_frames.pop(key, None)
                        self._last_sent.pop(key, None)
                        continue
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
                self.last_error = next(iter(failures.values()), None) or next(
                    iter(self._controller_errors.values()), None
                )
                retry_delay = 0.5
                await asyncio.sleep(1 / 100)
            except OSError as err:
                self.last_error = str(err)
                if self.transport:
                    self.transport.close()
                    self.transport = None
                self._last_sent.clear()
                self._last_frames.clear()
                self._last_poll.clear()
                self.discovered.clear()
                self._seen.clear()
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
        if any(
            n.get("output_mode") == "subscribed" and not self.subscribed(n, f["universe"])
            for n in self.project["nodes"]
            for f in self.project["fixtures"]
            if f["node_id"] == n["id"]
        ):
            return "waiting"
        return "active" if self.transport else "starting"

    def snapshot(self):
        self.expire_discovered()
        return {
            "project": deepcopy(self.project),
            "states": deepcopy(self.states),
            "output_enabled": self.enabled,
            "output_requested": self.output_requested,
            "output_status": self.output_status,
            "frames_sent": self.frames_sent,
            "last_error": self.last_error,
            "discovered": list(self.discovered.values()),
            "subscriptions": [
                {"node_id": n["id"], "universe": u, "active": self.subscribed(n, u)}
                for n in self.project["nodes"]
                if n.get("output_mode") == "subscribed"
                for u in sorted({f["universe"] for f in self.project["fixtures"] if f["node_id"] == n["id"]})
            ],
            "assumed_state": True,
        }
