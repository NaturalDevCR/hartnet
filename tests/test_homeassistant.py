"""Actual HA runtime + actual HTTP app; Art-Net is restricted to loopback.

Run in a Python 3.14 environment with pytest-homeassistant-custom-component.
The regular engine test environment skips this module.
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

import probatio
from hartnet.server import ENGINE, create_app
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

TOKEN = "test-ha-api-token-123456789"


@pytest.fixture(autouse=True)
def local_component(hass, enable_custom_integrations):
    from conftest import ROOT

    import custom_components

    # The HA harness imports its own testing_config/custom_components package.
    # Add this checkout to that package's search path without mocking HA's loader.
    component_path = str(ROOT / "custom_components")
    if component_path not in custom_components.__path__:
        custom_components.__path__.append(component_path)


async def test_config_flow_connects_to_actual_app(
    hass, enable_custom_integrations, socket_enabled, aiohttp_client, tmp_path, party
):
    app = create_app(tmp_path / "project.json", TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)
    result = await hass.config_entries.flow.async_init("hartnet", context={"source": SOURCE_USER})
    assert result["type"] == "form"
    fields = probatio.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert any(field["name"] == "host" for field in fields)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "127.0.0.1",
            "port": client.port,
            "token": TOKEN,
        },
    )
    assert result["type"] == "create_entry", result
    assert result["result"].unique_id == party["id"]
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_native_entities_and_service_commands(
    hass, enable_custom_integrations, socket_enabled, aiohttp_client, tmp_path, party
):
    party["nodes"][0].update(host="127.0.0.1", port=19999)
    app = create_app(tmp_path / "project.json", TOKEN, project=party, bind_port=0)
    client = await aiohttp_client(app)
    await app[ENGINE].start()
    entry = MockConfigEntry(
        domain="hartnet",
        title="HartNet",
        unique_id=party["id"],
        data={
            "host": "127.0.0.1",
            "port": client.port,
            "token": TOKEN,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    lights, numbers = hass.states.async_all("light"), hass.states.async_all("number")
    assert len(lights) == 4 and len(numbers) == 4
    light = next(s for s in lights if "spot_1" in s.entity_id)
    number = next(s for s in numbers if "speed" in s.entity_id)
    assert light.state == "off"
    assert light.attributes["supported_color_modes"] == ["rgbw"]
    await hass.services.async_call(
        "light",
        "turn_on",
        {
            ATTR_ENTITY_ID: light.entity_id,
            "rgbw_color": [255, 0, 0, 0],
            "brightness": 128,
        },
        blocking=True,
    )
    assert hass.states.get(light.entity_id).state == "on"
    assert hass.states.get(light.entity_id).attributes["brightness"] == 128
    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: number.entity_id,
            "value": 87,
        },
        blocking=True,
    )
    assert float(hass.states.get(number.entity_id).state) == 87
    frame = next(iter(app[ENGINE].frames().values()))
    assert frame[:5] == bytes([128, 128, 0, 0, 0])
    assert 87 in (frame[23], frame[53])
    await app[ENGINE].stop()
    await entry.runtime_data.async_request_refresh()
    assert hass.states.get(light.entity_id).state == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_generic_number_select_switch(
    hass, enable_custom_integrations, socket_enabled, aiohttp_client, tmp_path, generic
):
    generic["nodes"][0].update(host="127.0.0.1", port=19999)
    app = create_app(tmp_path / "project.json", TOKEN, project=generic, bind_port=0)
    client = await aiohttp_client(app)
    await app[ENGINE].start()
    entry = MockConfigEntry(
        domain="hartnet",
        title="Generic",
        unique_id=generic["id"],
        data={
            "host": "127.0.0.1",
            "port": client.port,
            "token": TOKEN,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    pan = hass.states.async_all("number")[0]
    mode = hass.states.async_all("select")[0]
    relay = hass.states.async_all("switch")[0]
    assert pan.attributes["max"] == 65535
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: pan.entity_id, "value": 4660}, blocking=True
    )
    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: mode.entity_id, "option": "Auto"}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: relay.entity_id}, blocking=True)
    frame = next(iter(app[ENGINE].frames().values()))
    assert frame[:8] == bytes([0x12, 150, 255, 17, 0, 0, 0, 0x34])
    assert await hass.config_entries.async_unload(entry.entry_id)
