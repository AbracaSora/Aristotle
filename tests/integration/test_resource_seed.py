from uuid import uuid4

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
