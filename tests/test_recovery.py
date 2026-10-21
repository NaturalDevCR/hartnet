"""Durability, startup, failure recovery and real process-crash regressions."""

import asyncio
import copy
import json
import socket
import sys

import aiohttp
import pytest
from hartnet.engine import Engine
from hartnet.model import ValidationError
from hartnet.server import ENGINE, create_app
from hartnet.storage import document

TOKEN = "durable-test-token-123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def loopback(project, receiver):
    project["nodes"][0].update(host="127.0.0.1", port=receiver.getsockname()[1], refresh_every=0)


def receiver_socket():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    return receiver


async def test_restart_restores_all_controls_and_manual_stop(aiohttp_client, tmp_path, generic):
    receiver = receiver_socket()
    loopback(generic, receiver)
    path = tmp_path / "project.json"
    client = await aiohttp_client(create_app(path, TOKEN, project=generic, bind_port=0))
    fixture = generic["fixtures"][0]["id"]
    values = {"pan": 51323, "mode": 150, "relay": 255}
    try:
        result = await client.post(
            f"/api/fixtures/{fixture}/command", headers=HEADERS, json={"values": values, "brightness": 91}
        )
        assert result.status == 200
        await client.post("/api/output", headers=HEADERS, json={"enabled": True})
        first = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 1)
        await client.close()
        restored_app = create_app(path, TOKEN, bind_port=0)
        restored = await aiohttp_client(restored_app)
        second = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 1)
        assert first == second  # Refresh=0 still sends the first restored frame.
        snapshot = await (await restored.get("/api/state", headers=HEADERS)).json()
        assert snapshot["output_enabled"] and snapshot["output_requested"]
        assert snapshot["states"][fixture]["brightness"] == 91
        assert snapshot["states"][fixture]["values"] == {**values, "fixed": 17}
        assert (await restored.get("/health")).status == 200
        await restored.post("/api/output", headers=HEADERS, json={"enabled": False})
        await restored.close()
        stopped_app = create_app(path, TOKEN, bind_port=0)
        stopped = await aiohttp_client(stopped_app)
        assert not stopped_app[ENGINE].enabled and stopped_app[ENGINE].transport is None
        assert (await (await stopped.get("/api/state", headers=HEADERS)).json())["states"] == snapshot[
            "states"
        ]
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 0.1)
    finally:
        receiver.close()


async def test_durable_target_and_concurrent_fixture_updates(aiohttp_client, tmp_path, party):
    path = tmp_path / "project.json"
    client = await aiohttp_client(create_app(path, TOKEN, project=party, bind_port=0))
    spot, _, _, speed = party["fixtures"][:4]
    responses = await asyncio.gather(
        client.post(
            f"/api/fixtures/{spot['id']}/command",
            headers=HEADERS,
            json={"on": True, "brightness": 147, "color": [21, 98, 154, 13], "transition": 900},
        ),
        client.post(
            f"/api/fixtures/{speed['id']}/command", headers=HEADERS, json={"values": {"number_1": 211}}
        ),
    )
    assert all(r.status == 200 for r in responses)
    restored = create_app(path, TOKEN, bind_port=0)[ENGINE]
    assert restored.states[spot["id"]]["brightness"] == 147
    assert restored.states[spot["id"]]["color"] == [21, 98, 154, 13]
    assert restored.states[speed["id"]]["values"]["number_1"] == 211
    assert restored.states[spot["id"]]["on"] and not restored.fades
    assert restored.render_fixture(spot)["dimmer_1"] == 147
    assert not restored.enabled  # Editing an offline preview never enables output.


async def test_disk_failure_does_not_apply_or_acknowledge_command(
    aiohttp_client, tmp_path, party, monkeypatch
):
    import hartnet.storage as storage

    path = tmp_path / "project.json"
    app = create_app(path, TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)
    before, saved = copy.deepcopy(app[ENGINE].states), path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    fixture = party["fixtures"][0]["id"]
    response = await client.post(
        f"/api/fixtures/{fixture}/command", headers=HEADERS, json={"on": True, "brightness": 63}
    )
    assert response.status == 503
    assert app[ENGINE].states == before and path.read_bytes() == saved
    response = await client.post("/api/output", headers=HEADERS, json={"enabled": True})
    assert response.status == 503 and not app[ENGINE].enabled
    assert list(tmp_path.glob(".hartnet-*")) == []


async def test_patch_edit_retains_unchanged_presets_and_resets_changed_mapping(
    aiohttp_client, tmp_path, party
):
    app = create_app(tmp_path / "project.json", TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)
    spot, speed = party["fixtures"][0], party["fixtures"][3]
    await client.post(f"/api/fixtures/{spot['id']}/command", headers=HEADERS, json={"brightness": 81})
    await client.post(
        f"/api/fixtures/{speed['id']}/command", headers=HEADERS, json={"values": {"number_1": 255}}
    )
    changed = copy.deepcopy(party)
    changed["fixtures"][0]["name"] = "Renamed spot"
    profile = next(p for p in changed["profiles"] if p["id"] == spot["profile_id"])
    profile["name"] = "Renamed profile"
    profile["controls"][0]["name"] = "Intensity"
    assert (await client.put("/api/project", headers=HEADERS, json=changed)).status == 200
    assert app[ENGINE].states[spot["id"]]["brightness"] == 81
    changed["fixtures"][0]["start_channel"] = 100
    assert (await client.put("/api/project", headers=HEADERS, json=changed)).status == 200
    assert app[ENGINE].states[spot["id"]]["brightness"] == 255
    assert app[ENGINE].states[speed["id"]]["values"]["number_1"] == 255
    assert app[ENGINE].transport is None


def test_legacy_upgrade_preserves_identity_and_requires_first_activation(tmp_path, party):
    path = tmp_path / "project.json"
    path.write_text(json.dumps(party))
    app = create_app(path, TOKEN)
    assert app[ENGINE].project == party and not app[ENGINE].output_requested
    assert json.loads(path.with_suffix(".previous.json").read_text()) == party
    assert json.loads(path.read_text())["storage_version"] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.with_suffix(".previous.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("corruption", ["json", "version", "state", "fixed", "intent", "missing"])
def test_invalid_store_fails_closed(tmp_path, generic, corruption):
    engine = Engine(generic)
    raw = document(generic, engine.states, True)
    fixture = generic["fixtures"][0]["id"]
    if corruption == "version":
        raw["storage_version"] = 999
    elif corruption == "state":
        raw["runtime"]["states"][fixture]["values"]["mode"] = 99
    elif corruption == "fixed":
        raw["runtime"]["states"][fixture]["values"]["fixed"] = 18
    elif corruption == "intent":
        raw["runtime"]["output_enabled"] = "true"
    elif corruption == "missing":
        raw["runtime"]["states"] = {}
    path = tmp_path / "project.json"
    path.write_text("{" if corruption == "json" else json.dumps(raw))
    with pytest.raises((ValidationError, ValueError)):
        create_app(path, TOKEN, bind_port=0)


async def test_socket_bind_failure_retries_and_stop_cancels_backoff(party, monkeypatch):
    receiver = receiver_socket()
    loopback(party, receiver)
    engine = Engine(party, bind_host="127.0.0.1", bind_port=0)
    original = engine.open_socket
    attempts = 0

    async def bind():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("address temporarily unavailable")
        await original()

    monkeypatch.setattr(engine, "open_socket", bind)
    try:
        await engine.start()
        await asyncio.sleep(0)
        assert engine.enabled and engine.output_status == "retrying"
        await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 2)
        assert attempts == 2 and engine.output_status == "active"
        assert engine.last_error is None
        await engine.close()

        async def always_fail():
            raise OSError("still unavailable")

        monkeypatch.setattr(engine, "open_socket", always_fail)
        await engine.start()
        await asyncio.sleep(0)
        await asyncio.wait_for(engine.stop(), 0.1)
        assert not engine.enabled and not engine.output_requested
    finally:
        await engine.close()
        receiver.close()


async def test_node_failure_does_not_stop_healthy_universes(party):
    project = copy.deepcopy(party)
    node = copy.deepcopy(project["nodes"][0])
    node.update(id="other-node", host="127.0.0.2")
    project["nodes"][0].update(host="127.0.0.1", refresh_every=0.05)
    project["nodes"].append(node)
    project["fixtures"][0]["node_id"] = node["id"]
    engine = Engine(project)

    class Transport:
        healthy = failures = 0

        def sendto(self, packet, address):
            if address[0] == "127.0.0.2":
                self.failures += 1
                raise OSError("one destination failed")
            self.healthy += 1

        def close(self):
            pass

    transport = Transport()
    engine.transport = transport
    try:
        await engine.start()
        await asyncio.sleep(0.65)
        assert engine.enabled and transport.failures == 2 and transport.healthy >= 5
        assert engine.output_status == "retrying"
    finally:
        await engine.close()


async def test_watchdog_health_does_not_expose_state_and_detects_dead_sender(
    aiohttp_client, tmp_path, party, monkeypatch
):
    app = create_app(tmp_path / "project.json", TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)
    health = await client.get("/health")
    assert health.status == 200 and await health.json() == {"status": "ok"}
    assert (await client.get("/api/state")).status == 401

    async def fail():
        raise RuntimeError("unexpected sender failure")

    monkeypatch.setattr(app[ENGINE], "_run", fail)
    await client.post("/api/output", headers=HEADERS, json={"enabled": True})
    await asyncio.sleep(0.01)
    assert (await client.get("/health")).status == 503
    assert (await client.post("/api/output", headers=HEADERS, json={"enabled": False})).status == 200
    assert (await client.get("/health")).status == 200


async def test_acknowledged_values_survive_sigkill_and_first_packet_is_restored(tmp_path, party):
    receiver = receiver_socket()
    loopback(party, receiver)
    path = tmp_path / "project.json"
    path.write_text(json.dumps(party))
    port_socket = socket.socket()
    port_socket.bind(("127.0.0.1", 0))
    port = port_socket.getsockname()[1]
    port_socket.close()
    url = f"http://127.0.0.1:{port}"
    code = (
        "from aiohttp import web; from hartnet.server import create_app; "
        f"web.run_app(create_app({str(path)!r}, {TOKEN!r}, bind_port=0), "
        f"host='127.0.0.1', port={port}, print=None)"
    )
    process = None
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:

            async def launch():
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    code,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                async with asyncio.timeout(8):
                    while True:
                        try:
                            async with session.get(url + "/api/state") as response:
                                if response.status == 200:
                                    return proc
                        except aiohttp.ClientError:
                            pass
                        if proc.returncode is not None:
                            raise AssertionError((await proc.stderr.read()).decode())
                        await asyncio.sleep(0.05)

            process = await launch()
            spot, speed = party["fixtures"][0], party["fixtures"][3]
            for fixture, command in [
                (spot, {"on": True, "brightness": 139, "color": [20, 255, 76, 8]}),
                (speed, {"values": {"number_1": 217}}),
            ]:
                async with session.post(
                    url + f"/api/fixtures/{fixture['id']}/command", json=command
                ) as response:
                    assert response.status == 200
            async with session.post(url + "/api/output", json={"enabled": True}) as response:
                accepted = await response.json()
                assert response.status == 200
            first = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 2)
            process.kill()  # SIGKILL skips every cleanup handler.
            await process.wait()
            process = await launch()
            restored = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(receiver, 1024), 2)
            assert restored[18:] == first[18:]
            assert restored[18] == 139 and restored[18 + 23] == 217
            async with session.get(url + "/api/state") as response:
                recovered = await response.json()
            assert recovered["output_enabled"] and recovered["states"] == accepted["states"]
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        receiver.close()


async def test_unchanged_commands_do_not_rewrite_storage(aiohttp_client, tmp_path, party, monkeypatch):
    import hartnet.storage as storage

    app = create_app(tmp_path / "project.json", TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)

    def unexpected_write(*args, **kwargs):
        raise AssertionError("No-op command attempted a disk write")

    monkeypatch.setattr(storage, "atomic_save", unexpected_write)
    fixture = party["fixtures"][0]["id"]
    assert (
        await client.post(
            f"/api/fixtures/{fixture}/command", headers=HEADERS, json={"on": False, "brightness": 255}
        )
    ).status == 200
    assert (await client.post("/api/output", headers=HEADERS, json={"enabled": False})).status == 200


@pytest.mark.parametrize("route", ["output", "legacy/preview", "profiles", "discover"])
async def test_non_object_payloads_are_rejected(aiohttp_client, tmp_path, route):
    client = await aiohttp_client(create_app(tmp_path / "project.json", TOKEN, bind_port=0))
    assert (await client.post(f"/api/{route}", headers=HEADERS, json=[])).status == 400
