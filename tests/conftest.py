from pathlib import Path

import pytest
from hartnet.legacy import import_legacy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_yaml():
    return (ROOT / "apps/hartnet/hartnet/static/party-legacy.yaml").read_text()


@pytest.fixture
def party(legacy_yaml):
    return import_legacy(legacy_yaml, scalars_as_numbers=True)["project"]


@pytest.fixture
def generic(party):
    party["fixtures"] = [party["fixtures"][0]]
    profile_id = party["fixtures"][0]["profile_id"]
    party["profiles"] = [
        {
            "id": profile_id,
            "name": "Generic device",
            "controls": [
                {"id": "pan", "name": "Pan", "kind": "number", "slots": [1, 8], "default": 0},
                {
                    "id": "mode",
                    "name": "Mode",
                    "kind": "select",
                    "slots": [2],
                    "default": 0,
                    "options": [{"label": "Manual", "value": 0}, {"label": "Auto", "value": 150}],
                },
                {"id": "relay", "name": "Relay", "kind": "switch", "slots": [3], "default": 0},
                {"id": "fixed", "name": "Fixed", "kind": "constant", "slots": [4], "default": 17},
            ],
        }
    ]
    return party
