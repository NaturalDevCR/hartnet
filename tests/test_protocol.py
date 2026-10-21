import asyncio
import socket
import time

import pytest
from hartnet.engine import Engine
from hartnet.protocol import art_dmx, art_poll, parse_poll_reply


@pytest.mark.parametrize("universe", [0, 1, 15, 16, 255, 256, 4096, 32767])
def test_wire_address_and_padding(universe):
    packet = art_dmx(universe, [1, 2, 3], 255)
    assert packet[:14] == b"Art-Net\x00\x00\x50\x00\x0e\xff\x00"
    assert int.from_bytes(packet[14:16], "little") == universe
    assert packet[16:18] == b"\x00\x04"
    assert packet[18:] == b"\x01\x02\x03\x00"


def test_poll_reply_old_and_bound_nodes():
    assert len(art_poll()) == 14
    data = bytearray(239)
    data[:10] = b"Art-Net\x00\x00\x21"
    data[10:14] = socket.inet_aton("10.0.0.2")
    data[18:20] = bytes([127, 15])
    data[26:31] = b"Node\0"
    data[172:174] = bytes([0, 1])
    data[174] = 0x80
    data[190] = 15
    data[211] = 3
    assert parse_poll_reply(bytes(data), "10.0.0.3")["universes"] == [32767]
    assert parse_poll_reply(bytes(data), "10.0.0.3")["bind_index"] == 3
    assert parse_poll_reply(bytes(data[:207]), "10.0.0.3")["bind_index"] == 0
    data[173] = 255
    assert parse_poll_reply(bytes(data), "10.0.0.3") is None
    assert parse_poll_reply(b"bad", "10.0.0.3") is None


async def test_actual_udp_loopback_fps_refresh_and_stop(party):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    party["nodes"][0].update(host="127.0.0.1", port=receiver.getsockname()[1], max_fps=10, refresh_every=0.2)
    engine = Engine(party, bind_host="127.0.0.1", bind_port=0)
    fixture = party["fixtures"][0]
    engine.command(fixture["id"], {"on": True, "brightness": 0})
    try:
        await engine.start()
        loop = asyncio.get_running_loop()
        first = await asyncio.wait_for(loop.sock_recv(receiver, 1024), timeout=1)
        assert len(first) == 530 and first[18:23] == bytes(5)
        engine.command(fixture["id"], {"on": True, "brightness": 255, "transition": 0.4})
        times, packets = [], []
        async with asyncio.timeout(2):
            while not packets or packets[-1][18] != 255:
                packets.append(await loop.sock_recv(receiver, 1024))
                times.append(time.monotonic())
        assert any(0 < p[18] < 255 for p in packets)
        assert all(b - a >= 0.08 for a, b in zip(times, times[1:], strict=False))
        refreshed = await asyncio.wait_for(loop.sock_recv(receiver, 1024), timeout=0.5)
        assert refreshed[18] == 255
        await engine.stop()
        assert not engine.enabled
        # Drain any datagram already in flight before asserting the stopped state.
        while True:
            try:
                receiver.recv(1024)
            except BlockingIOError:
                break
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(loop.sock_recv(receiver, 1024), timeout=0.25)
    finally:
        await engine.close()
        receiver.close()
