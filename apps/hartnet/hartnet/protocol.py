"""Small, defensive ArtDmx / ArtPoll codec. Not a full Art-Net controller stack."""

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


def art_poll():
    # Minimum interoperable poll, no targeted extension or diagnostic subscription.
    return HEADER + struct.pack("<H", 0x2000) + b"\x00\x0e\x00\x00"


def parse_poll_reply(data, sender):
    if len(data) < 207 or data[:10] != HEADER + b"\x00\x21":
        return None
    packet = data.ljust(239, b"\0")
    count = int.from_bytes(packet[172:174], "big")
    if count > 4:
        return None
    host = str(IPv4Address(packet[10:14]))
    if host == "0.0.0.0":
        host = sender
    base = ((packet[18] & 0x7F) << 8) | ((packet[19] & 0xF) << 4)
    outputs = [base | (packet[190 + i] & 0xF) for i in range(count) if packet[174 + i] & 0x80]
    return {
        "host": host,
        "bind_index": packet[211],
        "name": packet[26:44].split(b"\0")[0].decode("ascii", "replace"),
        "description": packet[44:108].split(b"\0")[0].decode("ascii", "replace"),
        "universes": outputs,
        "rdm": bool(packet[23] & 2),
        "mac": packet[201:207].hex(":"),
    }
