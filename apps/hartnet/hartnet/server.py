"""Authenticated local API and Home Assistant Ingress frontend."""

import asyncio
import hmac
import json
import os
import tempfile
from copy import deepcopy
from ipaddress import IPv4Address
from pathlib import Path

from aiohttp import web

from . import VERSION
from .engine import Engine
from .legacy import import_legacy
from .model import ValidationError, empty_project, export_profiles, require, validate_project

STATIC = Path(__file__).parent / "static"
ENGINE = web.AppKey("engine", Engine)
LOCK = web.AppKey("lock", asyncio.Lock)


def atomic_save(path, project):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(project, indent=2, ensure_ascii=False).encode()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hartnet-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            # Preserve the immediately previous patch before committing the replacement.
            backup = path.with_suffix(".previous.json")
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_app(data_path, token, *, dev=False, project=None, bind_port=6454):
    require(dev or isinstance(token, str) and len(token) >= 16, "Set api_token to at least 16 characters")
    path = Path(data_path)
    if project is None:
        project = json.loads(path.read_text()) if path.exists() else empty_project()
    project = validate_project(project)
    if not path.exists():
        atomic_save(path, project)

    @web.middleware
    async def security(request, handler):
        # Trust the TCP peer, never X-Forwarded-For / X-Ingress-Path from arbitrary hosts.
        ingress = request.remote == "172.30.32.2"
        development = dev and request.remote in ("127.0.0.1", "::1")
        bearer = request.headers.get("Authorization", "")
        authorized = bool(token) and hmac.compare_digest(bearer, f"Bearer {token}")
        if not (ingress or development or request.path.startswith("/api/") and authorized):
            raise web.HTTPUnauthorized(text="Home Assistant Ingress or an API token is required")
        if request.method not in {"GET", "HEAD"}:
            require(request.content_type == "application/json", "Content-Type application/json required")
            # Cross-origin scripts cannot mutate the API with a form POST. No permissive CORS.
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                raise web.HTTPForbidden(text="Cross-site request rejected")
        response = await handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'"
        )
        return response

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except (ValidationError, ValueError, TypeError, KeyError, RecursionError) as err:
            return web.json_response({"error": str(err)}, status=400)
        except OSError as err:
            return web.json_response({"error": f"Could not complete operation: {err}"}, status=503)

    app = web.Application(middlewares=[errors, security], client_max_size=1_000_000)
    app[ENGINE] = Engine(project, bind_port=bind_port)
    app[LOCK] = asyncio.Lock()

    async def info(request):
        return web.json_response({"version": VERSION, "id": app[ENGINE].project["id"], "name": "HartNet"})

    async def snapshot(request):
        return web.json_response(app[ENGINE].snapshot())

    async def commit(candidate):
        require(not app[ENGINE].enabled, "Stop output before changing configuration")
        require(isinstance(candidate, dict), "Invalid project")
        candidate = deepcopy(candidate)
        # The installation identity survives importing a different patch or backup.
        candidate["id"] = app[ENGINE].project["id"]
        validated = validate_project(candidate)
        await asyncio.to_thread(atomic_save, path, validated)
        app[ENGINE].load(validated)

    async def save_project(request):
        body = await request.json()
        async with app[LOCK]:
            await commit(body)
        return await snapshot(request)

    async def legacy_preview(request):
        body = await request.json()
        require(type(body.get("scalars_as_numbers", False)) is bool, "scalars_as_numbers: boolean required")
        result = await asyncio.to_thread(
            import_legacy, body.get("yaml"), body.get("scalars_as_numbers", False)
        )
        return web.json_response(result)

    async def profiles(request):
        return web.json_response(
            export_profiles(app[ENGINE].project),
            headers={"Content-Disposition": 'attachment; filename="hartnet-profiles.json"'},
        )

    async def import_profiles(request):
        bundle = await request.json()
        require(
            bundle.get("format") == "hartnet-profiles" and bundle.get("schema_version") == 1,
            "Incompatible profile format",
        )
        require(isinstance(bundle.get("profiles"), list), "profiles: list required")
        async with app[LOCK]:
            candidate = deepcopy(app[ENGINE].project)
            existing = {p["id"]: p for p in candidate["profiles"]}
            for profile in bundle["profiles"]:
                require(isinstance(profile, dict) and isinstance(profile.get("id"), str), "Invalid profile")
                require(
                    profile["id"] not in existing or existing[profile["id"]] == profile,
                    "A different profile already has this ID; use a new ID",
                )
                existing[profile["id"]] = profile
            candidate["profiles"] = list(existing.values())
            await commit(candidate)
        return await snapshot(request)

    async def command(request):
        body = await request.json()
        async with app[LOCK]:
            app[ENGINE].command(request.match_info["fixture"], body)
        return await snapshot(request)

    async def output(request):
        body = await request.json()
        require(type(body.get("enabled")) is bool, "enabled: boolean required")
        async with app[LOCK]:
            if body["enabled"]:
                await app[ENGINE].start()
            else:
                await app[ENGINE].stop()
        return await snapshot(request)

    async def discover(request):
        body = await request.json()
        target = str(IPv4Address(body.get("target", "")))
        async with app[LOCK]:
            result = await app[ENGINE].discover(target)
        return web.json_response(result)

    async def index(request):
        return web.FileResponse(STATIC / "index.html")

    async def cleanup(application):
        await application[ENGINE].close()

    app.router.add_get("/", index)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.router.add_get("/api/info", info)
    app.router.add_get("/api/state", snapshot)
    app.router.add_put("/api/project", save_project)
    app.router.add_post("/api/legacy/preview", legacy_preview)
    app.router.add_get("/api/profiles", profiles)
    app.router.add_post("/api/profiles", import_profiles)
    app.router.add_post("/api/fixtures/{fixture}/command", command)
    app.router.add_post("/api/output", output)
    app.router.add_post("/api/discover", discover)
    app.on_cleanup.append(cleanup)
    return app
