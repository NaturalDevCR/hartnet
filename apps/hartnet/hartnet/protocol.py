"""Defensive ArtDmx and Art-Net discovery codecs."""

import struct
from ipaddress import IPv4Address

from .model import integer

HEADER = b"Art-Net\0"
PORT = 6454


def art_dmx(universe, data, sequence=1):
    integer(universe, 0, 32767, "universe")
    integer(sequence, 0, 255, "sequence")
    if not 1 <= len(data) <= 512:
        raise ValueError("ArtDmx needs 1–512 slots (even padding is added)")
    payload = bytes(data)
    payload += b"\0" * (max(2, len(payload) + len(payload) % 2) - len(payload))
    return (
        HEADER
        + struct.pack("<H", 0x5000)
        + struct.pack(">HBB", 14, sequence, 0)
        + struct.pack("<H", universe)
        + struct.pack(">H", len(payload))
        + payload
    )


def art_poll(*, bottom=None, top=None):
    if bottom is None and top is None:
        return HEADER + struct.pack("<H", 0x2000) + b"\x00\x0e\x00\x00"
    integer(bottom, 0, 32767, "bottom")
    integer(top, bottom, 32767, "top")
    # Targeted unicast, with change notifications requested; no diagnostics.
    return HEADER + struct.pack("<H", 0x2000) + struct.pack(">HBBHHHH", 14, 0x22, 0, top, bottom, 0, 0)


def parse_poll(data):
    if len(data) < 14 or data[:10] != HEADER + b"\x00\x20" or int.from_bytes(data[10:12], "big") < 14:
        return None
    packet = data.ljust(18, b"\0")
    top, bottom = struct.unpack(">HH", packet[14:18])
    if data[12] & 0x20 and not 0 <= bottom <= top <= 32767:
        return None
    return {"targeted": bool(data[12] & 0x20), "bottom": bottom, "top": top}


def controller_reply(host, counter=0):
    packet = bytearray(239)
    packet[:10] = HEADER + b"\x00\x21"
    packet[10:14] = IPv4Address(host).packed
    struct.pack_into("<H", packet, 14, PORT)
    packet[16:18] = b"\x00\x04"
    packet[20:22] = b"\x00\xff"  # OemUnknown; no assigned HartNet OEM code yet.
    packet[23] = 0xE0  # Normal indicators; network-configured addresses; no RDM.
    packet[26:33] = b"HartNet"
    description = b"HartNet profile controller"
    packet[44 : 44 + len(description)] = description
    report = f"#0001 [{counter % 10000:04d}] Ready".encode("ascii")
    packet[108 : 108 + len(report)] = report
    # No physical DMX input/output ports, no invented MAC/manufacturer ID.
    packet[200] = 1  # StController
    packet[207:211] = IPv4Address(host).packed
    packet[211] = 1
    packet[212] = 0x08  # 15-bit Port-Address support.
    struct.pack_into(">H", packet, 226, 44)
    return bytes(packet)


def parse_poll_reply(data, sender):
    if len(data) < 207 or data[:10] != HEADER + b"\x00\x21":
        return None
    packet = bytes(data).ljust(239, b"\0")
    count = int.from_bytes(packet[172:174], "big")
    if count > 4:
        return None
    host = str(IPv4Address(packet[10:14]))
    if host == "0.0.0.0":
        host = sender
    base = ((packet[18] & 0x7F) << 8) | ((packet[19] & 0xF) << 4)
    outputs = [
        base | (packet[190 + i] & 0xF)
        for i in range(count)
        if packet[174 + i] & 0x80 and not packet[174 + i] & 0x3F and not packet[182 + i] & 1
    ]
    inputs = [
        base | (packet[186 + i] & 0xF)
        for i in range(count)
        if packet[174 + i] & 0x40 and not packet[174 + i] & 0x3F and not packet[178 + i] & 9
    ]
    return {
        "host": host,
        "bind_index": packet[211],
        "name": packet[26:44].split(b"\0")[0].decode("ascii", "replace"),
        "description": packet[44:108].split(b"\0")[0].decode("ascii", "replace"),
        "universes": outputs,
        "input_universes": inputs,
        "subscriptions": sorted(set(inputs + outputs)),
        "style": packet[200],
        "rdm": bool(packet[23] & 2),
        "mac": packet[201:207].hex(":"),
    }
