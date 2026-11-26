"""Final-paper eligibility, immutable snapshots and deterministic whole-sheet grading."""

from uuid import uuid4

from sqlalchemy import func, select

from .curriculum import POLICY, assert_unlocked, fail, iso, lock_user, progress_views, public_question
from .db import FinalTest, Question, StandardQuestion
from .model_jobs import ensure_enabled
from .providers import ProviderFailure, fingerprint, provider_config


def service_ready(db):
    try:
        ensure_enabled(db)
        cfg = provider_config("generation")
        if not cfg.configured:
            raise ProviderFailure("not_configured", "尚未配置 AI 小测生成服务")
        return cfg
    except ProviderFailure as exc:
        fail(503, str(exc))


def published_examples(db, keys):
    query = (
        select(StandardQuestion)
        .join(Question, Question.key == StandardQuestion.key)
        .where(StandardQuestion.key.in_(keys), Question.status == "published")
    )
    data = {row.key: row.data for row in db.scalars(query)}
    if any(key not in data for key in keys):
        fail(409, "预设题已停用，请更新预设集合")
    fields = ("stem", "options", "answer", "explanation", "bloom_level")
    return [{field: data[key][field] for field in fields} for key in keys]


def eligible_point(db, user, knowledge_id):
    point = assert_unlocked(db, user.id, knowledge_id)
    state = progress_views(db, user.id)[knowledge_id]
    if not state["ai_test"]["eligible"]:
        fail(409, "必须先完成全部预设题，且本期不开放已通过后的重测")
    if db.scalar(
        select(FinalTest.id).where(
            FinalTest.user_id == user.id,
            FinalTest.knowledge_id == knowledge_id,
            FinalTest.status.in_(("generating", "ready")),
        )
    ):
        fail(409, "已有进行中的小测，请继续原试卷")
    return point


def next_version(db, user_id, knowledge_id):
    query = select(func.max(FinalTest.version)).where(
        FinalTest.user_id == user_id, FinalTest.knowledge_id == knowledge_id
    )
    return (db.scalar(query) or 0) + 1


def create_test(action, knowledge_id, body):
    db, user, now = action.db, action.user, action.now
    lock_user(db, user.id)
    previous = db.scalar(
        select(FinalTest).where(FinalTest.user_id == user.id, FinalTest.request_id == body.request_id)
    )
    rules = body.rules.model_dump()
    if previous:
        if previous.knowledge_id != knowledge_id or previous.rules != rules:
            fail(409, "同一 request_id 不能对应不同知识点或规则")
        return previous, False
    point = eligible_point(db, user, knowledge_id)
    cfg = service_ready(db)
    preset = point.data["preset_set"]
    row = FinalTest(
        id=str(uuid4()),
        user_id=user.id,
        knowledge_id=knowledge_id,
        version=next_version(db, user.id, knowledge_id),
        request_id=body.request_id,
        preset_set_id=preset["id"],
        preset_set_version=preset["version"],
        status="generating",
        rules=rules,
        generation_context={
            "knowledge_name": point.data["name"],
            "description": point.data["description"],
            "examples": published_examples(db, preset["question_keys"]),
            "namespace": cfg.namespace,
            "policy_version": POLICY,
            "prompt_version": "final-test-v1",
        },
        questions=[],
        client_context={},
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row, True


def created_view(row):
    return {
        "test_id": row.id,
        "knowledge_id": row.knowledge_id,
        "version": row.version,
        "status": row.status,
        "created_at": iso(row.created_at),
    }


def test_summary(row):
    return {
        **created_view(row),
        "score": row.result["score"] if row.result else None,
        "passed": row.result["passed"] if row.result else None,
        "submitted_at": iso(row.submitted_at) if row.submitted_at is not None else None,
    }


def detail_view(row):
    visible = row.status in ("ready", "submitted")
    return {
        **created_view(row),
        "questions": [public_question(q) for q in row.questions] if visible else [],
        "rules": row.rules if visible else None,
        "result": row.result if row.status == "submitted" else None,
        "error": row.error if row.status == "generation_failed" else None,
    }


def own_test(db, user_id, test_id):
    row = db.get(FinalTest, test_id)
    if not row or row.user_id != user_id:
        fail(404, "小测不存在")
    return row


def grade_answers(questions, answers):
    if set(answers) != {q["key"] for q in questions}:
        fail(422, "必须整卷提交，不能遗漏或增加试卷外题目")
    feedback = []
    for q in questions:
        selected = answers[q["key"]]
        if selected not in {o["id"] for o in q["options"]}:
            fail(422, "答案选项不存在")
        feedback.append(
            {
                "question_key": q["key"],
                "selected_option_id": selected,
                "correct": selected == q["answer"]["option_id"],
                "answer": q["answer"],
                "explanation": q["explanation"],
            }
        )
    return feedback


def submission_result(row, feedback, now):
    score = sum(f["correct"] for f in feedback) / len(feedback)
    passed = score >= row.rules["pass_score"]
    # No Attempt rows are written: these answers never count as preset completion.
    return {
        "test_id": row.id,
        "status": "submitted",
        "score": score,
        "passed": passed,
        "knowledge_status": "mastered" if passed else "completed",
        "submitted_at": iso(now),
        "replayed": False,
        "feedback": feedback,
        "learning_feedback": {
            "source": "rule",
            "status": "pending",
            "summary": "小测已通过。" if passed else "小测尚未通过；预设题完成记录保留。",
            "suggestions": ["结合错题解析复习，再选择下一步学习。"],
            "history_count": 0,
        },
        "events": [
            {
                "event_id": f"{row.id}-submitted",
                "type": "ai_test_submitted",
                "knowledge_id": row.knowledge_id,
                "occurred_at": iso(now),
            }
        ],
    }


def mastery_event(db, row):
    if not row.result["passed"]:
        return []
    state = progress_views(db, row.user_id).get(row.knowledge_id)
    if not state or not state["unlocked"] or state["ai_test"]["passed_test_id"] != row.id:
        return []
    return [
        {
            "event_id": f"{row.id}-mastered",
            "type": "knowledge_mastered",
            "knowledge_id": row.knowledge_id,
            "occurred_at": iso(row.submitted_at),
        }
    ]


def require_current_preset(db, row):
    point = assert_unlocked(db, row.user_id, row.knowledge_id)
    preset = point.data["preset_set"]
    if (preset["id"], preset["version"]) != (row.preset_set_id, row.preset_set_version):
        fail(409, "该试卷对应的预设集合已变更，请联系维护者处理旧试卷")


def submit_test(action, test_id, body):
    db, user, now = action.db, action.user, action.now
    lock_user(db, user.id)
    row = own_test(db, user.id, test_id)
    context = body.client_context.model_dump() if body.client_context else {}
    answers = {a.question_key: a.selected_option_id for a in body.answers}
    signature = fingerprint({"answers": answers, "client_context": context})
    if len(answers) != len(body.answers):
        fail(422, "试卷答案不能重复")
    if row.status == "submitted":
        if row.submission_id != body.submission_id or row.submission_hash != signature:
            fail(409, "已提交试卷不能修改，重试必须使用原 submission_id 与原内容")
        return {**row.result, "replayed": True}, False
    if row.status != "ready":
        fail(409, "试卷尚未生成完成")
    require_current_preset(db, row)
    feedback = grade_answers(row.questions, answers)
    row.status, row.submitted_at = "submitted", now
    row.submission_id, row.submission_hash, row.client_context = body.submission_id, signature, context
    row.result = submission_result(row, feedback, now)
    db.flush()
    row.result = {**row.result, "events": row.result["events"] + mastery_event(db, row)}
    return row.result, True
