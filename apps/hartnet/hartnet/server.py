"""Authenticated local API and Home Assistant Ingress frontend."""

import asyncio
import hmac
import json
from copy import deepcopy
from ipaddress import IPv4Address
from pathlib import Path

from aiohttp import web

from . import VERSION
from .engine import Engine
from .legacy import import_legacy
from .model import ValidationError, empty_project, export_profiles, require, validate_project
from .storage import atomic_save, document, durable_save, load_document

STATIC = Path(__file__).parent / "static"
ENGINE = web.AppKey("engine", Engine)
LOCK = web.AppKey("lock", asyncio.Lock)


def create_app(data_path, token, *, dev=False, project=None, bind_port=6454):
    require(dev or isinstance(token, str) and len(token) >= 16, "Set api_token to at least 16 characters")
    path = Path(data_path)
    runtime = None
    raw = json.loads(path.read_text()) if path.exists() else None
    if raw is not None:
        saved_project, runtime = load_document(raw)
        require(project is None or project == saved_project, "Existing project differs from supplied project")
        project = saved_project
    project = validate_project(project if project is not None else empty_project())
    engine = Engine(project, bind_port=bind_port)
    if runtime is not None:
        engine.restore_runtime(runtime)
    else:
        atomic_save(path, document(project, engine.states, False))

    @web.middleware
    async def security(request, handler):
        # Trust the TCP peer, never X-Forwarded-For / X-Ingress-Path from arbitrary hosts.
        ingress = request.remote == "172.30.32.2"
        development = dev and request.remote in ("127.0.0.1", "::1")
        bearer = request.headers.get("Authorization", "")
        authorized = bool(token) and hmac.compare_digest(bearer, f"Bearer {token}")
        health_probe = request.method in {"GET", "HEAD"} and request.path == "/health"
        if not (health_probe or ingress or development or request.path.startswith("/api/") and authorized):
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
    app[ENGINE] = engine
    app[LOCK] = asyncio.Lock()

    async def info(request):
        return web.json_response({"version": VERSION, "id": app[ENGINE].project["id"], "name": "HartNet"})

    async def snapshot(request):
        return web.json_response(app[ENGINE].snapshot())

    async def health(request):
        healthy = not engine.output_requested or engine.enabled
        return web.json_response({"status": "ok" if healthy else "error"}, status=200 if healthy else 503)

    async def object_body(request):
        body = await request.json()
        require(isinstance(body, dict), "Expected a JSON object")
        return body

    async def commit(candidate):
        require(not engine.output_requested, "Stop output before changing configuration")
        require(isinstance(candidate, dict), "Invalid project")
        candidate = deepcopy(candidate)
        # The installation identity survives importing a different patch or backup.
        candidate["id"] = app[ENGINE].project["id"]
        validated = validate_project(candidate)
        staged = Engine(validated)
        staged.carry_states_from(engine)
        await durable_save(path, document(validated, staged.states, False), backup=True)
        engine.load(validated)
        engine.states = staged.states

    async def save_project(request):
        body = await object_body(request)
        async with app[LOCK]:
            await commit(body)
        return await snapshot(request)

    async def legacy_preview(request):
        body = await object_body(request)
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
        bundle = await object_body(request)
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
        body = await object_body(request)
        async with app[LOCK]:
            fixture_id = request.match_info["fixture"]
            state, transition = engine.prepare_command(fixture_id, body)
            states = {**engine.states, fixture_id: state}
            if state != engine.states[fixture_id]:
                await durable_save(path, document(engine.project, states, engine.output_requested))
            engine.apply_command(fixture_id, state, transition)
        return await snapshot(request)

    async def output(request):
        body = await object_body(request)
        require(type(body.get("enabled")) is bool, "enabled: boolean required")
        async with app[LOCK]:
            require(not body["enabled"] or engine.fixtures, "Add fixtures before enabling output")
            if body["enabled"] != engine.output_requested:
                await durable_save(path, document(engine.project, engine.states, body["enabled"]))
            if body["enabled"]:
                await app[ENGINE].start()
            else:
                await app[ENGINE].stop()
        return await snapshot(request)

    async def discover(request):
        body = await object_body(request)
        target = str(IPv4Address(body.get("target", "")))
        async with app[LOCK]:
            result = await app[ENGINE].discover(target)
        return web.json_response(result)

    async def index(request):
        return web.FileResponse(STATIC / "index.html")

    async def cleanup(application):
        await application[ENGINE].close()

    async def startup(application):
        if application[ENGINE].output_requested:
            await application[ENGINE].start()

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
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
    app.on_startup.append(startup)
    return app
