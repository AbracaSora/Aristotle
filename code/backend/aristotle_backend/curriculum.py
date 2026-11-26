"""One authoritative completion/unlock calculation for the 408 curriculum.

Progress is derived from committed attempts and final-test results, so no mutable
cache can disagree with scoring. Old diagnostic evidence remains a separate API.
"""

from datetime import datetime, timezone
from math import inf, nextafter
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.sql.functions import count

from .curriculum_publication import publish_curriculum as publish_curriculum
from .curriculum_schemas import QuestionPublic
from .db import (
    Attempt,
    CurriculumChapter,
    CurriculumPoint,
    CurriculumSubject,
    FinalTest,
    PresetTask,
    Question,
    StandardQuestion,
    Task,
    User,
)
from .task_storage import store_task

POLICY = "mastery-v2"


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")


def fail(status, message):
    raise HTTPException(status, message)


def lock_user(db, user_id):
    # Also acquires a write lock under SQLite tests. PostgreSQL locks just this row.
    db.execute(update(User).where(User.id == user_id).values(id=User.id))


def attempt_timestamp(db, user_id, question_key, now):
    """Called under the learner lock. Preserve submission order even at equal clock ticks."""
    latest = db.scalar(
        select(func.max(Attempt.created_at)).where(
            Attempt.user_id == user_id, Attempt.question_key == question_key
        )
    )
    return now if latest is None or now > latest else nextafter(latest, inf)


def published_points(db):
    subjects = {s.id for s in db.scalars(select(CurriculumSubject)) if s.data["status"] == "published"}
    chapters = {
        c.id
        for c in db.scalars(select(CurriculumChapter))
        if c.data["status"] == "published" and c.subject_id in subjects
    }
    return {
        p.id: p
        for p in db.scalars(select(CurriculumPoint))
        if p.data["status"] == "published" and p.chapter_id in chapters
    }


def point_or_404(db, knowledge_id):
    p = published_points(db).get(knowledge_id)
    if not p:
        fail(404, "知识点不存在或未发布")
    return p


def subjects_view(db):
    points = published_points(db)
    chapters = list(db.scalars(select(CurriculumChapter)))
    result = []

    def order(x):
        return (x.data["order"], x.id)

    for s in sorted(db.scalars(select(CurriculumSubject)), key=order):
        if s.data["status"] != "published":
            continue
        nested = []
        for c in sorted(chapters, key=order):
            if c.subject_id == s.id and c.data["status"] == "published":
                nested.append(
                    {
                        **c.data,
                        "knowledge_points": [
                            {**p.data, "updated_at": iso(p.updated_at)}
                            for p in sorted(points.values(), key=order)
                            if p.chapter_id == c.id
                        ],
                    }
                )
        result.append({**s.data, "chapters": nested})
    return result


def attempt_statistics(db, user_id):
    """Return one aggregate per question; never hydrate the learner's entire history."""
    key = Attempt.question_key
    ranked = (
        select(
            key,
            func.count().over(partition_by=key).label("count"),
            func.sum(case((Attempt.correct.is_(True), 1), else_=0)).over(partition_by=key).label("correct"),
            Attempt.created_at.label("updated_at"),
            Attempt.correct.label("latest_correct"),
            func.row_number()
            .over(partition_by=key, order_by=(Attempt.created_at.desc(), Attempt.id.desc()))
            .label("rank"),
        )
        .join(Question, Question.key == key)
        .where(Attempt.user_id == user_id, Question.status == "published")
        .subquery()
    )
    return {row.question_key: row for row in db.execute(select(ranked).where(ranked.c.rank == 1))}


def test_statistics(db, user_id):
    """Read only summary fields, excluding papers, prompts and feedback payloads."""
    grouped: dict[tuple[str, str, int], dict] = {}
    query = (
        select(
            FinalTest.id,
            FinalTest.knowledge_id,
            FinalTest.preset_set_id,
            FinalTest.preset_set_version,
            FinalTest.status,
            FinalTest.result["passed"].as_boolean().label("passed"),
            func.coalesce(FinalTest.submitted_at, FinalTest.created_at).label("updated_at"),
        )
        .where(FinalTest.user_id == user_id)
        .order_by(FinalTest.version)
    )
    for row in db.execute(query):
        key = (row.knowledge_id, row.preset_set_id, row.preset_set_version)
        stats = grouped.setdefault(key, {"latest": None, "passed": None, "updated_at": 0})
        stats["latest"] = row.id
        stats["updated_at"] = max(stats["updated_at"], row.updated_at)
        if row.status == "submitted" and row.passed:
            stats["passed"] = row.id
    return grouped


def mastery_status(completed, total, passed):
    if total and completed == total:
        return "mastered" if passed else "covered"
    return "learning" if completed else "new"


def prerequisite_counts(total, completed, latest_correct):
    required = (2 * total + 2) // 3
    return {
        "latest_correct_count": latest_correct,
        "required_correct_count": required,
        "prerequisite_qualified": total > 0 and completed == total and latest_correct >= required,
    }


def point_progress(point, attempts, tests):
    preset = point.data["preset_set"]
    rows = [attempts[key] for key in preset["question_keys"] if key in attempts]
    total, completed = len(preset["question_keys"]), len(rows)
    current = tests.get((point.id, preset["id"], preset["version"]), {})
    count, correct = sum(row.count for row in rows), sum(row.correct for row in rows)
    latest_correct = sum(row.latest_correct for row in rows)
    status = mastery_status(completed, total, current.get("passed"))
    return {
        "knowledge_id": point.id,
        "policy_version": POLICY,
        "preset_set_id": preset["id"],
        "preset_set_version": preset["version"],
        "mastery_status": status,
        "preset_total": total,
        "preset_completed": completed,
        **prerequisite_counts(total, completed, latest_correct),
        "completion_rate": completed / total if total else None,
        "attempt_count": count,
        "correct_attempt_count": correct,
        "accuracy": correct / count if count else None,
        "ai_test": {
            "eligible": False,
            "latest_test_id": current.get("latest"),
            "passed_test_id": current.get("passed") if status == "mastered" else None,
        },
        "updated_at": iso(
            max([point.updated_at, current.get("updated_at", 0)] + [row.updated_at for row in rows])
        ),
    }


def apply_unlock(point, values):
    unmet = [
        key
        for key in point.data["prerequisite_ids"]
        if key not in values or not values[key]["prerequisite_qualified"]
    ]
    value = values[point.id]
    value["unlocked"], value["unmet_prerequisite_ids"] = not unmet, unmet
    value["ai_test"]["eligible"] = not unmet and value["mastery_status"] == "covered"


def progress_views(db, user_id):
    points = published_points(db)
    if not points:
        return {}
    attempts, tests = attempt_statistics(db, user_id), test_statistics(db, user_id)
    values = {point.id: point_progress(point, attempts, tests) for point in points.values()}
    for point in points.values():
        apply_unlock(point, values)
    return values


def recommendation_states(db, user_id, evidence):
    progress = progress_views(db, user_id)
    return [
        {**state, "unmet_prerequisites": progress[key]["unmet_prerequisite_ids"]}
        if (key := state["knowledge_id"]) in progress
        else state
        for state in evidence
    ]


def locked_course_points(db, user_id):
    return {key for key, value in progress_views(db, user_id).items() if not value["unlocked"]}


def summary(v):
    return {
        "knowledge_id": v["knowledge_id"],
        "unlocked": v["unlocked"],
        "status": "locked"
        if not v["unlocked"]
        else {"new": "available", "learning": "available", "covered": "completed", "mastered": "mastered"}[
            v["mastery_status"]
        ],
        "completed_count": v["preset_completed"],
        "total_count": v["preset_total"],
        "latest_correct_count": v["latest_correct_count"],
        "required_correct_count": v["required_correct_count"],
        "prerequisite_qualified": v["prerequisite_qualified"],
        "unmet_prerequisite_ids": v["unmet_prerequisite_ids"],
        "ai_test_eligible": v["ai_test"]["eligible"],
        "passed_test_id": v["ai_test"]["passed_test_id"],
    }


def assert_unlocked(db, user_id, knowledge_id):
    point = point_or_404(db, knowledge_id)
    if not progress_views(db, user_id)[knowledge_id]["unlocked"]:
        fail(409, "每个直接先修知识点须完成全部预设题，且各题最近一次作答正确的比例至少为三分之二")
    return point


def public_question(data):
    keys = (
        "type",
        "content_format",
        "secondary_bloom_levels",
        "review_status",
        "question_id",
        "version",
        "key",
        "knowledge_id",
        "related_knowledge_ids",
        "stem",
        "options",
        "source",
        "bloom_level",
        "difficulty",
        "tag_ids",
        "dataset",
    )
    return QuestionPublic.model_validate({key: data[key] for key in keys if key in data}).model_dump(
        mode="json"
    )


def preset_questions(db, point):
    result = []
    for key in point.data["preset_set"]["question_keys"]:
        q, snapshot = db.get(Question, key), db.get(StandardQuestion, key)
        if not q or q.status != "published" or not snapshot:
            fail(409, "预设题版本已停用或不可用，请维护者发布新的预设集合")
        result.append(public_question(snapshot.data))
    return result


def feedback(db, attempt, replayed=False):
    data = db.get(StandardQuestion, attempt.question_key).data
    return {
        "attempt_id": attempt.id,
        "question_key": attempt.question_key,
        "selected_option_id": next(o["id"] for o in data["options"] if o["text"] == attempt.selected),
        "correct": attempt.correct,
        "answer": data["answer"],
        "explanation": data["explanation"],
        "replayed": replayed,
        "created_at": iso(attempt.created_at),
        "events": [],
    }


def preset_task_view(db, task):
    keys = task.decision["question_keys"]
    attempts = list(
        db.scalars(select(Attempt).where(Attempt.task_id == task.id).order_by(Attempt.created_at, Attempt.id))
    )
    answered = {a.question_key for a in attempts}
    return {
        "id": task.id,
        "mode": "practice",
        "activity": "preset_practice",
        "graph_version": task.graph_version,
        **task.decision,
        "questions": [public_question(db.get(StandardQuestion, key).data) for key in keys],
        "attempts": [feedback(db, a) for a in attempts],
        "next_question_key": next((key for key in keys if key not in answered), None),
        "created_at": task.created_at,
    }


def create_preset_task(db, user, knowledge_id, now):
    lock_user(db, user.id)
    point = assert_unlocked(db, user.id, knowledge_id)
    preset_questions(db, point)
    preset = point.data["preset_set"]
    binding = db.get(PresetTask, (user.id, preset["id"], preset["version"]))
    if binding:
        return db.get(Task, binding.task_id), False
    return allocate_preset_task(db, user.id, point, now), True


def allocate_preset_task(db, user_id, point, now):
    preset = point.data["preset_set"]
    task = Task(
        id=str(uuid4()),
        user_id=user_id,
        mode="practice",
        graph_version=point.graph_version,
        decision={
            "knowledge_id": point.id,
            "preset_set_id": preset["id"],
            "preset_set_version": preset["version"],
            "question_keys": preset["question_keys"],
            "policy_version": POLICY,
        },
        evidence_snapshot=[],
        created_at=now,
    )
    store_task(db, task)
    db.merge(
        PresetTask(
            user_id=user_id, preset_set_id=preset["id"], preset_set_version=preset["version"], task_id=task.id
        )
    )
    db.flush()
    return task


def retry_preset(db, user_id, task_id, now):
    lock_user(db, user_id)
    previous = db.get(Task, task_id)
    if not previous or previous.user_id != user_id or "preset_set_id" not in previous.decision:
        fail(404, "预设练习不存在")
    point = assert_unlocked(db, user_id, previous.decision["knowledge_id"])
    preset = point.data["preset_set"]
    if (preset["id"], preset["version"]) != (
        previous.decision["preset_set_id"],
        previous.decision["preset_set_version"],
    ):
        fail(409, "预设集合已经更新，请重新进入练习")
    if successor := previous.decision.get("retry_task_id"):
        return db.get(Task, successor), False
    submitted = db.scalar(select(count()).select_from(Attempt).where(Attempt.task_id == task_id))
    if not submitted or submitted != len(preset["question_keys"]):
        fail(409, "请先完成本轮预设练习")
    preset_questions(db, point)
    task = allocate_preset_task(db, user_id, point, now)
    previous.decision = {**previous.decision, "retry_task_id": task.id}
    return task, True
