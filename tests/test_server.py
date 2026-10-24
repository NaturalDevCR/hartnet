import copy
import json

from hartnet.server import ENGINE, create_app

TOKEN = "test-token-only-123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


async def test_api_auth_preview_commit_persistence(aiohttp_client, tmp_path, legacy_yaml):
    path = tmp_path / "project.json"
    app = create_app(path, TOKEN, bind_port=0)
    client = await aiohttp_client(app)
    assert (await client.get("/api/state")).status == 401
    assert (await client.get("/", headers=HEADERS)).status == 401  # API token doesn't expose the UI.
    assert (await client.get("/api/state", headers={"X-Ingress-Path": "/fake"})).status == 401
    info = await (await client.get("/api/info", headers=HEADERS)).json()
    response = await client.post(
        "/api/legacy/preview", headers=HEADERS, json={"yaml": legacy_yaml, "scalars_as_numbers": True}
    )
    preview = await response.json()
    assert response.status == 200 and len(preview["project"]["fixtures"]) == 8
    assert app[ENGINE].transport is None
    assert json.loads(path.read_text())["project"]["fixtures"] == []  # Preview is side-effect free.
    response = await client.put("/api/project", headers=HEADERS, json=preview["project"])
    saved = await response.json()
    assert response.status == 200
    assert not saved["output_enabled"] and app[ENGINE].transport is None
    assert saved["project"]["id"] == info["id"]
    assert len(json.loads(path.read_text())["project"]["fixtures"]) == 8
    exported = await (await client.get("/api/profiles", headers=HEADERS)).json()
    assert "192.0.2.30" not in json.dumps(exported)
    assert path.with_suffix(".previous.json").exists()


async def test_invalid_patch_does_not_replace_config(aiohttp_client, tmp_path, sample_patch):
    app = create_app(tmp_path / "project.json", TOKEN, project=sample_patch, bind_port=0)
    client = await aiohttp_client(app)
    broken = copy.deepcopy(sample_patch)
    broken["fixtures"][0]["start_channel"] = 512
    response = await client.put("/api/project", headers=HEADERS, json=broken)
    assert response.status == 400
    assert app[ENGINE].project == sample_patch
    assert app[ENGINE].transport is None


async def test_invalid_body_and_csrf(aiohttp_client, tmp_path):
    app = create_app(tmp_path / "project.json", TOKEN)
    client = await aiohttp_client(app)
    assert (await client.post("/api/output", headers=HEADERS, json={"enabled": "yes"})).status == 400
    assert (await client.put("/api/project", headers=HEADERS, json=[])).status == 400
    assert (await client.post("/api/output", headers=HEADERS, data="enabled=true")).status == 400
    assert (
        await client.post(
            "/api/output", headers={**HEADERS, "Sec-Fetch-Site": "cross-site"}, json={"enabled": True}
        )
    ).status == 403


async def test_api_read_only_while_outputting(aiohttp_client, tmp_path, sample_patch):
    sample_patch["nodes"][0].update(host="127.0.0.1", port=19999)
    app = create_app(tmp_path / "project.json", TOKEN, project=sample_patch, bind_port=0)
    client = await aiohttp_client(app)
    await client.post("/api/output", headers=HEADERS, json={"enabled": True})
    assert app[ENGINE].enabled
    response = await client.put("/api/project", headers=HEADERS, json=sample_patch)
    assert response.status == 400
    await client.post("/api/output", headers=HEADERS, json={"enabled": False})
    assert not app[ENGINE].enabled
