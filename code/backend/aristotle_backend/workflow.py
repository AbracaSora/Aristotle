"""Persistent learning workflow. Mock providers never write learning evidence."""

from uuid import uuid4

from aristotle_core.policy import LEVELS, recommend
from fastapi import HTTPException
from sqlalchemy import select

from .db import (
    Attempt,
    DiagnosticRound,
    LearnerProfile,
    LearningResource,
    LearningScope,
    Material,
    Question,
    SourceChunk,
    Task,
    TaskProgress,
    TaskQuestion,
)

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
    boundaries = {}
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
    latest = {}
    for q in db.scalars(select(Question).where(Question.status == "published")):
        if (
            q.knowledge_id in ids
            and q.level in LEVELS
            and (q.question_id not in latest or q.version > latest[q.question_id].version)
        ):
            latest[q.question_id] = q
    return list(latest.values())


def source_refs(db, user, knowledge_id):
    refs = [
        {"type": "public", "id": r.id}
        for r in db.scalars(select(LearningResource).where(LearningResource.knowledge_id == knowledge_id))
    ]
    chunks = db.execute(
        select(SourceChunk, Material)
        .join(Material, SourceChunk.material_id == Material.id)
        .where(
            Material.user_id == user.id,
            Material.deleted.is_(False),
            SourceChunk.knowledge_id == knowledge_id,
            SourceChunk.status == "confirmed",
        )
    ).all()
    refs.extend({"type": "chunk", "id": c.id} for c, _ in chunks)
    for m in db.scalars(
        select(Material).where(
            Material.user_id == user.id,
            Material.deleted.is_(False),
            Material.confirmed.is_(True),
            Material.knowledge_id == knowledge_id,
        )
    ):
        if not db.scalar(select(SourceChunk.id).where(SourceChunk.material_id == m.id).limit(1)):
            refs.append({"type": "material", "id": m.id})
    return refs


def resolve_sources(db, user_id, refs, knowledge_id=None):
    result = []
    for ref in refs:
        base = {"id": ref["id"], "type": ref["type"]}
        if ref["type"] == "public":
            row = db.get(LearningResource, ref["id"])
            if row:
                result.append(
                    {
                        **base,
                        "title": row.title,
                        "text": row.text,
                        "location": row.source,
                        "implementation": "demo-content",
                        "knowledge_id": row.knowledge_id,
                    }
                )
                continue
        elif ref["type"] == "chunk":
            chunk = db.get(SourceChunk, ref["id"])
            m = db.get(Material, chunk.material_id) if chunk else None
            if (
                m
                and m.user_id == user_id
                and not m.deleted
                and chunk.status == "confirmed"
                and (not knowledge_id or chunk.knowledge_id == knowledge_id)
            ):
                result.append(
                    {
                        **base,
                        "title": m.title,
                        "text": chunk.text,
                        "location": chunk.location,
                        "implementation": chunk.implementation,
                        "knowledge_id": chunk.knowledge_id,
                    }
                )
                continue
        else:
            m = db.get(Material, ref["id"])
            if (
                m
                and m.user_id == user_id
                and not m.deleted
                and m.confirmed
                and (not knowledge_id or m.knowledge_id == knowledge_id)
            ):
                result.append(
                    {
                        **base,
                        "title": m.title,
                        "text": m.text,
                        "location": "粘贴文本第 1 段",
                        "implementation": "manual",
                        "knowledge_id": m.knowledge_id,
                    }
                )
                continue
        result.append({**base, "unavailable": True, "reason": "来源已删除或关联已取消"})
    return result


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


def persist_task(db, user, scope, graph, states, decision, now, activity, round_id=None, resume_level=None):
    task = Task(
        id=str(uuid4()),
        user_id=user.id,
        mode="diagnostic" if activity == "diagnostic" else "practice",
        graph_version=graph.version,
        decision=decision,
        evidence_snapshot=states,
        created_at=now,
    )
    db.add(task)
    db.flush()
    for i, key in enumerate(decision["question_keys"]):
        db.add(TaskQuestion(task_id=task.id, question_key=key, position=i))
    state = next(s for s in states if s["knowledge_id"] == decision["knowledge_id"])
    facts = [f"{state['name']}：{state['evidence_count']} 道不同题目的有效证据"]
    facts.extend(
        f"{LEVEL_NAMES[c['level']]}：{c['count']} 题，正确率 "
        + (f"{c['correct_rate']:.0%}" if c["correct_rate"] is not None else "暂无")
        for c in state["cognitive"]
        if c["count"]
    )
    resources = source_refs(db, user, decision["knowledge_id"])
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
    db.add(
        TaskProgress(
            task_id=task.id,
            scope_id=scope.id,
            round_id=round_id,
            status="recommended",
            data={
                "activity": activity,
                "resource_refs": resources,
                "evidence_facts": facts,
                "resume_level": resume_level,
                "plan": plan,
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


def create_recommendation(
    db, user, graph, attempts, states, now, knowledge_id=None, level=None, exclude_keys=()
):
    scope = selected_scope(db, user, True)
    rounds = db.scalars(
        select(DiagnosticRound).where(
            DiagnosticRound.user_id == user.id, DiagnosticRound.scope_id == scope.id
        )
    ).all()
    if any(r.status == "active" for r in rounds):
        reject(409, "请先完成当前诊断")
    if not any(r.status == "completed" for r in rounds):
        reject(409, "请先完成所选范围的初始诊断")
    nodes = scoped_nodes(db, user, graph.nodes)
    questions = available_questions(db, nodes)
    candidates = [
        {"key": q.key, "question_id": q.question_id, "knowledge_id": q.knowledge_id, "level": q.level}
        for q in questions
        if q.key not in exclude_keys
    ]
    try:
        decision = recommend(nodes, states, candidates, attempts, knowledge_id, level)
    except ValueError as exc:
        reject(409, str(exc))
    target = decision["knowledge_id"]
    # The original FR-5.3: adequate understanding + weak application -> application.
    state = next(s for s in states if s["knowledge_id"] == target)
    dims = {c["level"]: c for c in state["cognitive"]}
    if (
        not level
        and dims["understand"]["count"] >= 3
        and (dims["understand"]["correct_rate"] or 0) >= 0.8
        and any(q.knowledge_id == target and q.level == "apply" for q in questions)
    ):
        if dims["apply"]["count"] < 3 or (dims["apply"]["correct_rate"] or 0) < 0.8:
            decision = recommend(nodes, states, candidates, attempts, target, "apply")
            decision["reason"] = (
                f"{state['name']}的理解题已有多题支持，应用证据仍需补足，下一步练习按规则执行操作。"
            )
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
    latest = {}
    for a in sorted(attempts, key=lambda a: a["at"], reverse=True):
        if a["knowledge_id"] == target and a["level"] in ("apply", "analyze") and a["at"] > cutoff:
            latest.setdefault(a["question_id"], a)
    recent = list(latest.values())[:2]
    review = len(recent) == 2 and all(not a["correct"] for a in recent)
    refs = source_refs(db, user, target)
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
    decision["policy_version"] = FLOW_VERSION
    return persist_task(db, user, scope, graph, states, decision, now, activity, resume_level=resume)


def create_diagnostic(db, user, graph, attempts, states, now, knowledge_id=None, target_level=None):
    scope = selected_scope(db, user, True)
    nodes = scoped_nodes(db, user, graph.nodes)
    if knowledge_id and knowledge_id not in scope.knowledge_ids:
        reject(422, "诊断目标不属于所选范围")
    qs = available_questions(db, nodes)
    seen = {a["question_id"] for a in attempts}
    blueprint = []
    for node in nodes:
        if knowledge_id and node["id"] != knowledge_id:
            continue
        for level in LEVELS:
            if target_level and level != target_level:
                continue
            available = sorted(
                (q for q in qs if q.knowledge_id == node["id"] and q.level == level),
                key=lambda q: (q.question_id in seen, q.key),
            )[:3]
            if available:
                blueprint.append(
                    {
                        "knowledge_id": node["id"],
                        "level": level,
                        "keys": [q.key for q in available],
                        "fresh_count": sum(q.question_id not in seen for q in available),
                    }
                )
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
        warnings = []
        if len(entry["keys"]) < 3:
            warnings.append("该认知维度题量不足，完成后仍可能显示证据不足")
        if entry["fresh_count"] < len(entry["keys"]):
            warnings.append("部分题目曾练习过，复测可能受记忆影响；不据此宣称学习收益")
        decision = {
            "knowledge_id": entry["knowledge_id"],
            "target_level": entry["level"],
            "question_keys": entry["keys"],
            "reason": "本段诊断用于收集特定知识点和认知活动的证据，不要求先修已掌握，也不意味着已完成学习。",
            "warnings": warnings,
            "policy_version": FLOW_VERSION,
            "material_ids": [],
            "status": "ready",
        }
        persist_task(db, user, scope, graph, states, decision, now, "diagnostic", row.id)
    return row


def diagnostic_view(db, row):
    tasks = db.execute(
        select(Task, TaskProgress)
        .join(TaskProgress)
        .where(TaskProgress.round_id == row.id)
        .order_by(Task.created_at, Task.id)
    ).all()
    entries = []
    for t, p in tasks:
        answered = len(db.scalars(select(Attempt).where(Attempt.task_id == t.id)).all())
        entries.append(
            {
                "task_id": t.id,
                "knowledge_id": t.decision["knowledge_id"],
                "level": t.decision["target_level"],
                "question_count": len(t.decision["question_keys"]),
                "answered": answered,
                "status": p.status,
            }
        )
    # blueprint ordering, not random UUID ordering, determines student progression.
    order = {(b["knowledge_id"], b["level"]): i for i, b in enumerate(row.blueprint)}
    entries.sort(key=lambda e: order[(e["knowledge_id"], e["level"])])
    return {
        "id": row.id,
        "scope_id": row.scope_id,
        "status": row.status,
        "created_at": row.created_at,
        "segments": entries,
        "completed_segments": sum(e["status"] == "completed" for e in entries),
        "notice": "演示题诊断采用规则基线，尚未验证测量效度；阅读不会增加掌握证据。",
    }


def finish_task(db, task, progress, now, states):
    rows = db.scalars(select(Attempt).where(Attempt.task_id == task.id)).all()
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
