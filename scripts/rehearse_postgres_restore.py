"""Rehearse backup, restore and deletion replay on two new disposable Compose databases."""

import json
import os
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

from aristotle_backend.app import create_app
from aristotle_backend.config import database_url
from aristotle_backend.db import Material
from aristotle_backend.flow_support import erase_material
from aristotle_backend.migrations import upgrade_database
from aristotle_backend.seed import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def postgres_tool(program, user, *args, **streams):
    command = ["docker", "compose", "exec", "-T", "postgres", program, "-U", user, *args]
    subprocess.run(command, cwd=ROOT, check=True, **streams)


@contextmanager
def scratch_database(base):
    name = "aristotle_drill_" + uuid4().hex
    postgres_tool("createdb", base.username, name)
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        postgres_tool("dropdb", base.username, name)


def write_fixture(api):
    user = api.post(
        "/api/v1/auth/login",
        json={"username": "student1", "password": os.getenv("ARISTOTLE_DEMO_PASSWORD", "demo-password")},
    )
    user.raise_for_status()
    headers = {"Authorization": "Bearer " + user.json()["access_token"]}
    task = api.post("/api/v1/tasks", headers=headers, json={"mode": "practice", "knowledge_id": "linear"})
    task.raise_for_status()
    row = task.json()
    q = row["questions"][0]
    api.post(
        f"/api/v1/tasks/{row['id']}/attempts",
        headers=headers,
        json={"question_key": q["key"], "selected": q["options"][0], "submission_id": str(uuid4())},
    ).raise_for_status()
    material = api.post(
        "/api/v1/materials",
        headers=headers,
        json={"title": "隔离演练资料", "text": "仅用于删除重放验证", "knowledge_id": "linear"},
    )
    material.raise_for_status()
    return headers, material.json()["id"]


def core_snapshot(db):
    # Identifiers are fixed project table names. Only counts and hashes leave the database.
    result = {}
    for table in ("users", "questions", "reviews", "tasks", "attempts"):
        rows = db.execute(
            text(
                f"SELECT count(*), md5(string_agg(digest, '' ORDER BY digest)) "
                f"FROM (SELECT md5(row_to_json(t)::text) AS digest FROM {table} AS t) AS rows"
            )
        ).one()
        if not rows[0]:
            raise RuntimeError(f"Missing fixture rows in {table}")
        result[table] = tuple(rows)
    return result


def verify_restore(target, journal, baseline):
    app = create_app(target)
    try:
        with app.state.sessions.begin() as db:
            if core_snapshot(db) != baseline:
                raise RuntimeError("Restored learning or review rows differ from snapshot")
            for key in json.loads(journal.read_text()):
                row = db.get(Material, key)
                if row is None or not row.text:
                    raise RuntimeError("Snapshot has no pre-deletion material for the replay")
                erase_material(db, row)
        with app.state.sessions() as db:
            for key in json.loads(journal.read_text()):
                row = db.get(Material, key)
                if not row.deleted or row.text or row.confirmed or row.external_processing_allowed:
                    raise RuntimeError("Deleted content or permission resurfaced")
    finally:
        app.state.engine.dispose()


def rehearse():
    base = make_url(database_url())
    if base.get_backend_name() != "postgresql" or base.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Requires a locally published Compose PostgreSQL connection")
    with ExitStack() as cleanup:
        source, target = (cleanup.enter_context(scratch_database(base)) for _ in range(2))
        folder = Path(cleanup.enter_context(tempfile.TemporaryDirectory()))
        upgrade_database(source)
        app = create_app(source)
        cleanup.callback(app.state.engine.dispose)
        seed_demo(app.state.sessions)
        api = cleanup.enter_context(TestClient(app))
        headers, key = write_fixture(api)
        with app.state.sessions() as db:
            baseline = core_snapshot(db)
        archive, journal = folder / "snapshot.dump", folder / "deleted.json"
        with archive.open("xb") as stream:
            postgres_tool("pg_dump", base.username, "-Fc", "-d", make_url(source).database, stdout=stream)
        api.delete("/api/v1/materials/" + key, headers=headers).raise_for_status()
        with app.state.sessions() as db:
            deleted = list(db.scalars(select(Material.id).where(Material.deleted.is_(True))))
        if key not in deleted:
            raise RuntimeError("Deletion was not recorded in source")
        journal.write_text(json.dumps(deleted))
        started = time.monotonic()
        with archive.open("rb") as stream:
            postgres_tool(
                "pg_restore",
                base.username,
                "--exit-on-error",
                "--single-transaction",
                "-d",
                make_url(target).database,
                stdin=stream,
            )
        verify_restore(target, journal, baseline)
        return {
            "storage": "PostgreSQL / pgvector, two isolated databases",
            "tables_verified": {k: v[0] for k, v in baseline.items()},
            "matched_row_digests": True,
            "replayed_material_deletions": len(deleted),
            "restore_and_verify_seconds": round(time.monotonic() - started, 3),
            "archive_bytes": archive.stat().st_size,
        }


if __name__ == "__main__":
    print(json.dumps(rehearse(), ensure_ascii=False, indent=2))
