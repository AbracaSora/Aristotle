import json
from uuid import uuid4

import pytest
from aristotle_backend.config import PROJECT_ROOT
from aristotle_backend.db import Attempt, Graph, LearningScope, Question
from aristotle_backend.design_seed import seed_design_flow
from aristotle_backend.resource_seed import import_resource_demo
from sqlalchemy import func, select


def test_resource_demo_replaces_learning_data_and_preserves_history(app, client, login):
    seed_design_flow(app.state.sessions)
    headers = login()
    assert (
        client.patch("/api/v1/learning-scope", headers=headers, json={"scope_id": "foundations"}).status_code
        == 200
    )
    diagnostic = client.post("/api/v1/diagnostics", headers=headers, json={}).json()
    task_id = diagnostic["segments"][0]["task_id"]
    client.post(f"/api/v1/tasks/{task_id}/actions", headers=headers, json={"action": "accept"})
    task = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
    question = task["questions"][0]
    with app.state.sessions() as db:
        answer = db.get(Question, question["key"]).answer
    assert (
        client.post(
            f"/api/v1/tasks/{task_id}/attempts",
            headers=headers,
            json={
                "question_key": question["key"],
                "selected": answer,
                "submission_id": str(uuid4()),
            },
        ).status_code
        == 200
    )

    first = import_resource_demo(app.state.sessions)
    second = import_resource_demo(app.state.sessions)
    assert first == {
        "knowledge_points": 203,
        "questions": 650,
        "inserted_questions": 650,
        "scopes": 24,
        "graph_version": first["graph_version"],
    }
    assert second["inserted_questions"] == 0

    with app.state.sessions() as db:
        active = db.scalar(select(Graph).order_by(Graph.sequence.desc()).limit(1))
        assert active.version == first["graph_version"] and len(active.nodes) == 203
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(Question).where(Question.source.like("resource 本地演示题%"))
            )
            == 650
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(LearningScope)
                .where(LearningScope.id.like("resource-%"), LearningScope.published.is_(True))
            )
            == 24
        )
        assert not db.get(LearningScope, "foundations").published

    context = client.get("/api/v1/learning-context", headers=headers).json()
    assert context["selected_scope"]["id"] == "resource-DS-1"
    knowledge = client.get("/api/v1/knowledge", headers=headers).json()
    assert knowledge["nodes"] and all(node["id"].startswith("DS-") for node in knowledge["nodes"])
    assert client.get("/api/v1/history", headers=headers).json()["total"] == 1
    next_diagnostic = client.post("/api/v1/diagnostics", headers=headers, json={})
    assert next_diagnostic.status_code == 201, next_diagnostic.text
    first_segment = next_diagnostic.json()["segments"][0]
    next_task = client.get(f"/api/v1/tasks/{first_segment['task_id']}", headers=headers).json()
    assert next_task["questions"][0]["question_id"].startswith("KEW-DS-")


def test_resource_import_rolls_back_earlier_points_when_a_later_point_has_no_questions(app, tmp_path):
    original = PROJECT_ROOT / "resource" / "data-structures"
    points = [json.loads(line) for line in (original / "knowledge_points.jsonl").read_text().splitlines()[:2]]
    first_question = json.loads((original / "questions.jsonl").read_text().splitlines()[0])
    assert first_question["knowledge_point_id"] == points[0]["id"]
    manifest = {
        "exports": {"graph": "graph.json"},
        "subjects": [{"directory": ".", "subject": "数据结构", "knowledge_points": 2, "questions": 1}],
        "total_knowledge_points": 2,
        "total_questions": 1,
    }
    graph = {"nodes": [{"id": point["id"], "prerequisites": []} for point in points]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "knowledge_points.jsonl").write_text("\n".join(map(json.dumps, points)))
    (tmp_path / "questions.jsonl").write_text(json.dumps(first_question))
    with pytest.raises(ValueError, match="知识点没有题目"):
        import_resource_demo(app.state.sessions, tmp_path)
    with app.state.sessions() as db:
        assert db.scalar(select(Graph).where(Graph.version.like("resource-demo-%"))) is None
        assert db.scalar(select(Question).where(Question.question_id == first_question["id"])) is None
