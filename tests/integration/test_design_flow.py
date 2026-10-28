from uuid import uuid4

import pytest
from aristotle_backend.db import Material, Question, ServiceJob, SourceChunk
from aristotle_backend.design_seed import seed_design_flow
from sqlalchemy import select


@pytest.fixture
def design(app):
    seed_design_flow(app.state.sessions)
    return app


def choose(client, h, scope="stack"):
    r = client.patch("/api/v1/learning-scope", headers=h, json={"scope_id": scope})
    assert r.status_code == 200, r.text


def action(client, h, task_id, kind):
    r = client.post(f"/api/v1/tasks/{task_id}/actions", headers=h, json={"action": kind})
    assert r.status_code == 200, r.text
    return r.json()


def diagnose_all(client, h, app, weak_apply=False, body=None):
    r = client.post("/api/v1/diagnostics", headers=h, json=body or {})
    assert r.status_code == 201, r.text
    diagnostic = r.json()
    for segment in diagnostic["segments"]:
        task_id = segment["task_id"]
        task = action(client, h, task_id, "accept")["task"]
        for q in task["questions"]:
            with app.state.sessions() as db:
                row = db.get(Question, q["key"])
                answer = (
                    next(o for o in row.options if o != row.answer)
                    if weak_apply and q["level"] == "apply"
                    else row.answer
                )
            r = client.post(
                f"/api/v1/tasks/{task_id}/attempts",
                headers=h,
                json={"question_key": q["key"], "selected": answer, "submission_id": str(uuid4())},
            )
            assert r.status_code == 200, r.text
        action(client, h, task_id, "complete")
    return client.get(f"/api/v1/diagnostics/{diagnostic['id']}", headers=h).json()


def test_original_ac04_two_learners_get_different_plans_and_review_retest_does_not_fake_mastery(
    client, login, design
):
    first, second = login(), login("student2")
    for h in (first, second):
        choose(client, h)
    assert diagnose_all(client, first, design, weak_apply=True)["status"] == "completed"
    assert diagnose_all(client, second, design)["status"] == "completed"
    a = client.post("/api/v1/recommendations", headers=first, json={}).json()
    b = client.post("/api/v1/recommendations", headers=second, json={}).json()
    assert a["activity"] == "material_review" and a["resources"]
    assert b["activity"] == "practice"
    assert "两道不同" in a["reason"]
    before = client.get("/api/v1/learning-state", headers=first).json()["states"]
    action(client, first, a["id"], "accept")
    completed = action(client, first, a["id"], "complete")["task"]
    assert completed["feedback"]["next_action"] == "retest"
    assert client.get("/api/v1/learning-state", headers=first).json()["states"] == before
    diagnose_all(client, first, design, body={"knowledge_id": "stack", "target_level": "apply"})
    after = client.get("/api/v1/learning-state", headers=first).json()["states"]
    stack = next(s for s in after if s["knowledge_id"] == "stack")
    assert stack["status"] == "provisional"
    assert len(client.get("/api/v1/history", headers=first).json()["items"]) == 12


def test_scope_is_explicit_unsupported_does_not_reset_history_and_cross_scope_tasks_cannot_mutate(
    client, login, design
):
    h = login()
    assert client.post("/api/v1/recommendations", headers=h, json={}).status_code == 409
    choose(client, h, "foundations")
    diagnostic = client.post("/api/v1/diagnostics", headers=h, json={}).json()
    segment = diagnostic["segments"][0]
    assert (
        client.post(
            f"/api/v1/tasks/{segment['task_id']}/attempts",
            headers=h,
            json={"question_key": "l1:v1", "selected": "一对一", "submission_id": str(uuid4())},
        ).status_code
        == 409
    )
    choose(client, h, "stack")
    assert (
        client.post(
            f"/api/v1/tasks/{segment['task_id']}/actions", headers=h, json={"action": "accept"}
        ).status_code
        == 409
    )
    assert (
        client.patch("/api/v1/learning-scope", headers=h, json={"scope_id": "os-planned"}).status_code == 409
    )
    assert client.get("/api/v1/learning-context", headers=h).json()["selected_scope"]["id"] == "stack"


def test_task_accept_skip_replace_and_premature_complete_are_real_states(client, login, design):
    h = login()
    choose(client, h, "foundations")
    diagnose_all(client, h, design)
    task = client.post("/api/v1/recommendations", headers=h, json={}).json()
    assert task["lifecycle"] == "recommended"
    assert (
        client.post(f"/api/v1/tasks/{task['id']}/actions", headers=h, json={"action": "complete"}).status_code
        == 409
    )
    result = action(client, h, task["id"], "replace")
    assert result["task"]["lifecycle"] == "superseded"
    assert result["replacement"]["status"] == "material_review"
    assert not result["replacement"]["questions"]
    skipped = action(client, h, result["replacement"]["id"], "skip")
    assert skipped["task"]["lifecycle"] == "skipped"
    assert client.get("/api/v1/learning-timeline", headers=h).json()["items"]


def test_mock_pdf_requires_confirmation_and_deleted_private_chunks_and_jobs_are_purged(client, login, design):
    h = login()
    other = login("student2")
    choose(client, h)
    r = client.post(
        "/api/v1/material-imports",
        headers=h,
        json={"source_type": "text", "title": "私有资料", "text": "栈的私有段落\n\n第二段私人内容"},
    )
    job = r.json()
    assert job["status"] == "queued"
    assert client.get("/api/v1/jobs/" + job["id"], headers=other).status_code == 404
    result = client.post("/api/v1/jobs/" + job["id"] + "/run", headers=h).json()
    mid = result["result"]["material_id"]
    material = client.get("/api/v1/materials", headers=h).json()["items"][0]
    assert len(material["chunks"]) == 2 and all(c["status"] == "pending" for c in material["chunks"])
    chunk = material["chunks"][0]
    path = f"/api/v1/materials/{mid}/chunks/{chunk['id']}"
    assert (
        client.patch(path, headers=other, json={"knowledge_id": "stack", "status": "confirmed"}).status_code
        == 404
    )
    assert (
        client.patch(path, headers=h, json={"knowledge_id": "stack", "status": "confirmed"}).status_code
        == 200
    )
    assert client.delete("/api/v1/materials/" + mid, headers=h).status_code == 204
    with design.state.sessions() as db:
        assert db.get(Material, mid).text == ""
        assert all(
            c.text == "" for c in db.scalars(select(SourceChunk).where(SourceChunk.material_id == mid))
        )
        stored = db.get(ServiceJob, job["id"])
        assert "私有" not in str(stored.params) and "私人" not in str(stored.result)
    assert client.post("/api/v1/material-imports/pdf", headers=h).status_code == 501


@pytest.mark.parametrize("scenario", ["scanned", "encrypted", "oversize", "timeout"])
def test_import_failures_do_not_publish_material(client, login, design, scenario):
    h = login()
    choose(client, h)
    job = client.post(
        "/api/v1/material-imports",
        headers=h,
        json={"source_type": "pdf_mock", "title": "样例", "scenario": scenario},
    ).json()
    result = client.post("/api/v1/jobs/" + job["id"] + "/run", headers=h).json()
    assert result["status"] == "failed" and result["implementation"] == "mock"
    assert not client.get("/api/v1/materials", headers=h).json()["items"]


def test_mock_annotation_config_roles_failure_and_review_gate(client, login, design):
    editor, admin, h = login("editor"), login("admin"), login()
    assert client.get("/api/v1/admin/provider-settings", headers=editor).status_code == 403
    assert client.get("/api/v1/admin/provider-settings", headers=admin).status_code == 200
    draft = {
        "question_id": "flow_new",
        "version": 1,
        "knowledge_id": "linear",
        "prompt": "测试",
        "options": ["A", "B"],
        "answer": "B",
        "explanation": "样例",
        "source": "自编",
    }
    assert client.post("/api/v1/admin/questions", headers=editor, json=draft).status_code == 201
    job = client.post(
        "/api/v1/admin/questions/flow_new:v1/annotation-jobs",
        headers=editor,
        json={"scenario": "invalid_output", "suggested_level": "understand"},
    ).json()
    failed = client.post("/api/v1/jobs/" + job["id"] + "/run", headers=editor).json()
    assert failed["status"] == "failed" and failed["result"]["real_external_calls"] == 0
    assert client.post("/api/v1/jobs/" + job["id"] + "/retry", headers=editor).status_code == 409
    job = client.post("/api/v1/admin/questions/flow_new:v1/annotation-jobs", headers=editor, json={}).json()
    result = client.post("/api/v1/jobs/" + job["id"] + "/run", headers=editor).json()
    assert result["result"]["requires_review"]
    replay = client.post("/api/v1/jobs/" + job["id"] + "/run", headers=editor).json()
    assert result["result"]["candidate_id"] == replay["result"]["candidate_id"]
    candidates = client.get("/api/v1/admin/candidates", headers=editor).json()["items"]
    assert next(c for c in candidates if c["id"] == result["result"]["candidate_id"])["needs_attention"]
    assert client.get("/api/v1/admin/jobs", headers=h).status_code == 403
    assert client.post("/api/v1/admin/providers/live", headers=admin).status_code == 501


def test_report_retirement_reason_and_role_changes_are_audited(client, login, design):
    h, editor, admin = login(), login("editor"), login("admin")
    choose(client, h, "foundations")
    diagnose_all(client, h, design)
    r = client.post(
        "/api/v1/content-reports",
        headers=h,
        json={"question_key": "l1:v1", "category": "label", "message": "请复核标签"},
    )
    assert r.status_code == 201
    result = client.post(
        "/api/v1/admin/content-reports/" + r.json()["id"] + "/resolve",
        headers=editor,
        json={"action": "retire", "reason": "样例：暂存争议，等待内容复核"},
    )
    assert result.status_code == 200
    history = client.get("/api/v1/history", headers=h).json()["items"]
    assert next(a for a in history if a["question_key"] == "l1:v1")["retirement_reason"]
    assert client.get("/api/v1/admin/content-reports", headers=h).status_code == 403
    assert (
        client.patch(
            "/api/v1/admin/users/student2/role", headers=admin, json={"role": "maintainer"}
        ).status_code
        == 200
    )
    assert any(
        a["action"] == "role_changed"
        for a in client.get("/api/v1/admin/audit", headers=editor).json()["items"]
    )


def test_import_jobs_survive_refresh_and_only_owner_can_list_them(client, login, design):
    h, other = login(), login("student2")
    choose(client, h)
    job = client.post(
        "/api/v1/material-imports", headers=h, json={"source_type": "text", "title": "可恢复", "text": "段落"}
    ).json()
    assert client.get("/api/v1/jobs", headers=h).json()["items"][0]["id"] == job["id"]
    assert client.get("/api/v1/jobs", headers=other).json()["items"] == []
    assert client.get("/api/v1/admin/jobs", headers=login("editor")).json()["items"] == []


def test_retired_question_in_unfinished_diagnostic_can_rebuild_without_losing_history(client, login, design):
    h, editor = login(), login("editor")
    choose(client, h, "foundations")
    diagnostic = client.post("/api/v1/diagnostics", headers=h, json={}).json()
    task_id = diagnostic["segments"][0]["task_id"]
    action(client, h, task_id, "accept")
    assert (
        client.post(
            f"/api/v1/tasks/{task_id}/attempts",
            headers=h,
            json={"question_key": "l1:v1", "selected": "一对一", "submission_id": str(uuid4())},
        ).status_code
        == 200
    )
    client.post("/api/v1/admin/questions/l2:v1/retire", headers=editor)
    rebuilt = client.post(f"/api/v1/diagnostics/{diagnostic['id']}/restart", headers=h)
    assert rebuilt.status_code == 201, rebuilt.text
    task = client.get("/api/v1/tasks/" + rebuilt.json()["segments"][0]["task_id"], headers=h).json()
    assert "l2:v1" not in task["question_keys"] and task["warnings"]
    assert client.get(f"/api/v1/tasks/{task_id}", headers=h).json()["lifecycle"] == "superseded"
    assert client.get("/api/v1/history", headers=h).json()["total"] == 1


def test_mock_annotation_quota_reservation_is_atomic_and_retries_count(client, login, design):
    from concurrent.futures import ThreadPoolExecutor

    editor, admin = login("editor"), login("admin")
    assert (
        client.patch(
            "/api/v1/admin/provider-settings", headers=admin, json={"daily_annotation_limit": 1, "retries": 0}
        ).status_code
        == 200
    )
    draft = {
        "question_id": "quota_test",
        "version": 1,
        "knowledge_id": "linear",
        "prompt": "测试",
        "options": ["A", "B"],
        "answer": "A",
        "explanation": "样例",
        "source": "自编",
    }
    client.post("/api/v1/admin/questions", headers=editor, json=draft)

    def reserve(_):
        return client.post(
            "/api/v1/admin/questions/quota_test:v1/annotation-jobs",
            headers=editor,
            json={"scenario": "timeout"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(reserve, range(2)))
    assert sorted(statuses) == [202, 429]
    job = client.get("/api/v1/admin/jobs", headers=editor).json()["items"][0]
    client.post("/api/v1/jobs/" + job["id"] + "/run", headers=editor)
    assert client.post("/api/v1/jobs/" + job["id"] + "/retry", headers=editor).status_code == 429
    assert client.get("/api/v1/admin/audit", headers=admin).status_code == 200


def test_unauthorized_role_action_is_audited_without_request_body(client, login, design):
    secret = "private body should not be copied"
    result = client.post("/api/v1/admin/questions", headers=login(), json={"text": secret})
    assert result.status_code == 403
    events = client.get("/api/v1/admin/audit", headers=login("admin")).json()["items"]
    denied = next(e for e in events if e["action"] == "access_denied")
    assert denied["actor_id"] == "student1" and secret not in str(denied)


def test_understanding_supported_but_application_evidence_insufficient_recommends_application(
    client, login, design
):
    h = login()
    choose(client, h)
    with design.state.sessions() as db:
        hidden = list(
            db.scalars(
                select(Question).where(
                    Question.knowledge_id == "stack",
                    Question.level == "apply",
                    Question.key != "wf_stack_a1:v1",
                )
            )
        )
        keys = [q.key for q in hidden]
        for q in hidden:
            q.status = "retired"
        db.commit()
    diagnose_all(client, h, design, weak_apply=True)
    with design.state.sessions() as db:
        for key in keys:
            db.get(Question, key).status = "published"
        db.commit()
    result = client.post("/api/v1/recommendations", headers=h, json={}).json()
    assert result["knowledge_id"] == "stack"
    assert result["target_level"] == "apply" and result["activity"] == "practice"
    assert "理解题已有多题支持" in result["reason"]
    assert len(result["questions"]) == 3
