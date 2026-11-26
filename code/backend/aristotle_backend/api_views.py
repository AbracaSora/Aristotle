from uuid import uuid4

from aristotle_core.policy import diagnose
from sqlalchemy import select

from .api_access import fail
from .curriculum import (
    preset_task_view,
)
from .db import (
    Attempt,
    Audit,
    Graph,
    Material,
    Question,
    SystemSetting,
    TaskQuestion,
)
from .flow_support import chunks_view
from .learning_context import LearningRun
from .workflow import (
    flow_view,
    round_evidence,
    scoped_nodes,
)


def active_graph(db):
    graph = db.scalar(select(Graph).order_by(Graph.sequence.desc()).limit(1))
    if not graph:
        fail(503, "尚未发布知识结构，请先初始化演示数据或由维护者发布")
    return graph


def owned(db, model, key, user):
    row = db.get(model, key)
    if row is None or row.user_id != user.id:
        fail(404, "资源不存在")
    return row


def audit_record(user, action, target, now):
    return Audit(id=str(uuid4()), actor_id=user.id, action=action, target=target, at=now)


def history_rows(db, user_id):
    rows = db.execute(
        select(Attempt, Question)
        .join(Question, Attempt.question_key == Question.key)
        .where(Attempt.user_id == user_id, Question.status == "published")
    ).all()
    return [
        {
            "id": a.id,
            "question_id": q.question_id,
            "knowledge_id": q.knowledge_id,
            "level": q.level,
            "correct": a.correct,
            "at": a.created_at,
        }
        for a, q in rows
    ]


def learning_state(db, user, now):
    graph = active_graph(db)
    attempts = round_evidence(db, user, history_rows(db, user.id))
    return graph, attempts, diagnose(scoped_nodes(db, user, graph.nodes), attempts, now)


def question_view(q):
    # Explicit allowlist: answer/explanation must never leak before submission.
    return {
        "key": q.key,
        "question_id": q.question_id,
        "version": q.version,
        "knowledge_id": q.knowledge_id,
        "prompt": q.prompt,
        "options": q.options,
        "level": q.level,
        "status": q.status,
        "dataset": q.dataset,
    }


def attempt_view(a, q, db=None):
    retirement = db.get(SystemSetting, "retired:" + q.key) if db else None
    return {
        "id": a.id,
        "task_id": a.task_id,
        "question_key": a.question_key,
        "submission_id": a.submission_id,
        "selected": a.selected,
        "correct": a.correct,
        "created_at": a.created_at,
        "answer": q.answer,
        "explanation": q.explanation,
        "level": q.level,
        "question_version": q.version,
        "content_status": q.status,
        "retirement_reason": retirement.data["reason"] if retirement else None,
    }


def material_view(m, db=None):
    return {
        "id": m.id,
        "title": m.title,
        "text": m.text,
        "knowledge_id": m.knowledge_id,
        "confirmed": m.confirmed,
        "external_processing_allowed": m.external_processing_allowed,
        "source_location": "粘贴文本第 1 段",
        "chunks": chunks_view(db, m) if db else [],
    }


def task_view(db, task):
    if "preset_set_id" in task.decision:
        return preset_task_view(db, task)
    questions = db.scalars(
        select(Question)
        .join(TaskQuestion, TaskQuestion.question_key == Question.key)
        .where(TaskQuestion.task_id == task.id)
        .order_by(TaskQuestion.position)
    ).all()
    attempts = db.scalars(
        select(Attempt).where(Attempt.task_id == task.id).order_by(Attempt.created_at)
    ).all()
    by_key = {q.key: q for q in questions}
    materials = task_materials(db, task)
    return {
        "id": task.id,
        "mode": task.mode,
        "graph_version": task.graph_version,
        "created_at": task.created_at,
        **task.decision,
        "questions": [question_view(q) for q in questions],
        "materials": materials,
        "attempts": [attempt_view(a, by_key[a.question_key], db) for a in attempts],
        "evidence_snapshot": task.evidence_snapshot,
        "notice": "课程后端原型；demo-seed 为模拟审核的演示题，非正式审核题库。",
        **flow_view(db, task),
    }


def task_materials(db, task):
    keys = task.decision.get("material_ids", [])
    eligible = db.scalars(
        select(Material).where(
            Material.id.in_(keys),
            Material.user_id == task.user_id,
            Material.deleted.is_(False),
            Material.confirmed.is_(True),
            Material.knowledge_id == task.decision["knowledge_id"],
        )
    )
    by_id = {m.id: material_view(m) for m in eligible}
    materials = [
        by_id.get(key, {"id": key, "unavailable": True, "reason": "来源已删除或关联已取消/变更"})
        for key in keys
    ]
    return materials


def learning_run(db, user, now):
    return LearningRun(db, user, now, *learning_state(db, user, now))
