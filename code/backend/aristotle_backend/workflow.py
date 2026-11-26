"""Persistent learning workflow. Mock providers never write learning evidence."""

from typing import Any
from uuid import uuid4

from aristotle_core.policy import LEVELS, RecommendationEvidence, recommend
from fastapi import HTTPException
from sqlalchemy import select

from .curriculum import recommendation_states
from .db import (
    Attempt,
    DiagnosticRound,
    LearnerProfile,
    LearningScope,
    Question,
    Task,
    TaskProgress,
)
from .diagnostic import build_blueprint, segment_decision
from .diagnostic import diagnostic_view as diagnostic_view
from .learning_context import Activity
from .task_sources import resolve_sources, source_refs
from .task_storage import store_task

FLOW_VERSION = "learning-flow-0.2"
LEVEL_NAMES = {"remember": "记忆", "understand": "理解", "apply": "应用", "analyze": "分析"}
LEVEL_TEXT = {
    "remember": "识别概念与事实",
    "understand": "解释知识的含义",
    "apply": "在情境中执行方法",
    "analyze": "辨别结构、关系和原因",
}


def reject(code, message):
    raise HTTPException(code, message)


def selected_scope(db, user, required=False):
    profile = db.get(LearnerProfile, user.id)
    scope = db.get(LearningScope, profile.scope_id) if profile else None
    if required and (not scope or not scope.published):
        reject(409, "请先选择已开放的学习范围")
    return scope


def scoped_nodes(db, user, nodes):
    scope = selected_scope(db, user)
    if not scope:
        return nodes
    return [n for n in nodes if n["id"] in scope.knowledge_ids]


def round_evidence(db, user, attempts):
    boundaries: dict[tuple[str, str], float] = {}
    rounds = db.scalars(
        select(DiagnosticRound)
        .where(DiagnosticRound.user_id == user.id, DiagnosticRound.status.in_(["active", "completed"]))
        .order_by(DiagnosticRound.created_at.desc(), DiagnosticRound.id.desc())
    ).all()
    for row in rounds:
        for entry in row.blueprint:
            boundaries.setdefault((entry["knowledge_id"], entry["level"]), row.created_at)
    return [a for a in attempts if a["at"] >= boundaries.get((a["knowledge_id"], a["level"]), -1)]


def available_questions(db, nodes):
    ids = {n["id"] for n in nodes}
    latest: dict[str, Any] = {}
    published = select(Question).where(
        Question.status == "published", Question.knowledge_id.in_(ids), Question.level.in_(LEVELS)
    )
    for q in db.scalars(published):
        if q.question_id not in latest or q.version > latest[q.question_id].version:
            latest[q.question_id] = q
    return list(latest.values())


def flow_view(db, task):
    progress = db.get(TaskProgress, task.id)
    if not progress:
        return {"lifecycle": "legacy", "activity": "practice", "resources": [], "feedback": None}
    return {
        "lifecycle": progress.status,
        "activity": progress.data.get("activity", "practice"),
        "scope_id": progress.scope_id,
        "round_id": progress.round_id,
        "goal": progress.data.get("goal"),
        "plan": progress.data.get("plan", []),
        "evidence_facts": progress.data.get("evidence_facts", []),
        "resources": resolve_sources(
            db, task.user_id, progress.data.get("resource_refs", []), task.decision["knowledge_id"]
        ),
        "feedback": progress.data.get("feedback"),
        "resume_level": progress.data.get("resume_level"),
        "implementation": {"orchestration": "rule-baseline", "content": "demo", "llm": "mock/disabled"},
    }


def assert_task_actionable(db, task):
    progress = db.get(TaskProgress, task.id)
    if progress:
        profile = db.get(LearnerProfile, task.user_id)
        if not profile or profile.scope_id != progress.scope_id:
            reject(409, "任务属于其他学习范围，请切回原范围或请求新任务")
        if progress.status in ("skipped", "superseded", "completed"):
            reject(409, "任务已经结束，不能新增作答")
        if progress.status not in ("accepted", "active"):
            reject(409, "请先接受学习安排")


def evidence_facts(state):
    facts = [f"{state['name']}：{state['evidence_count']} 道不同题目的有效证据"]
    facts.extend(
        f"{LEVEL_NAMES[c['level']]}：{c['count']} 题，正确率 "
        + (f"{c['correct_rate']:.0%}" if c["correct_rate"] is not None else "暂无")
        for c in state["cognitive"]
        if c["count"]
    )
    return facts


def learning_plan(resources, activity, decision):
    plan = (
        [{"kind": "read", "title": "回看资料并梳理规则", "required": activity == "material_review"}]
        if resources
        else []
    )
    plan += (
        [{"kind": "answer", "title": "用不同题目收集作答证据", "required": True}]
        if decision["question_keys"]
        else []
    )
    plan.append({"kind": "feedback", "title": "查看证据与下一步建议", "required": True})
    return plan


def persist_task(run, scope, decision, activity):
    db, user, states = run.db, run.user, run.states
    task = Task(
        id=str(uuid4()),
        user_id=user.id,
        mode="diagnostic" if activity.name == "diagnostic" else "practice",
        graph_version=run.graph.version,
        decision=decision,
        evidence_snapshot=states,
        created_at=run.now,
    )
    store_task(db, task)
    state = next(s for s in states if s["knowledge_id"] == decision["knowledge_id"])
    resources = source_refs(db, user, decision["knowledge_id"])
    db.add(
        TaskProgress(
            task_id=task.id,
            scope_id=scope.id,
            round_id=activity.round_id,
            status="recommended",
            data={
                "activity": activity.name,
                "resource_refs": resources,
                "evidence_facts": evidence_facts(state),
                "resume_level": activity.resume_level,
                "plan": learning_plan(resources, activity.name, decision),
                "goal": {
                    "knowledge_id": state["knowledge_id"],
                    "title": state["name"],
                    "level": decision["target_level"],
                    "description": LEVEL_TEXT[decision["target_level"]],
                },
            },
        )
    )
    return task


def require_completed_diagnostic(db, user, scope):
    rounds = db.scalars(
        select(DiagnosticRound).where(
            DiagnosticRound.user_id == user.id, DiagnosticRound.scope_id == scope.id
        )
    ).all()
    if any(r.status == "active" for r in rounds):
        reject(409, "请先完成当前诊断")
    if not any(r.status == "completed" for r in rounds):
        reject(409, "请先完成所选范围的初始诊断")


def needs_material_review(db, user, target, attempts):
    recent_review = (
        db.execute(
            select(TaskProgress).join(Task).where(Task.user_id == user.id, TaskProgress.status == "completed")
        )
        .scalars()
        .all()
    )
    cutoff = max(
        (
            p.data.get("completed_at", 0)
            for p in recent_review
            if p.data.get("activity") == "material_review"
            and p.data.get("goal", {}).get("knowledge_id") == target
        ),
        default=0,
    )
    latest: dict[str, Any] = {}
    for a in sorted(attempts, key=lambda a: a["at"], reverse=True):
        if a["knowledge_id"] == target and a["level"] in ("apply", "analyze") and a["at"] > cutoff:
            latest.setdefault(a["question_id"], a)
    recent = list(latest.values())[:2]
    return len(recent) == 2 and all(not a["correct"] for a in recent)


def needs_application(dims, target, questions, level):
    return (
        not level
        and dims["understand"]["count"] >= 3
        and (dims["understand"]["correct_rate"] or 0) >= 0.8
        and any(q.knowledge_id == target and q.level == "apply" for q in questions)
    ) and (dims["apply"]["count"] < 3 or (dims["apply"]["correct_rate"] or 0) < 0.8)


def recommendation_activity(decision, state, review, refs):
    activity, resume = "practice", None
    if review and refs:
        resume = decision["target_level"]
        decision.update(
            question_keys=[],
            target_level="understand",
            warnings=[],
            reason=f"{state['name']}近期两道不同的应用/分析题未答对，先回看理解资料，再用新题检验；这不是对具体错因的断言。",
        )
        activity = "material_review"
    elif not decision["question_keys"] and refs:
        activity = "material_review"
    decision["material_ids"] = []
    decision["status"] = (
        "ready" if decision["question_keys"] else ("material_review" if refs else "content_unavailable")
    )
    return activity, resume


def create_recommendation(run, knowledge_id=None, level=None, exclude_keys=()):
    db, user = run.db, run.user
    graph, attempts, states = run.graph, run.attempts, run.states
    scope = selected_scope(db, user, True)
    require_completed_diagnostic(db, user, scope)
    nodes = scoped_nodes(db, user, graph.nodes)
    questions = available_questions(db, nodes)
    candidates = [
        {"key": q.key, "question_id": q.question_id, "knowledge_id": q.knowledge_id, "level": q.level}
        for q in questions
        if q.key not in exclude_keys
    ]
    ranked_states = recommendation_states(db, user.id, states)
    try:
        decision = recommend(
            RecommendationEvidence(nodes, ranked_states, attempts), candidates, knowledge_id, level
        )
    except ValueError as exc:
        reject(409, str(exc))
    target = decision["knowledge_id"]
    # The original FR-5.3: adequate understanding + weak application -> application.
    state = next(s for s in states if s["knowledge_id"] == target)
    dims = {c["level"]: c for c in state["cognitive"]}
    if needs_application(dims, target, questions, level):
        decision = recommend(
            RecommendationEvidence(nodes, ranked_states, attempts), candidates, target, "apply"
        )
        decision["reason"] = (
            f"{state['name']}的理解题已有多题支持，应用证据仍需补足，下一步练习按规则执行操作。"
        )
    review = needs_material_review(db, user, target, attempts)
    refs = source_refs(db, user, target)
    activity, resume = recommendation_activity(decision, state, review, refs)
    decision["policy_version"] = FLOW_VERSION
    return persist_task(run, scope, decision, Activity(activity, resume_level=resume))


def create_diagnostic(run, knowledge_id=None, target_level=None):
    db, user = run.db, run.user
    graph, attempts, now = run.graph, run.attempts, run.now
    scope = selected_scope(db, user, True)
    nodes = scoped_nodes(db, user, graph.nodes)
    if knowledge_id and knowledge_id not in scope.knowledge_ids:
        reject(422, "诊断目标不属于所选范围")
    targets = [n["id"] for n in nodes if knowledge_id is None or n["id"] == knowledge_id]
    levels = [target_level] if target_level else LEVELS
    blueprint = build_blueprint(targets, levels, available_questions(db, nodes), attempts)
    if not blueprint:
        reject(409, "目标范围没有已发布诊断题，不能生成诊断结论")
    existing = db.scalar(
        select(DiagnosticRound).where(
            DiagnosticRound.user_id == user.id,
            DiagnosticRound.scope_id == scope.id,
            DiagnosticRound.status == "active",
        )
    )
    if existing:
        reject(409, "该范围还有未完成的诊断，请先继续原诊断")
    row = DiagnosticRound(
        id=str(uuid4()),
        user_id=user.id,
        scope_id=scope.id,
        status="active",
        blueprint=blueprint,
        created_at=now,
    )
    db.add(row)
    db.flush()
    for entry in blueprint:
        decision = segment_decision(entry, FLOW_VERSION)
        persist_task(run, scope, decision, Activity("diagnostic", round_id=row.id))
    return row


def finish_task(run, task, progress):
    db, now, states = run.db, run.now, run.states
    rows = db.scalars(select(Attempt).where(Attempt.task_id == task.id)).all()
    require_completion_evidence(db, progress, task, rows)
    state = next((s for s in states if s["knowledge_id"] == task.decision["knowledge_id"]), None)
    feedback = {
        "answered": len(rows),
        "correct": sum(a.correct for a in rows),
        "message": "已记录资料复习；未增加题目证据或掌握分数，下一步用不同题目检验。"
        if progress.data["activity"] == "material_review"
        else "作答已保存。请结合知识点及各认知维度证据查看下一步安排，单题不代表能力提升。",
        "state": state,
        "next_action": "retest" if progress.data["activity"] == "material_review" else "recommend",
        "knowledge_id": task.decision["knowledge_id"],
        "target_level": progress.data.get("resume_level") or task.decision["target_level"],
    }
    progress.status = "completed"
    progress.data = {**progress.data, "completed_at": now, "feedback": feedback}
    db.flush()
    if progress.round_id:
        diagnostic = db.get(DiagnosticRound, progress.round_id)
        remaining = db.scalar(
            select(TaskProgress.task_id)
            .where(TaskProgress.round_id == diagnostic.id, TaskProgress.status != "completed")
            .limit(1)
        )
        if not remaining:
            diagnostic.status = "completed"
        feedback["next_action"] = "diagnostic_next" if remaining else "diagnostic_done"
        progress.data = {**progress.data, "feedback": feedback}
    return feedback


def require_completion_evidence(db, progress, task, rows):
    if progress.data["activity"] == "material_review":
        if not any(
            not r.get("unavailable")
            for r in resolve_sources(
                db, task.user_id, progress.data.get("resource_refs", []), task.decision["knowledge_id"]
            )
        ):
            reject(409, "资料来源已不可用，请更换任务")
    elif len(rows) != len(task.decision["question_keys"]) or not rows:
        reject(409, "尚未完成所有题目，不能标记任务完成")
