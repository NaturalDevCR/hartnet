"""Subscription routing, stale nodes and controller discovery over loopback only."""

import asyncio
import socket
import struct

import pytest
from hartnet.engine import Engine, Receiver
from hartnet.model import ValidationError, validate_project
from hartnet.protocol import HEADER, art_poll, controller_reply, parse_poll, parse_poll_reply
from hartnet.server import ENGINE, create_app
from hartnet.storage import atomic_save, document


def node_reply(*, bind=2, output=0, input_universe=None):
    data = bytearray(239)
    data[:10] = HEADER + b"\x00\x21"
    data[10:14] = socket.inet_aton("127.0.0.1")
    data[172:174] = b"\x00\x01"
    data[211] = bind
    if output is not None:
        data[18:20] = bytes([output >> 8, (output >> 4) & 15])
        data[174] |= 0x80
        data[190] = output & 15
    if input_universe is not None:
        data[18:20] = bytes([input_universe >> 8, (input_universe >> 4) & 15])
        data[174] |= 0x40
        data[186] = input_universe & 15
    return data


def test_targeted_poll_and_controller_announcement():
    poll = art_poll(bottom=0, top=32767)
    assert len(poll) == 22 and poll[12] == 0x22
    assert poll[14:18] == b"\x7f\xff\x00\x00"
    assert parse_poll(poll) == {"targeted": True, "bottom": 0, "top": 32767}
    assert parse_poll(art_poll())["targeted"] is False
    assert parse_poll(b"invalid") is None
    assert parse_poll(HEADER + b"\x00\x20\x00\x0d\x00\x00") is None
    invalid = bytearray(poll)
    invalid[14:18] = struct.pack(">HH", 0, 1)
    assert parse_poll(invalid) is None
    packet = controller_reply("127.0.0.1", 10001)
    assert len(packet) == 239 and packet[14:16] == b"\x36\x19"
    assert packet[20:22] == b"\x00\xff" and packet[200] == 1
    assert packet[172:174] == bytes(2) and packet[174:194] == bytes(20)
    assert packet[226:228] == b"\x00\x2c"
    assert packet[108:].startswith(b"#0001 [0001] Ready\0")
    reply = parse_poll_reply(packet, "127.0.0.1")
    assert reply["name"] == "HartNet" and reply["style"] == 1
    assert reply["subscriptions"] == [] and not reply["rdm"]


def test_ports_include_inputs_and_exclude_sacn_disabled_and_non_dmx():
    data = node_reply(output=32767, input_universe=32766)
    reply = parse_poll_reply(data, "127.0.0.1")
    assert reply["universes"] == [32767]
    assert reply["input_universes"] == [32766]
    assert reply["subscriptions"] == [32766, 32767]
    data[182] = 1  # sACN output
    assert parse_poll_reply(data, "127.0.0.1")["subscriptions"] == [32766]
    data[178] = 8  # Disabled input
    assert parse_poll_reply(data, "127.0.0.1")["subscriptions"] == []
    data[174] = 0xC1  # MIDI, not DMX
    assert parse_poll_reply(data, "127.0.0.1")["subscriptions"] == []
    data = node_reply(output=None, input_universe=0)
    assert parse_poll_reply(data[:207], "127.0.0.1")["subscriptions"] == [0]


def test_bindings_expiry_and_no_routing_to_other_advertised_ips(sample_patch, monkeypatch):
    import hartnet.engine as module

    sample_patch["nodes"][0].update(host="127.0.0.1", output_mode="subscribed")
    engine = Engine(sample_patch)
    node = sample_patch["nodes"][0]
    now = 100.0
    monkeypatch.setattr(module.time, "monotonic", lambda: now)
    engine.receive(node_reply(), ("127.0.0.2", 6454))
    assert not engine.subscribed(node, 0)  # An advertised IP alone is insufficient.
    engine.receive(node_reply(), ("127.0.0.1", 6454))
    engine.receive(node_reply(bind=3, output=1), ("127.0.0.1", 6454))
    assert engine.subscribed(node, 0) and engine.subscribed(node, 1)
    engine.receive(node_reply(output=None), ("127.0.0.1", 6454))
    assert not engine.subscribed(node, 0) and engine.subscribed(node, 1)
    now += module.SUBSCRIPTION_TIMEOUT
    assert not engine.subscribed(node, 1)
    assert engine.snapshot()["discovered"] == []
    assert engine.snapshot()["subscriptions"] == [{"node_id": node["id"], "universe": 0, "active": False}]
    engine.receive(node_reply(), ("127.0.0.1", 6454))
    assert engine.subscribed(node, 0)
    engine.load(sample_patch)
    assert not engine.subscribed(node, 0)  # Never retain subscriptions across a patch edit.


@pytest.mark.parametrize("value", [None, True, "broadcast", [], {}])
def test_invalid_output_mode_rejected(sample_patch, value):
    sample_patch["nodes"][0]["output_mode"] = value
    with pytest.raises(ValidationError, match="Invalid output mode"):
        validate_project(sample_patch)


async def test_udp_subscription_withdrawal_expiry_reappearance_and_stop(sample_patch, monkeypatch):
    import hartnet.engine as module

    monkeypatch.setattr(module, "POLL_INTERVAL", 0.04)
    monkeypatch.setattr(module, "SUBSCRIPTION_TIMEOUT", 0.14)

    class Gateway(asyncio.DatagramProtocol):
        def __init__(self):
            self.answer = False
            self.universe = 1
            self.polls = asyncio.Queue()
            self.frames = asyncio.Queue()

        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            if parse_poll(data):
                self.polls.put_nowait((data, addr))
                if self.answer:
                    self.transport.sendto(node_reply(output=self.universe), addr)
            elif data[:10] == HEADER + b"\x00\x50":
                self.frames.put_nowait(data)

    loop = asyncio.get_running_loop()
    transport, gateway = await loop.create_datagram_endpoint(Gateway, local_addr=("127.0.0.1", 0))
    sample_patch["nodes"][0].update(
        host="127.0.0.1",
        port=transport.get_extra_info("sockname")[1],
        output_mode="subscribed",
        refresh_every=0,
    )
    engine = Engine(sample_patch, bind_host="127.0.0.1", bind_port=0)
    try:
        await engine.start()
        poll, sender = await asyncio.wait_for(gateway.polls.get(), 1)
        assert parse_poll(poll)["targeted"] and engine.output_status == "waiting"
        gateway.answer = True
        await asyncio.sleep(0.08)
        assert gateway.frames.empty()  # Subscribing to another universe never enables output.
        gateway.universe = 0
        first = await asyncio.wait_for(gateway.frames.get(), 1)
        assert len(first) == 530 and engine.output_status == "active"
        gateway.universe = None
        await asyncio.sleep(0.08)
        assert engine.output_status == "waiting"
        gateway.universe = 0
        second = await asyncio.wait_for(gateway.frames.get(), 1)
        assert second[18:] == first[18:]  # Fresh frame even with refresh=0 and unchanged data.
        gateway.answer = False
        await asyncio.sleep(0.2)
        assert engine.output_status == "waiting" and not engine.subscribed(sample_patch["nodes"][0], 0)
        gateway.answer = True
        await asyncio.wait_for(gateway.frames.get(), 1)
        await engine.stop()
        # Remove already queued traffic, then prove no DMX, poll or delayed replies follow stop.
        while not gateway.polls.empty():
            gateway.polls.get_nowait()
        while not gateway.frames.empty():
            gateway.frames.get_nowait()
        transport.sendto(art_poll(), sender)
        await asyncio.sleep(0.18)
        assert gateway.polls.empty() and gateway.frames.empty()
    finally:
        await engine.close()
        transport.close()


async def test_controller_replies_are_unicast_and_delayed_handles_are_cancelled(sample_patch):
    sample_patch["nodes"][0].update(host="127.0.0.1", output_mode="subscribed")
    engine = Engine(sample_patch, bind_host="127.0.0.1", bind_port=6454)

    class Transport:
        def __init__(self):
            self.packets = []

        def sendto(self, packet, destination):
            self.packets.append((packet, destination))

        def close(self):
            pass

    engine.transport = transport = Transport()
    # A live task enables controller replies without creating any network socket.
    engine.task = asyncio.create_task(asyncio.Event().wait())
    try:
        receiver = Receiver(engine)
        receiver.datagram_received(art_poll(bottom=0, top=0), ("127.0.0.2", 12345))
        assert not engine._reply_handles  # Controller has no subscribed DMX input/output ports.
        receiver.datagram_received(art_poll(), ("127.0.0.2", 12345))
        assert len(engine._reply_handles) == 1
        engine._reply_handles["127.0.0.2"].cancel()
        engine._reply_to_poll("127.0.0.2")
        packet, destination = transport.packets.pop()
        assert destination == ("127.0.0.2", 6454)
        assert parse_poll_reply(packet, "127.0.0.1")["style"] == 1
        receiver.datagram_received(art_poll(), ("127.0.0.2", 12345))
        await engine.stop()
        await asyncio.sleep(1.01)
        assert not transport.packets and not engine._reply_handles
    finally:
        await engine.close()


async def test_restart_relearns_subscription_before_first_saved_frame(aiohttp_client, tmp_path, sample_patch):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    sample_patch["nodes"][0].update(
        host="127.0.0.1", port=receiver.getsockname()[1], output_mode="subscribed", refresh_every=0
    )
    saved = Engine(sample_patch)
    spot, speed = sample_patch["fixtures"][0], sample_patch["fixtures"][3]
    saved.command(spot["id"], {"on": True, "brightness": 123, "color": [10, 255, 99, 3]})
    saved.command(speed["id"], {"values": {"number_1": 219}})
    expected = next(iter(saved.frames().values()))
    path = tmp_path / "project.json"
    atomic_save(path, document(saved.project, saved.states, True))
    app = create_app(path, "subscription-restart-token", bind_port=0)
    client = await aiohttp_client(app)
    engine = app[ENGINE]
    loop = asyncio.get_running_loop()
    try:
        assert engine.output_requested and engine.enabled and not engine.discovered
        poll, sender = await asyncio.wait_for(loop.sock_recvfrom(receiver, 1024), 1)
        assert parse_poll(poll) and engine.output_status == "waiting"
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(loop.sock_recvfrom(receiver, 1024), 0.06)
        await loop.sock_sendto(receiver, bytes(node_reply()), sender)
        first, _ = await asyncio.wait_for(loop.sock_recvfrom(receiver, 1024), 1)
        assert first[:10] == HEADER + b"\x00\x50" and first[18:] == expected
        assert first[18] == 123 and first[18 + 23] == 219
        assert engine.output_status == "active"
    finally:
        await client.close()
        receiver.close()
