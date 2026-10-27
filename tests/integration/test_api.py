from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from aristotle_backend.app import create_app
from aristotle_backend.db import Attempt, Material
from aristotle_backend.seed import BANK
from fastapi.testclient import TestClient
from sqlalchemy import select

ANSWERS = {row[0] + ":v1": row[5] for row in BANK}


def new_task(client, headers, **body):
    response = client.post("/api/v1/tasks", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def answer_task(client, headers, task):
    for q in task["questions"]:
        response = client.post(
            f"/api/v1/tasks/{task['id']}/attempts",
            headers=headers,
            json={"question_key": q["key"], "selected": ANSWERS[q["key"]], "submission_id": str(uuid4())},
        )
        assert response.status_code == 200, response.text


def draft_body(qid="new"):
    return {
        "question_id": qid,
        "version": 1,
        "knowledge_id": "linear",
        "prompt": "自编测试题",
        "options": ["A", "B"],
        "answer": "B",
        "explanation": "测试用解析",
        "source": "测试自编",
    }


def candidate(qid="new", **overrides):
    return {
        "question_id": qid,
        "question_version": 1,
        "primary_level": "understand",
        "secondary_levels": [],
        "rationale": "本题需要解释关系",
        "confidence": 0.9,
        **overrides,
    }


def publish(client, headers, qid="new", level="understand"):
    response = client.post(
        f"/api/v1/admin/questions/{qid}:v1/candidates", headers=headers, json=candidate(qid)
    )
    assert response.status_code == 201, response.text
    response = client.post(
        f"/api/v1/admin/candidates/{response.json()['id']}/review",
        headers=headers,
        json={"decision": "approve", "reason": "测试审核", "content_verified": True, "final_level": level},
    )
    assert response.status_code == 200, response.text


def test_authentication_authorization_and_logout(client, login):
    assert client.get("/api/v1/knowledge").status_code == 401
    wrong = client.post("/api/v1/auth/login", json={"username": "student1", "password": "incorrect"})
    assert wrong.status_code == 401
    student = login()
    assert client.get("/api/v1/admin/questions", headers=student).status_code == 403
    assert client.get("/api/v1/learning-state", headers=login("editor")).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=student).status_code == 204
    assert client.get("/api/v1/auth/me", headers=student).status_code == 401


def test_expired_session(client, login, app):
    headers = login()
    app.state.clock = lambda: 9_000_000_000
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_full_learning_flow_and_restart_persistence(client, login, app):
    headers = login()
    targets = []
    for i in range(4):
        task = new_task(client, headers, mode="diagnostic" if i == 0 else "practice")
        targets.append((task["knowledge_id"], task["target_level"]))
        for q in task["questions"]:
            assert "answer" not in q and "explanation" not in q
        answer_task(client, headers, task)
    assert targets == [
        ("linear", "remember"),
        ("stack", "understand"),
        ("stack_ops", "apply"),
        ("stack_ops", "analyze"),
    ]
    assert len(client.get("/api/v1/history", headers=headers).json()["items"]) == 12
    states = client.get("/api/v1/learning-state", headers=headers).json()
    assert all(s["status"] == "provisional" for s in states["states"])
    restarted = create_app(str(app.state.engine.url))
    with TestClient(restarted) as second:
        assert len(second.get("/api/v1/history", headers=headers).json()["items"]) == 12
        assert second.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()["attempts"]


def test_tasks_and_materials_are_private_even_with_known_ids(client, login):
    first, other = login(), login("student2")
    task = new_task(client, first)
    assert client.get(f"/api/v1/tasks/{task['id']}", headers=other).status_code == 404
    assert (
        client.post(
            f"/api/v1/tasks/{task['id']}/attempts",
            headers=other,
            json={"question_key": "l1:v1", "selected": ANSWERS["l1:v1"], "submission_id": "private-attempt"},
        ).status_code
        == 404
    )
    material = client.post(
        "/api/v1/materials",
        headers=first,
        json={"title": "私人资料", "text": "只属于学生一", "knowledge_id": "linear"},
    ).json()
    path = f"/api/v1/materials/{material['id']}"
    assert (
        client.patch(path, headers=other, json={"knowledge_id": "linear", "confirmed": True}).status_code
        == 404
    )
    assert client.delete(path, headers=other).status_code == 404
    assert client.get("/api/v1/materials", headers=other).json()["items"] == []


def test_concurrent_retries_only_save_one_attempt_and_conflicting_reuse_is_rejected(client, login, app):
    headers = login()
    task = new_task(client, headers)
    path = f"/api/v1/tasks/{task['id']}/attempts"
    body = {"question_key": "l1:v1", "selected": ANSWERS["l1:v1"], "submission_id": "same-submission"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post(path, headers=headers, json=body), range(12)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert client.post(path, headers=headers, json={**body, "selected": "一对多"}).status_code == 409
    assert (
        client.post(
            path, headers=headers, json={**body, "question_key": "l2:v1", "selected": "0"}
        ).status_code
        == 409
    )
    assert client.post(path, headers=headers, json={**body, "submission_id": "another-request"}).json()[
        "replayed"
    ]
    with app.state.sessions() as db:
        assert len(db.scalars(select(Attempt)).all()) == 1


def test_repeated_practice_keeps_history_without_inflating_evidence(client, login):
    headers = login()
    for _ in range(2):
        answer_task(client, headers, new_task(client, headers, knowledge_id="linear"))
    assert len(client.get("/api/v1/history", headers=headers).json()["items"]) == 6
    assert client.get("/api/v1/learning-state", headers=headers).json()["states"][0]["evidence_count"] == 3


def test_history_totals_are_per_user_and_independent_of_pagination(client, login):
    headers = login()
    for _ in range(2):
        answer_task(client, headers, new_task(client, headers, knowledge_id="linear"))
    page = client.get("/api/v1/history?limit=1&offset=1", headers=headers).json()
    assert len(page["items"]) == 1
    assert page["total"] == 6 and page["correct_total"] == 6
    other = client.get("/api/v1/history", headers=login("student2")).json()
    assert other["total"] == 0 and other["correct_total"] == 0


def test_pending_review_cannot_be_assigned_and_published_content_is_immutable(client, login):
    editor, student = login("editor"), login()
    assert client.post("/api/v1/admin/questions", headers=editor, json=draft_body()).status_code == 201
    task = new_task(client, student, target_level="understand")
    assert task["status"] == "content_unavailable"
    response = client.post("/api/v1/admin/questions/new:v1/candidates", headers=editor, json=candidate())
    annotation_id = response.json()["id"]
    assert response.json()["provider"] == "manual-prototype"
    assert new_task(client, student, target_level="understand")["questions"] == []
    path = f"/api/v1/admin/candidates/{annotation_id}/review"
    review = {"decision": "approve", "reason": "确认题目内容及标签", "final_level": "understand"}
    assert client.post(path, headers=editor, json=review).status_code == 422
    assert client.post(path, headers=editor, json={**review, "content_verified": True}).status_code == 200
    task = new_task(client, student, target_level="understand")
    assert [q["key"] for q in task["questions"]] == ["new:v1"]
    assert task["warnings"]
    assert client.post(path, headers=editor, json={**review, "content_verified": True}).status_code == 409
    assert (
        client.post("/api/v1/admin/questions/new:v1/candidates", headers=editor, json=candidate()).status_code
        == 409
    )
    assert client.post("/api/v1/admin/questions", headers=editor, json=draft_body()).status_code == 409


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"question_version": 2}, 409),
        ({"primary_level": "invented"}, 422),
        ({"confidence": 1.1}, 422),
        ({"rationale": "   "}, 422),
        ({"secondary_levels": ["understand"]}, 422),
        ({"review_status": "approved"}, 422),
    ],
)
def test_invalid_or_stale_annotation_is_rejected(client, login, overrides, expected):
    headers = login("editor")
    client.post("/api/v1/admin/questions", headers=headers, json=draft_body())
    result = client.post(
        "/api/v1/admin/questions/new:v1/candidates", headers=headers, json=candidate(**overrides)
    )
    assert result.status_code == expected


def test_retirement_excludes_future_tasks_and_invalidates_evidence_but_keeps_history(client, login):
    headers, editor = login(), login("editor")
    answer_task(client, headers, new_task(client, headers))
    assert client.post("/api/v1/admin/questions/l1:v1/retire", headers=editor).status_code == 200
    state = client.get("/api/v1/learning-state", headers=headers).json()["states"][0]
    assert state["evidence_count"] == 2 and state["status"] == "insufficient"
    task = new_task(client, headers)
    assert "l1:v1" not in task["question_keys"]
    assert len(client.get("/api/v1/history", headers=headers).json()["items"]) == 3
    pending = next(q for q in task["questions"] if q["key"] == "l2:v1")
    client.post("/api/v1/admin/questions/l2:v1/retire", headers=editor)
    response = client.post(
        f"/api/v1/tasks/{task['id']}/attempts",
        headers=headers,
        json={"question_key": pending["key"], "selected": "0", "submission_id": str(uuid4())},
    )
    assert response.status_code == 409


def test_material_confirmation_and_delete_remove_text_from_historical_task(client, login, app):
    headers = login()
    material = client.post(
        "/api/v1/materials",
        headers=headers,
        json={"title": "笔记", "text": "私人原文测试", "knowledge_id": "linear"},
    ).json()
    assert new_task(client, headers, target_level="analyze")["status"] == "content_unavailable"
    path = f"/api/v1/materials/{material['id']}"
    client.patch(path, headers=headers, json={"knowledge_id": "linear", "confirmed": True})
    task = new_task(client, headers, target_level="analyze")
    assert task["status"] == "material_review"
    assert task["materials"][0]["text"] == "私人原文测试"
    assert client.delete(path, headers=headers).status_code == 204
    historical = client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()
    assert historical["materials"][0]["unavailable"]
    assert "私人原文测试" not in str(historical)
    assert client.get("/api/v1/materials", headers=headers).json()["items"] == []
    with app.state.sessions() as db:
        assert db.get(Material, material["id"]).text == ""


def test_invalid_graph_publish_does_not_replace_active_graph(client, login):
    headers = login("editor")
    invalid = {"version": "bad", "nodes": [{"id": "a", "name": "A", "prerequisites": ["a"]}]}
    assert client.post("/api/v1/admin/graphs", headers=headers, json=invalid).status_code == 422
    assert client.get("/api/v1/knowledge", headers=headers).json()["version"] == "ds-demo-v1"
    missing_references = {"version": "missing", "nodes": [{"id": "a", "name": "A", "prerequisites": []}]}
    assert client.post("/api/v1/admin/graphs", headers=headers, json=missing_references).status_code == 409


def test_new_question_revision_requires_new_review_and_keeps_old_attempt_version(client, login):
    headers, editor = login(), login("editor")
    answer_task(client, headers, new_task(client, headers))
    revision = {**draft_body("l1"), "version": 2}
    assert client.post("/api/v1/admin/questions", headers=editor, json=revision).status_code == 201
    assert "l1:v1" in new_task(client, headers, knowledge_id="linear")["question_keys"]
    response = client.post(
        "/api/v1/admin/questions/l1:v2/candidates", headers=editor, json=candidate("l1", question_version=2)
    )
    assert response.status_code == 201
    client.post(
        f"/api/v1/admin/candidates/{response.json()['id']}/review",
        headers=editor,
        json={
            "decision": "approve",
            "reason": "新版本审核",
            "content_verified": True,
            "final_level": "remember",
        },
    )
    task = new_task(client, headers, knowledge_id="linear")
    assert "l1:v2" in task["question_keys"] and "l1:v1" not in task["question_keys"]
    history = client.get("/api/v1/history", headers=headers).json()["items"]
    assert next(a for a in history if a["question_key"] == "l1:v1")["question_version"] == 1


def test_private_input_not_echoed_in_validation_errors(client, login):
    result = client.post(
        "/api/v1/materials",
        headers=login(),
        json={"title": "a", "text": "private-content", "knowledge_id": "linear", "secret": "private-secret"},
    )
    assert result.status_code == 422
    assert "private-secret" not in result.text and "private-content" not in result.text


def test_only_submitted_task_questions_reveal_answers(client, login):
    headers = login()
    task = new_task(client, headers)
    response = client.post(
        f"/api/v1/tasks/{task['id']}/attempts",
        headers=headers,
        json={"question_key": "l1:v1", "selected": "一对多", "submission_id": str(uuid4())},
    )
    assert response.json()["correct"] is False
    assert response.json()["answer"] == "一对一"
    view = client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()
    assert all("answer" not in q and "explanation" not in q for q in view["questions"])
    assert len(view["attempts"]) == 1


def test_unsupported_first_release_labels_are_not_assigned(client, login):
    headers, editor = login(), login("editor")
    client.post("/api/v1/admin/questions", headers=editor, json=draft_body())
    publish(client, editor, level="evaluate")
    assert all(q["level"] != "evaluate" for q in new_task(client, headers)["questions"])


def test_openapi_and_demo_are_available(client):
    assert client.get("/health").json()["external_model"] == "not_configured"
    assert "/api/v1/tasks" in client.get("/openapi.json").json()["paths"]
    assert client.get("/demo").status_code == 200


def test_concurrent_candidate_approvals_have_only_one_effective_review(client, login):
    headers = login("editor")
    client.post("/api/v1/admin/questions", headers=headers, json=draft_body())
    candidate_ids = [
        client.post("/api/v1/admin/questions/new:v1/candidates", headers=headers, json=candidate()).json()[
            "id"
        ]
        for _ in range(2)
    ]

    def approve(key):
        return client.post(
            f"/api/v1/admin/candidates/{key}/review",
            headers=headers,
            json={
                "decision": "approve",
                "reason": "并发审核",
                "content_verified": True,
                "final_level": "understand",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, candidate_ids))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    rows = client.get("/api/v1/admin/candidates", headers=headers).json()["items"]
    assert sum(a["decision"] == "approve" for a in rows if a["question_key"] == "new:v1") == 1
