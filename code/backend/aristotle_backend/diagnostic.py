"""Fixed diagnostic blueprints and student-visible round progress."""

from collections import defaultdict

from sqlalchemy import func, select

from .db import Attempt, Task, TaskProgress


def build_blueprint(targets, levels, questions, attempts):
    seen = {attempt["question_id"] for attempt in attempts}
    grouped = defaultdict(list)
    for question in sorted(questions, key=lambda q: (q.question_id in seen, q.key)):
        grouped[question.knowledge_id, question.level].append(question)
    blueprint = []
    for target in targets:
        for level in levels:
            available = grouped[target, level][:3]
            if available:
                blueprint.append(
                    {
                        "knowledge_id": target,
                        "level": level,
                        "keys": [q.key for q in available],
                        "fresh_count": sum(q.question_id not in seen for q in available),
                    }
                )
    return blueprint


def segment_decision(entry, policy_version):
    warnings = []
    if len(entry["keys"]) < 3:
        warnings.append("该认知维度题量不足，完成后仍可能显示证据不足")
    if entry["fresh_count"] < len(entry["keys"]):
        warnings.append("部分题目曾练习过，复测可能受记忆影响；不据此宣称学习收益")
    return {
        "knowledge_id": entry["knowledge_id"],
        "target_level": entry["level"],
        "question_keys": entry["keys"],
        "reason": "本段诊断用于收集特定知识点和认知活动的证据，不要求先修已掌握，也不意味着已完成学习。",
        "warnings": warnings,
        "policy_version": policy_version,
        "material_ids": [],
        "status": "ready",
    }


def diagnostic_view(db, row):
    tasks = db.execute(
        select(Task, TaskProgress, func.count(Attempt.id))
        .join(TaskProgress, TaskProgress.task_id == Task.id)
        .outerjoin(Attempt, Attempt.task_id == Task.id)
        .where(TaskProgress.round_id == row.id)
        .group_by(Task.id, TaskProgress.task_id)
    ).all()
    entries = []
    for t, p, answered in tasks:
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
