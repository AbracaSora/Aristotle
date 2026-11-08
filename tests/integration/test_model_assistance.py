import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from aristotle_backend.db import Annotation, Material, ModelCall, Question, ServiceJob, SourceEmbedding, Task
from aristotle_backend.design_seed import seed_design_flow
from aristotle_backend.model_jobs import run_job
from aristotle_backend.retrieval import invalidate_material_index
from sqlalchemy import func, select


@pytest.fixture
def models(app, monkeypatch):
    for kind in ("LLM", "EMBEDDING"):
        monkeypatch.setenv(f"ARISTOTLE_{kind}_BASE_URL", "https://model.test/v1")
        monkeypatch.setenv(f"ARISTOTLE_{kind}_MODEL", "test-" + kind.lower())
        monkeypatch.setenv(f"ARISTOTLE_{kind}_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("ARISTOTLE_EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setenv("ARISTOTLE_MODEL_DAILY_LIMIT", "200")
    monkeypatch.setenv("ARISTOTLE_MODEL_RETRIES", "0")
    monkeypatch.setenv("ARISTOTLE_INLINE_WORKER", "1")
    seed_design_flow(app.state.sessions)
    requests = []

    def reply(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        assert request.headers["authorization"] == "Bearer test-only-not-a-real-key"
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "index": i,
                            "embedding": [1, 0, 0] if "栈" in text or "newest" in text else [0, 1, 0],
                        }
                        for i, text in enumerate(body["input"])
                    ],
                    "usage": {"prompt_tokens": 5, "total_tokens": 5},
                },
            )
        content = json.loads(body["messages"][-1]["content"])
        if "question_id" in content:
            output = {
                "question_id": content["question_id"],
                "question_version": content["question_version"],
                "primary_level": "understand",
                "secondary_levels": [],
                "rationale": "需要解释概念关系",
                "confidence": 0.9,
                "ambiguity_note": "",
            }
        else:
            output = {
                "answer": "栈按后进先出的规则组织操作。",
                "citations": [content["sources"][0]["id"]],
                "insufficient_evidence": False,
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    app.state.model_transport = httpx.MockTransport(reply)
    return requests, reply


def source(client, headers, text="栈的私人授权文本"):
    material = client.post(
        "/api/v1/materials",
        headers=headers,
        json={"title": "个人讲义", "text": text, "knowledge_id": "stack"},
    ).json()
    client.patch(
        "/api/v1/materials/" + material["id"],
        headers=headers,
        json={"knowledge_id": "stack", "confirmed": True},
    )
    return material["id"]


def index(client, headers):
    response = client.post(
        "/api/v1/retrieval/index", headers=headers, json={"knowledge_id": "stack", "allow_external": True}
    )
    assert response.status_code == 202, response.text
    return client.get("/api/v1/jobs/" + response.json()["id"], headers=headers).json()


def sources(client, headers):
    return client.get("/api/v1/retrieval/sources?knowledge_id=stack", headers=headers).json()["items"]


def explain(client, headers, hits, query="解释后进先出"):
    response = client.post(
        "/api/v1/explanations",
        headers=headers,
        json={
            "knowledge_id": "stack",
            "query": query,
            "source_keys": [h["id"] for h in hits[:2]],
            "allow_external": True,
        },
    )
    assert response.status_code == 202, response.text
    return client.get("/api/v1/jobs/" + response.json()["id"], headers=headers).json()


def test_map_uses_authored_edges_and_individual_evidence_without_creating_tasks(client, login, models, app):
    h = login()
    with app.state.sessions() as db:
        before = db.scalar(select(func.count()).select_from(Task))
    result = client.get("/api/v1/knowledge-map", headers=h).json()
    assert {"source": "linear", "target": "stack", "kind": "prerequisite"} in result["edges"]
    assert len(result["states"]) == len(result["nodes"]) and result["version"]
    assert all(state["evidence_count"] == 0 for state in result["states"])
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == before
    assert client.get("/api/v1/knowledge-map", headers=login("editor")).status_code == 403


def test_keyword_sources_obey_confirmation_ownership_and_explicit_outbound_consent(client, login, models):
    h, other = login(), login("student2")
    mid = source(client, h)
    result = client.post(
        "/api/v1/retrieval/search",
        headers=h,
        json={"knowledge_id": "stack", "query": "私人", "mode": "keyword"},
    ).json()
    assert any(hit["material_id"] == mid for hit in result["items"])
    assert all(hit["material_id"] != mid for hit in sources(client, other))
    assert (
        client.patch(
            f"/api/v1/materials/{mid}/external-consent", headers=other, json={"allowed": True}
        ).status_code
        == 404
    )
    assert (
        client.post("/api/v1/retrieval/index", headers=h, json={"knowledge_id": "stack"}).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/retrieval/search", headers=h, json={"mode": "semantic", "query": "栈"}
        ).status_code
        == 403
    )
    assert not models[0]


def test_real_protocol_index_and_pgvector_search_do_not_disguise_keywords(client, login, models, app):
    h = login()
    before = client.get("/api/v1/learning-state", headers=h).json()
    result = index(client, h)
    assert result["status"] == "succeeded", result
    assert result["result"]["indexed"] > 0
    query = "Take the newest item first"
    keyword = client.post(
        "/api/v1/retrieval/search",
        headers=h,
        json={"query": query, "mode": "keyword", "knowledge_id": "stack"},
    ).json()
    semantic = client.post(
        "/api/v1/retrieval/search",
        headers=h,
        json={"query": query, "mode": "semantic", "knowledge_id": "stack", "allow_external_query": True},
    ).json()
    assert semantic["mode"] == "semantic" and semantic["items"] and semantic["model"] == "test-embedding"
    assert keyword["items"] == []
    assert semantic["items"][0]["score"] > 0.9
    assert client.get("/api/v1/learning-state", headers=h).json() == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceEmbedding)) > 0
        calls = list(db.scalars(select(ModelCall)))
        assert calls and all(row.status == "succeeded" and row.external_calls == 1 for row in calls)
        assert all(len(row.input_hash) == 64 for row in calls)


def test_private_source_is_not_sent_until_authorized_and_revoke_removes_index_and_answer(
    client, login, models, app
):
    h = login()
    mid = source(client, h, "栈的独有私人讲义内容")
    assert index(client, h)["status"] == "succeeded"
    assert "独有私人" not in json.dumps(models[0], ensure_ascii=False)
    client.patch(f"/api/v1/materials/{mid}/external-consent", headers=h, json={"allowed": True})
    assert index(client, h)["status"] == "succeeded"
    assert "独有私人" in json.dumps(models[0], ensure_ascii=False)
    private = [hit for hit in sources(client, h) if hit["material_id"] == mid]
    job = explain(client, h, private)
    assert job["status"] == "succeeded", job
    client.patch(f"/api/v1/materials/{mid}/external-consent", headers=h, json={"allowed": False})
    erased = client.get("/api/v1/jobs/" + job["id"], headers=h).json()
    assert erased["status"] == "failed" and "answer" not in erased["result"]
    with app.state.sessions() as db:
        assert not db.scalar(select(SourceEmbedding.id).where(SourceEmbedding.material_id == mid))
    # Revoking external processing keeps locally authorized keyword reading available.
    assert any(hit["material_id"] == mid for hit in sources(client, h))
    assert client.delete(f"/api/v1/materials/{mid}", headers=h).status_code == 204
    assert not any(hit["material_id"] == mid for hit in sources(client, h))


def test_embedding_model_switch_never_uses_old_model_vectors(client, login, models, monkeypatch):
    h = login()
    assert index(client, h)["status"] == "succeeded"
    count = len(models[0])
    monkeypatch.setenv("ARISTOTLE_EMBEDDING_MODEL", "different-embedding-model")
    result = client.post(
        "/api/v1/retrieval/search",
        headers=h,
        json={"query": "栈", "knowledge_id": "stack", "mode": "hybrid", "allow_external_query": True},
    ).json()
    assert result["items"] == [] and result["missing_index"] > 0
    assert len(models[0]) == count


def test_invalid_vectors_are_rejected_and_accounted_without_partial_index(client, login, models, app):
    app.state.model_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'{"data":[{"index":0,"embedding":[NaN,0,1]}]}')
    )
    result = index(client, login())
    assert result["status"] == "failed" and result["result"]["error_code"] == "invalid_output", result
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceEmbedding)) == 0
        assert db.scalar(select(ModelCall)).status == "failed"


def test_unknown_citations_are_rejected_and_explanations_never_change_evidence(client, login, models, app):
    h = login()
    before = client.get("/api/v1/learning-state", headers=h).json()
    app.state.model_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "编造的引用",
                                    "citations": ["other-user-source"],
                                    "insufficient_evidence": False,
                                }
                            )
                        }
                    }
                ]
            },
        )
    )
    result = explain(client, h, sources(client, h))
    assert result["status"] == "failed" and result["result"]["error_code"] == "invalid_output", result
    assert "answer" not in result["result"]
    assert client.get("/api/v1/learning-state", headers=h).json() == before


def test_real_annotation_is_only_a_candidate_until_human_review(client, login, models, app):
    h, editor = login(), login("editor")
    body = {
        "question_id": "real_candidate",
        "version": 1,
        "knowledge_id": "linear",
        "prompt": "说明线性关系",
        "options": ["A", "B"],
        "answer": "A",
        "explanation": "需要理解关系",
        "source": "测试自编",
    }
    assert client.post("/api/v1/admin/questions", headers=editor, json=body).status_code == 201
    assert (
        client.post("/api/v1/admin/questions/real_candidate:v1/model-annotations", headers=h).status_code
        == 403
    )
    queued = client.post("/api/v1/admin/questions/real_candidate:v1/model-annotations", headers=editor)
    assert queued.status_code == 202, queued.text
    job = client.get("/api/v1/jobs/" + queued.json()["id"], headers=editor).json()
    assert job["status"] == "succeeded" and job["result"]["requires_review"], job
    with app.state.sessions() as db:
        assert db.get(Question, "real_candidate:v1").status == "pending_review"
        candidate_id = job["result"]["candidate_id"]
        assert db.get(Annotation, candidate_id).provider.startswith("openai-compatible:")
    task = client.post(
        "/api/v1/tasks", headers=h, json={"knowledge_id": "linear", "target_level": "understand"}
    ).json()
    assert "real_candidate:v1" not in task["question_keys"]
    approval = client.post(
        f"/api/v1/admin/candidates/{candidate_id}/review",
        headers=editor,
        json={
            "decision": "approve",
            "reason": "人工核验",
            "content_verified": True,
            "final_level": "understand",
        },
    )
    assert approval.status_code == 200, approval.text


def test_queue_claiming_is_idempotent_and_queued_jobs_use_frozen_model_configuration(
    client, login, models, app, monkeypatch
):
    monkeypatch.setenv("ARISTOTLE_INLINE_WORKER", "0")
    h = login()
    response = client.post(
        "/api/v1/retrieval/index", headers=h, json={"knowledge_id": "stack", "allow_external": True}
    )
    job_id = response.json()["id"]
    assert not models[0]
    result = run_job(app.state.sessions, job_id, app.state.model_transport)
    assert result["status"] == "succeeded", result
    count = len(models[0])
    assert run_job(app.state.sessions, job_id, app.state.model_transport) is None and len(models[0]) == count
    response = client.post(
        "/api/v1/retrieval/index", headers=h, json={"knowledge_id": "stack", "allow_external": True}
    )
    monkeypatch.setenv("ARISTOTLE_EMBEDDING_MODEL", "changed-after-queueing")
    result = run_job(app.state.sessions, response.json()["id"], app.state.model_transport)
    assert result["status"] == "failed"
    assert (
        client.get("/api/v1/jobs/" + response.json()["id"], headers=h).json()["result"]["error_code"]
        == "settings_changed"
    )
    assert len(models[0]) == count


def test_transient_retry_reserves_both_calls_and_does_not_replay_completed_jobs(
    client, login, models, app, monkeypatch
):
    monkeypatch.setenv("ARISTOTLE_MODEL_RETRIES", "1")
    calls = []

    def transient(request):
        calls.append(1)
        return httpx.Response(429) if len(calls) == 1 else models[1](request)

    app.state.model_transport = httpx.MockTransport(transient)
    result = index(client, login())
    assert result["status"] == "succeeded", result
    with app.state.sessions() as db:
        call = db.scalar(select(ModelCall))
        assert call.reserved_requests == 2 and call.external_calls == 2
    assert run_job(app.state.sessions, result["id"], app.state.model_transport) is None
    assert len(calls) == 2


def test_shared_model_quota_is_reserved_atomically(client, login, models, app, monkeypatch):
    monkeypatch.setenv("ARISTOTLE_MODEL_DAILY_LIMIT", "1")
    h = login()
    hits = sources(client, h)[:1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: explain(client, h, hits, query=f"解释后进先出 {i}"), range(2)))
    assert sorted(row["status"] for row in results) == ["failed", "succeeded"], results
    assert (
        next(row for row in results if row["status"] == "failed")["result"]["error_code"] == "quota_exceeded"
    )
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ModelCall)) == 1


def test_revoking_source_during_inference_never_restores_generated_private_text(client, login, models, app):
    h = login()
    mid = source(client, h)
    client.patch(f"/api/v1/materials/{mid}/external-consent", headers=h, json={"allowed": True})

    def revoke_while_processing(request):
        with app.state.sessions() as db:
            db.get(Material, mid).external_processing_allowed = False
            invalidate_material_index(db, mid)
            db.commit()
        return models[1](request)

    app.state.model_transport = httpx.MockTransport(revoke_while_processing)
    result = explain(client, h, [hit for hit in sources(client, h) if hit["material_id"] == mid])
    assert result["status"] == "failed" and "answer" not in result["result"], result


def test_other_users_cannot_read_or_dispatch_model_jobs(client, login, models, monkeypatch):
    monkeypatch.setenv("ARISTOTLE_INLINE_WORKER", "0")
    h, other = login(), login("student2")
    job = client.post(
        "/api/v1/retrieval/index", headers=h, json={"knowledge_id": "stack", "allow_external": True}
    ).json()
    assert client.get("/api/v1/jobs/" + job["id"], headers=other).status_code == 404
    assert client.post("/api/v1/model-jobs/" + job["id"] + "/dispatch", headers=other).status_code == 404
    assert client.post("/api/v1/jobs/" + job["id"] + "/run", headers=h).status_code == 409
    assert not models[0]


def test_model_status_is_redacted_and_does_not_trigger_generation(client, login, models, app):
    response = client.get("/api/v1/model-status", headers=login())
    assert response.status_code == 200 and response.json()["generation"]["configured"]
    assert "test-only-not-a-real-key" not in response.text and "model.test" not in response.text
    assert client.post("/api/v1/admin/providers/live", headers=login("admin")).status_code == 200
    assert not models[0]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ModelCall)) == 0


def test_identical_queued_requests_share_one_job_and_interrupted_calls_are_not_auto_retried(
    client, login, models, app, monkeypatch
):
    from aristotle_backend.model_jobs import expire_running

    monkeypatch.setenv("ARISTOTLE_INLINE_WORKER", "0")
    h = login()
    body = {"knowledge_id": "stack", "allow_external": True}
    a = client.post("/api/v1/retrieval/index", headers=h, json=body).json()
    b = client.post("/api/v1/retrieval/index", headers=h, json=body).json()
    assert a["id"] == b["id"] and not models[0]
    with app.state.sessions() as db:
        job = db.get(ServiceJob, a["id"])
        job.status = "running"
        job.result = {"started_at": 1, "run_id": "old"}
        db.commit()
    expire_running(app.state.sessions, now=10000)
    failed = client.get("/api/v1/jobs/" + a["id"], headers=h).json()
    assert failed["status"] == "failed" and failed["result"]["error_code"] == "interrupted"
    assert not failed["result"]["retryable"] and not models[0]
