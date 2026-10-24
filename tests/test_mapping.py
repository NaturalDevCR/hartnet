import copy
import json

import pytest
from hartnet.engine import Engine
from hartnet.legacy import import_legacy
from hartnet.model import ValidationError, export_profiles, validate_project


def test_import_sample_patch_exact_addresses(sample_patch):
    assert len(sample_patch["nodes"]) == 1
    node = sample_patch["nodes"][0]
    assert (node["host"], node["port"], node["max_fps"], node["refresh_every"], node["full_universe"]) == (
        "192.0.2.30",
        6454,
        25,
        1,
        True,
    )
    assert [f["start_channel"] for f in sample_patch["fixtures"]] == [1, 10, 23, 24, 30, 40, 53, 54]
    assert {f["universe"] for f in sample_patch["fixtures"]} == {0}
    profiles = {p["id"]: p for p in sample_patch["profiles"]}
    kinds = [profiles[f["profile_id"]]["controls"][0]["kind"] for f in sample_patch["fixtures"]]
    assert kinds == ["dimmer", "dimmer", "number", "number", "dimmer", "dimmer", "number", "number"]


def test_render_golden_sample_frame(sample_patch):
    engine = Engine(sample_patch)
    assert not engine.enabled and engine.transport is None
    spot, derby, macro, speed = sample_patch["fixtures"][:4]
    engine.command(spot["id"], {"on": True, "brightness": 128, "color": [255, 0, 0, 0]})
    engine.command(derby["id"], {"on": True, "brightness": 255, "color": [0, 255, 0, 128]})
    for fixture, value in [(macro, 200), (speed, 83)]:
        control = engine.controls(fixture)[0]
        engine.command(fixture["id"], {"values": {control["id"]: value}})
    frame = next(iter(engine.frames().values()))
    assert len(frame) == 512
    assert frame[:5] == bytes([128, 128, 0, 0, 0])
    assert frame[9:15] == bytes([255, 0, 0, 255, 0, 128])
    assert frame[22:24] == bytes([200, 83])
    assert frame[15:22] == bytes(7)
    assert frame[40] == 0  # Second Derby's fixed channel 41.
    engine.command(derby["id"], {"on": False})
    frame = next(iter(engine.frames().values()))
    assert frame[9:15] == bytes(6)
    assert frame[22:24] == bytes([200, 83])  # Light off does not overwrite macro/speed.


def test_generic_controls_nonadjacent_fine_byte(generic):
    engine = Engine(generic)
    fixture = generic["fixtures"][0]
    engine.command(fixture["id"], {"values": {"pan": 0x1234, "mode": 150, "relay": 255}})
    frame = next(iter(engine.frames().values()))
    assert frame[:8] == bytes([0x12, 150, 255, 17, 0, 0, 0, 0x34])
    previous = copy.deepcopy(engine.states)
    with pytest.raises(ValidationError):
        engine.command(fixture["id"], {"values": {"pan": 80, "mode": 23}})
    assert engine.states == previous  # Command validation is atomic.


@pytest.mark.parametrize("slots", [[1], [1, 8], [1, 7, 9], [9, 7, 4, 1]])
def test_full_precision_maximum(generic, slots):
    generic["profiles"][0]["controls"] = [
        {"id": "value", "name": "Value", "kind": "number", "slots": slots, "default": 0}
    ]
    engine = Engine(generic)
    engine.command(generic["fixtures"][0]["id"], {"values": {"value": 256 ** len(slots) - 1}})
    frame = next(iter(engine.frames().values()))
    assert all(frame[slot - 1] == 255 for slot in slots)


@pytest.mark.parametrize(
    "mutation", ["overlap", "overflow", "duplicate-slot", "unknown-kind", "invalid-default"]
)
def test_reject_invalid_patch(generic, mutation):
    if mutation == "overlap":
        extra = copy.deepcopy(generic["fixtures"][0])
        extra["id"] = "other"
        generic["fixtures"].append(extra)
    elif mutation == "overflow":
        generic["fixtures"][0]["start_channel"] = 510
    elif mutation == "duplicate-slot":
        generic["profiles"][0]["controls"][0]["slots"] = [1, 2]
    elif mutation == "unknown-kind":
        generic["profiles"][0]["controls"][0]["kind"] = "launch"
    else:
        generic["profiles"][0]["controls"][1]["default"] = 9
    with pytest.raises(ValidationError):
        validate_project(generic)


def test_exports_exclude_installation(sample_patch):
    bundle = export_profiles(sample_patch)
    serialized = json.dumps(bundle)
    assert "192.0.2.30" not in serialized
    assert all(field not in serialized for field in ('"node_id"', '"start_channel"', '"universe"'))
    assert bundle["format"] == "hartnet-profiles"


def test_legacy_rejects_partial_unsupported_import(legacy_yaml):
    with pytest.raises(ValidationError, match="Unsupported legacy function"):
        import_legacy(legacy_yaml.replace("drgbw", "dxy"))


def test_legacy_import_is_repeatable(legacy_yaml):
    first, second = import_legacy(legacy_yaml), import_legacy(legacy_yaml)
    assert first["project"]["fixtures"] == second["project"]["fixtures"]
    assert first["project"]["profiles"] == second["project"]["profiles"]
