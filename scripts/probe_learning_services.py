"""Explicit four-call model smoke test using only authored data in an isolated test schema."""

import json
import os
from uuid import uuid4

from aristotle_backend.app import create_app
from aristotle_backend.config import PROJECT_ROOT, database_url
from aristotle_backend.db import ModelCall, Question, create_database_engine
from aristotle_backend.design_seed import seed_design_flow
from aristotle_backend.migrations import upgrade_database
from aristotle_backend.model_jobs import run_job
from aristotle_backend.seed import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url


def main():
    business = make_url(database_url())
    parsed = make_url(
        os.getenv("ARISTOTLE_TEST_DATABASE_URL")
        or business.set(database=business.database + "_test").render_as_string(hide_password=False)
    )
    if parsed.get_backend_name() != "postgresql" or parsed.database == business.database:
        raise RuntimeError("Use a separate PostgreSQL test database for the live probe")
    admin = create_database_engine(parsed.render_as_string(hide_password=False))
    schema = "probe_" + uuid4().hex
    with admin.begin() as con:
        con.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = parsed.update_query_dict({"options": f"-csearch_path={schema},public"}).render_as_string(
        hide_password=False
    )
    app = None
    try:
        upgrade_database(url)
        app = create_app(url)
        password = os.getenv("ARISTOTLE_DEMO_PASSWORD", "demo-password")
        seed_demo(app.state.sessions, password)
        seed_design_flow(app.state.sessions)
        with TestClient(app) as client:

            def login(username):
                response = client.post(
                    "/api/v1/auth/login", json={"username": username, "password": password}
                )
                if response.status_code != 200:
                    raise RuntimeError("Probe login failed")
                return {"Authorization": "Bearer " + response.json()["access_token"]}

            student, editor = login("student1"), login("editor")
            config = client.get("/api/v1/model-status", headers=student).json()
            if not all(config[k]["configured"] for k in ("generation", "embedding")):
                raise RuntimeError(
                    "Configure both generation and embedding services before this explicit probe"
                )
            before = client.get("/api/v1/learning-state", headers=student).json()

            def finish(response, headers):
                if response.status_code != 202:
                    raise RuntimeError("Probe job could not be queued: " + str(response.status_code))
                job_id = response.json()["id"]
                run_job(app.state.sessions, job_id)
                result = client.get("/api/v1/jobs/" + job_id, headers=headers).json()
                if result["status"] != "succeeded":
                    raise RuntimeError("Probe failed: " + result["result"].get("error_code", "unknown"))
                return result["result"]

            indexed = finish(
                client.post(
                    "/api/v1/retrieval/index",
                    headers=student,
                    json={"knowledge_id": "stack", "allow_external": True},
                ),
                student,
            )
            print("PASS: authored public source indexed through the real embedding service", flush=True)
            response = client.post(
                "/api/v1/retrieval/search",
                headers=student,
                json={
                    "knowledge_id": "stack",
                    "query": "最晚放进去的元素为什么先取出来？",
                    "mode": "semantic",
                    "allow_external_query": True,
                },
            )
            if response.status_code != 200 or not response.json().get("items"):
                raise RuntimeError("Real pgvector semantic search returned no usable source")
            hits = response.json()["items"]
            print("PASS: real pgvector cosine retrieval", flush=True)
            question = {
                "question_id": "live_probe_stack",
                "version": 1,
                "knowledge_id": "stack",
                "prompt": "空栈依次入栈 A、B，再出栈一次，剩余元素是什么？",
                "options": ["A", "B"],
                "answer": "A",
                "explanation": "后进的 B 先出栈，留下 A。",
                "source": "独立探测题，不发布",
            }
            assert client.post("/api/v1/admin/questions", headers=editor, json=question).status_code == 201
            candidate = finish(
                client.post("/api/v1/admin/questions/live_probe_stack:v1/model-annotations", headers=editor),
                editor,
            )
            with app.state.sessions() as db:
                assert db.get(Question, "live_probe_stack:v1").status == "pending_review"
            print("PASS: real generation produces a candidate; content remains unpublished", flush=True)
            explained = finish(
                client.post(
                    "/api/v1/explanations",
                    headers=student,
                    json={
                        "knowledge_id": "stack",
                        "query": "依据这些资料解释栈的后进先出，并给出简短的操作示例。",
                        "source_keys": [hit["id"] for hit in hits[:2]],
                        "allow_external": True,
                    },
                ),
                student,
            )
            assert explained["citations"] and all(
                key in {h["id"] for h in hits} for key in explained["citations"]
            )
            assert client.get("/api/v1/learning-state", headers=student).json() == before
            print("PASS: grounded explanation with valid references; learning evidence unchanged", flush=True)
            with app.state.sessions() as db:
                calls = list(db.scalars(select(ModelCall)))
                summary = {
                    "passed": True,
                    "database": "postgresql",
                    "storage": "pgvector",
                    "embedding_model": config["embedding"]["model"],
                    "generation_model": config["generation"]["model"],
                    "indexed": indexed["indexed"],
                    "semantic_hits": len(hits),
                    "best_score": hits[0]["score"],
                    "candidate_requires_review": candidate["requires_review"],
                    "explanation_citations": len(explained["citations"]),
                    "learning_evidence_unchanged": True,
                    "calls": [
                        {
                            "purpose": c.purpose,
                            "status": c.status,
                            "requests": c.external_calls,
                            "usage": c.usage,
                        }
                        for c in calls
                    ],
                }
            path = PROJECT_ROOT / ".local" / "learning-services-probe.json"
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            print("Verification summary: " + str(path), flush=True)
    finally:
        if app:
            app.state.engine.dispose()
        with admin.begin() as con:
            con.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


if __name__ == "__main__":
    main()
