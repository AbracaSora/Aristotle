from uuid import uuid4

from aristotle_core.policy import POLICY_VERSION, RecommendationEvidence, recommend
from fastapi import Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.functions import count

from .api_access import current_user, fail, get_db, student, student_session
from .api_views import active_graph, attempt_view, learning_run, learning_state, owned, task_view
from .curriculum import (
    assert_unlocked,
    attempt_timestamp,
    create_preset_task,
    iso,
    lock_user,
    progress_views,
    recommendation_states,
)
from .curriculum import (
    feedback as preset_feedback,
)
from .curriculum_schemas import PresetTaskView, QuestionFeedback
from .db import (
    Attempt,
    CurriculumPoint,
    Material,
    Question,
    StandardQuestion,
    Task,
    TaskProgress,
    TaskQuestion,
)
from .schemas import (
    AttemptInput,
    AttemptView,
    HistoryView,
    LearningStateView,
    TaskInput,
    TaskView,
)
from .task_storage import store_task
from .workflow import (
    assert_task_actionable,
    create_recommendation,
    scoped_nodes,
    selected_scope,
)


def install_task_routes(app):
    @app.get("/api/v1/knowledge", tags=["学习"])
    def knowledge(user=Depends(current_user), db=Depends(get_db)):
        graph = active_graph(db)
        return {"version": graph.version, "nodes": scoped_nodes(db, user, graph.nodes)}

    @app.get("/api/v1/learning-state", response_model=LearningStateView, tags=["学习"])
    def state(request: Request, user=Depends(student), db=Depends(get_db)):
        graph, _, states = learning_state(db, user, request.app.state.clock())
        return {
            "graph_version": graph.version,
            "policy_version": POLICY_VERSION,
            "window_days": 14,
            "states": states,
            "notice": "这是多题作答的规则摘要，不是学生总体认知等级或经验证的能力测量。",
        }

    @app.get("/api/v1/curriculum-progress", tags=["学习"])
    def curriculum_progress(user=Depends(student), db=Depends(get_db)):
        if db.scalar(select(CurriculumPoint.id).limit(1)):
            return {
                key: {"total": v["preset_total"], "completed": v["preset_completed"]}
                for key, v in progress_views(db, user.id).items()
            }
        latest = latest_published(db)
        answered = set(db.scalars(select(Attempt.question_key).where(Attempt.user_id == user.id)))
        result: dict[str, dict[str, int]] = {}
        for q in latest.values():
            item = result.setdefault(q.knowledge_id, {"total": 0, "completed": 0})
            item["total"] += 1
            item["completed"] += int(q.key in answered)
        return result

    @app.post("/api/v1/tasks", status_code=201, response_model=TaskView | PresetTaskView, tags=["学习"])
    def create_task(body: TaskInput, response: Response, ctx=Depends(student_session)):
        now = ctx.request.app.state.clock()
        if (
            body.mode == "practice"
            and body.knowledge_id
            and ctx.db.scalar(select(CurriculumPoint.id).limit(1))
        ):
            task, created = create_preset_task(ctx.db, ctx.user, body.knowledge_id, now)
            ctx.db.commit()
            response.status_code = 201 if created else 200
            return task_view(ctx.db, task)
        run = learning_run(ctx.db, ctx.user, now)
        if selected_scope(ctx.db, ctx.user):
            if body.mode == "diagnostic":
                fail(409, "请选择诊断流程接口创建独立诊断轮次")
            task = create_recommendation(
                run,
                body.knowledge_id,
                body.target_level,
            )
            ctx.db.commit()
            return task_view(ctx.db, task)
        return legacy_task(ctx, body, run)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskView | PresetTaskView, tags=["学习"])
    def get_task(task_id: str, user=Depends(student), db=Depends(get_db)):
        return task_view(db, owned(db, Task, task_id, user))

    @app.post(
        "/api/v1/tasks/{task_id}/attempts", response_model=AttemptView | QuestionFeedback, tags=["学习"]
    )
    def submit(task_id: str, body: AttemptInput, ctx=Depends(student_session)):
        lock_user(ctx.db, ctx.user.id)
        task = owned(ctx.db, Task, task_id, ctx.user)
        q = ctx.db.get(Question, body.question_key)
        if not q or not ctx.db.get(TaskQuestion, (task_id, body.question_key)):
            fail(404, "题目不属于该任务")

        normalize_selection(body, q)

        def result_view(row, replayed):
            if body.selected_option_id is not None:
                if ctx.db.get(StandardQuestion, q.key):
                    return preset_feedback(ctx.db, row, replayed)
                return {
                    "attempt_id": row.id,
                    "question_key": q.key,
                    "selected_option_id": body.selected_option_id,
                    "correct": row.correct,
                    "answer": {"option_id": chr(65 + q.options.index(q.answer))},
                    "explanation": q.explanation,
                    "replayed": replayed,
                    "created_at": iso(row.created_at),
                }
            return {**attempt_view(row, q, ctx.db), "replayed": replayed}

        def existing_result():
            by_submission = ctx.db.scalar(
                select(Attempt).where(
                    Attempt.user_id == ctx.user.id,
                    Attempt.task_id == task_id,
                    Attempt.submission_id == body.submission_id,
                )
            )
            by_question = ctx.db.scalar(
                select(Attempt).where(Attempt.task_id == task_id, Attempt.question_key == body.question_key)
            )
            if by_submission and (
                by_submission.question_key != body.question_key or by_submission.selected != body.selected
            ):
                fail(409, "同一 submission_id 不能用于不同作答")
            row = by_submission or by_question
            if row and row.selected != body.selected:
                fail(409, "本任务的该题已经提交，不能覆盖首次答案")
            return row

        existing = existing_result()
        if existing:
            return result_view(existing, True)
        validate_new_attempt(ctx, task, q, body)
        row = record_attempt(ctx, task, q, body)
        try:
            ctx.db.commit()
        except IntegrityError:
            ctx.db.rollback()
            row = existing_result()
            if not row:
                fail(409, "作答保存冲突，请重试")
            return result_view(row, True)
        return result_view(row, False)

    @app.get("/api/v1/history", response_model=HistoryView, tags=["学习"])
    def history(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user=Depends(student),
        db=Depends(get_db),
    ):
        rows = db.execute(
            select(Attempt, Question)
            .join(Question, Attempt.question_key == Question.key)
            .where(Attempt.user_id == user.id)
            .order_by(Attempt.created_at.desc(), Attempt.id)
            .offset(offset)
            .limit(limit)
        ).all()
        total = db.scalar(select(count()).select_from(Attempt).where(Attempt.user_id == user.id))
        correct_total = db.scalar(
            select(count()).select_from(Attempt).where(Attempt.user_id == user.id, Attempt.correct.is_(True))
        )
        return {
            "items": [attempt_view(a, q, db) for a, q in rows],
            "limit": limit,
            "offset": offset,
            "total": total,
            "correct_total": correct_total,
        }


def question_candidates(db):
    latest = latest_published(db)
    candidates = [
        {"key": q.key, "question_id": q.question_id, "knowledge_id": q.knowledge_id, "level": q.level}
        for q in latest.values()
    ]
    return candidates


def latest_published(db):
    latest: dict[str, Question] = {}
    for q in db.scalars(select(Question).where(Question.status == "published")):
        if q.question_id not in latest or q.version > latest[q.question_id].version:
            latest[q.question_id] = q
    return latest


def link_task_materials(ctx, decision):
    materials = ctx.db.scalars(
        select(Material).where(
            Material.user_id == ctx.user.id,
            Material.deleted.is_(False),
            Material.confirmed.is_(True),
            Material.knowledge_id == decision["knowledge_id"],
        )
    ).all()
    decision["material_ids"] = [m.id for m in materials]
    decision["status"] = (
        "ready" if decision["question_keys"] else ("material_review" if materials else "content_unavailable")
    )


def legacy_task(ctx, body, run):
    candidates = question_candidates(ctx.db)
    try:
        decision = recommend(
            RecommendationEvidence(
                run.graph.nodes, recommendation_states(ctx.db, ctx.user.id, run.states), run.attempts
            ),
            candidates,
            body.knowledge_id,
            body.target_level,
        )
    except ValueError as e:
        fail(409, str(e))
    link_task_materials(ctx, decision)
    task = Task(
        id=str(uuid4()),
        user_id=ctx.user.id,
        mode=body.mode,
        graph_version=run.graph.version,
        decision=decision,
        evidence_snapshot=run.states,
        created_at=run.now,
    )
    store_task(ctx.db, task)
    ctx.db.commit()
    return task_view(ctx.db, task)


def normalize_selection(body, q):
    # Normalize IDs against the frozen option order, preserving old text clients.
    if body.selected_option_id is not None:
        mapping = {chr(65 + i): value for i, value in enumerate(q.options)}
        selected = mapping.get(body.selected_option_id)
        if selected is None or (body.selected is not None and selected != body.selected):
            fail(422, "选项 ID 无效或与答案文本冲突")
        body.selected = selected


def validate_new_attempt(ctx, task, q, body):
    if task.mode == "practice" and ctx.db.get(CurriculumPoint, q.knowledge_id):
        assert_unlocked(ctx.db, ctx.user.id, q.knowledge_id)
    if "preset_set_id" not in task.decision:
        assert_task_actionable(ctx.db, task)
    if q.status != "published":
        fail(409, "题目已停用，不接受新作答；请重新请求任务")
    if body.selected not in q.options:
        fail(422, "提交答案必须属于题目选项")


def record_attempt(ctx, task, q, body):
    row = Attempt(
        id=str(uuid4()),
        user_id=ctx.user.id,
        task_id=task.id,
        question_key=q.key,
        submission_id=body.submission_id,
        selected=body.selected,
        correct=body.selected == q.answer,
        created_at=attempt_timestamp(ctx.db, ctx.user.id, q.key, ctx.request.app.state.clock()),
    )
    progress = ctx.db.get(TaskProgress, task.id)
    ctx.db.add(row)
    if progress:
        progress.status = "active"
    return row
