"""Atomic, versioned project and desired-state storage.

Only accepted command targets are persisted, never per-frame fade samples.
"""

import asyncio
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from .engine import Engine
from .model import require, validate_project

FORMAT = "hartnet-store"
VERSION = 1


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hartnet-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_save(path, document, *, backup=True):
    path = Path(path)
    payload = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False).encode()
    if backup and path.exists():
        atomic_write(path.with_suffix(".previous.json"), path.read_bytes())
    atomic_write(path, payload)


async def durable_save(path, document, *, backup=False):
    # Finish disk IO before the caller can release its transaction lock on cancellation.
    task = asyncio.create_task(asyncio.to_thread(atomic_save, path, document, backup=backup))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def document(project, states, output_enabled):
    return {
        "format": FORMAT,
        "storage_version": VERSION,
        "project": deepcopy(project),
        "runtime": {"states": deepcopy(states), "output_enabled": output_enabled},
    }


def load_document(raw):
    # Version 0.2 and earlier saved only a portable project. They never saved output intent.
    if isinstance(raw, dict) and raw.get("format") != FORMAT:
        project = validate_project(raw)
        return project, None
    require(isinstance(raw, dict) and raw.get("format") == FORMAT, "Invalid storage format")
    require(
        type(raw.get("storage_version")) is int and raw["storage_version"] == VERSION,
        "Unsupported storage version",
    )
    project = validate_project(raw.get("project"))
    engine = Engine(project)
    engine.restore_runtime(raw.get("runtime"))
    return project, deepcopy(raw["runtime"])
