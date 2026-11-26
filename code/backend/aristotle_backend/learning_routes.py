from fastapi import Depends, Request
from sqlalchemy import select

from .api_access import student_session
from .api_views import learning_run
from .curriculum import lock_user, locked_course_points
from .db import (
    DiagnosticRound,
    LearnerProfile,
    LearningScope,
    Task,
    TaskProgress,
)
from .flow_schemas import (
    DiagnosticInput,
    ScopeChoice,
    TaskAction,
)
from .schemas import TaskInput
from .workflow import (
    assert_task_actionable,
    create_diagnostic,
    create_recommendation,
    diagnostic_view,
    finish_task,
    reject,
    selected_scope,
)


def install(app, dependencies, services):
    get_db = dependencies.get_db
    current_user = dependencies.current_user
    student = dependencies.student
    state_of, graph_of, task_view, owned, audit_record = services

    def scope_view(scope):
        return {
            "id": scope.id,
            "title": scope.title,
            "knowledge_ids": scope.knowledge_ids,
            "published": scope.published,
            "description": scope.description,
        }

    @app.get("/api/v1/capabilities", tags=["学习流程"])
    def capabilities(user=Depends(current_user)):
        from .providers import ProviderFailure, provider_config

        def configured(kind):
            try:
                return provider_config(kind).configured
            except ProviderFailure:
                return False

        return {
            "flow_version": "learning-flow-0.2",
            "modules": {
                "identity_and_storage": "implemented",
                "scope_and_task_lifecycle": "implemented",
                "diagnosis_and_recommendation": "rule-baseline",
                "content_bank": "demo-fixtures",
                "pdf_extraction": "pypdf-text",
                "knowledge_association": "name-match-v1-requires-confirmation",
                "knowledge_map": "interactive-prerequisite-map",
                "semantic_retrieval": "pgvector" if configured("embedding") else "not-configured",
                "llm_annotation": "openai-compatible" if configured("generation") else "not-configured",
                "llm_explanation": "grounded-openai-compatible"
                if configured("generation")
                else "not-configured",
                "backup_and_performance_acceptance": "not_implemented",
            },
        }

    @app.get("/api/v1/scopes", tags=["学习流程"])
    def scopes(user=Depends(current_user), db=Depends(get_db)):
        return {"items": [scope_view(s) for s in db.scalars(select(LearningScope))]}

    @app.patch("/api/v1/learning-scope", tags=["学习流程"])
    def choose_scope(body: ScopeChoice, user=Depends(student), db=Depends(get_db)):
        scope = db.get(LearningScope, body.scope_id)
        if not scope or not scope.published:
            reject(409, "该范围尚未开放，不会删除你的其他学习记录")
        graph_ids = {n["id"] for n in graph_of(db).nodes}
        if not scope.knowledge_ids or not set(scope.knowledge_ids) <= graph_ids:
            reject(409, "范围引用的知识结构尚未发布")
        profile = db.get(LearnerProfile, user.id)
        if profile:
            profile.scope_id = scope.id
        else:
            db.add(LearnerProfile(user_id=user.id, scope_id=scope.id))
        db.commit()
        return {"selected_scope": scope_view(scope), "history_preserved": True}

    @app.get("/api/v1/learning-context", tags=["学习流程"])
    def context(user=Depends(student), db=Depends(get_db)):
        scope = selected_scope(db, user)
        if not scope:
            return {
                "selected_scope": None,
                "diagnostic": None,
                "current_task": None,
                "last_feedback": None,
                "stage": "scope",
            }
        diagnostic = db.scalar(
            select(DiagnosticRound)
            .where(DiagnosticRound.user_id == user.id, DiagnosticRound.scope_id == scope.id)
            .order_by(DiagnosticRound.created_at.desc())
            .limit(1)
        )
        active, feedback = scope_activity(db, user, scope)
        return {
            "selected_scope": scope_view(scope),
            "diagnostic": diagnostic_view(db, diagnostic) if diagnostic else None,
            "current_task": task_view(db, active) if active else None,
            "last_feedback": feedback,
            "stage": "diagnosis"
            if not diagnostic or diagnostic.status == "active"
            else ("activity" if active else "recommendation"),
        }

    @app.post("/api/v1/diagnostics", status_code=201, tags=["学习流程"])
    def start_diagnostic(body: DiagnosticInput, request: Request, user=Depends(student), db=Depends(get_db)):
        run = learning_run(db, user, request.app.state.clock())
        row = create_diagnostic(
            run,
            body.knowledge_id,
            body.target_level,
        )
        db.commit()
        return diagnostic_view(db, row)

    @app.get("/api/v1/diagnostics/{round_id}", tags=["学习流程"])
    def get_diagnostic(round_id: str, user=Depends(student), db=Depends(get_db)):
        return diagnostic_view(db, owned(db, DiagnosticRound, round_id, user))

    @app.post("/api/v1/diagnostics/{round_id}/restart", status_code=201, tags=["学习流程"])
    def restart_diagnostic(round_id: str, request: Request, user=Depends(student), db=Depends(get_db)):
        old = owned(db, DiagnosticRound, round_id, user)
        scope = selected_scope(db, user, True)
        if old.status != "active" or old.scope_id != scope.id:
            reject(409, "只能重建当前范围的未完成诊断")
        for progress in db.scalars(select(TaskProgress).where(TaskProgress.round_id == old.id)):
            if progress.status != "completed":
                progress.status = "superseded"
        old.status = "superseded"
        db.flush()
        run = learning_run(db, user, request.app.state.clock())
        target = old.blueprint[0] if len(old.blueprint) == 1 else {}
        row = create_diagnostic(
            run,
            target.get("knowledge_id"),
            target.get("level"),
        )
        db.commit()
        return diagnostic_view(db, row)

    @app.post("/api/v1/recommendations", status_code=201, tags=["学习流程"])
    def recommendation(body: TaskInput, request: Request, user=Depends(student), db=Depends(get_db)):
        lock_user(db, user.id)
        run = learning_run(db, user, request.app.state.clock())
        scope = selected_scope(db, user, True)
        existing = pending_recommendation(db, user, scope)
        locked = locked_course_points(db, user.id)
        if body.knowledge_id in locked:
            reject(409, "请先完成各直接前驱预设并达到三分之二正确率")
        if existing:
            if existing.decision["knowledge_id"] not in locked:
                return task_view(db, existing)
            old = db.get(TaskProgress, existing.id)
            old.status = "superseded"
            old.data = {
                **old.data,
                "reason": "先修正确率回落，请先复习前驱",
                "ended_at": request.app.state.clock(),
            }
        task = create_recommendation(
            run,
            body.knowledge_id,
            body.target_level,
        )
        db.commit()
        return task_view(db, task)

    @app.post("/api/v1/tasks/{task_id}/actions", tags=["学习流程"])
    def task_action(task_id: str, body: TaskAction, ctx=Depends(student_session)):
        lock_user(ctx.db, ctx.user.id)
        task = owned(ctx.db, Task, task_id, ctx.user)
        progress = ctx.db.get(TaskProgress, task.id)
        if not progress:
            reject(409, "这是旧版练习记录，请从学习计划请求新任务")
        scope = selected_scope(ctx.db, ctx.user, True)
        if progress.scope_id != scope.id:
            reject(409, "请先切回任务所属范围")
        if progress.status == "completed" and body.action == "complete":
            return {"task": task_view(ctx.db, task), "replacement": None}
        validate_transition(ctx, task, progress, body)
        replacement = apply_transition(ctx, task, progress, body)
        ctx.db.commit()
        return {
            "task": task_view(ctx.db, task),
            "replacement": task_view(ctx.db, replacement) if replacement else None,
        }

    @app.post("/api/v1/tasks/{task_id}/explanation", tags=["学习流程"])
    def explanation_placeholder(task_id: str, user=Depends(student), db=Depends(get_db)):
        owned(db, Task, task_id, user)
        reject(501, "模型解释适配器尚未实现；当前展示规则依据和已审核静态解析")

    @app.get("/api/v1/learning-timeline", tags=["学习流程"])
    def timeline(user=Depends(student), db=Depends(get_db)):
        rows = db.execute(
            select(Task, TaskProgress)
            .join(TaskProgress)
            .where(Task.user_id == user.id)
            .order_by(Task.created_at.desc())
            .limit(100)
        ).all()
        return {
            "items": [
                {
                    "id": t.id,
                    "scope_id": p.scope_id,
                    "mode": t.mode,
                    "status": p.status,
                    "goal": p.data.get("goal"),
                    "activity": p.data.get("activity"),
                    "created_at": t.created_at,
                    "feedback": p.data.get("feedback"),
                    "policy_version": t.decision["policy_version"],
                }
                for t, p in rows
            ]
        }


def scope_activity(db, user, scope):
    tasks = db.execute(
        select(Task, TaskProgress)
        .join(TaskProgress)
        .where(Task.user_id == user.id, TaskProgress.scope_id == scope.id)
        .order_by(Task.created_at.desc(), Task.id.desc())
    ).all()
    locked = locked_course_points(db, user.id)
    active = next(
        (
            t
            for t, p in tasks
            if p.status in ("recommended", "accepted", "active")
            and not p.round_id
            and t.decision["knowledge_id"] not in locked
        ),
        None,
    )
    completed = [p for _, p in tasks if p.status == "completed"]
    feedback = (
        max(completed, key=lambda p: p.data.get("completed_at", 0)).data.get("feedback")
        if completed
        else None
    )
    return active, feedback


def pending_recommendation(db, user, scope):
    active = db.scalar(
        select(DiagnosticRound).where(
            DiagnosticRound.user_id == user.id,
            DiagnosticRound.scope_id == scope.id,
            DiagnosticRound.status == "active",
        )
    )
    if active:
        reject(409, "请先完成当前诊断，再查看基于本轮证据的推荐")
    existing = db.scalar(
        select(Task)
        .join(TaskProgress)
        .where(
            Task.user_id == user.id,
            TaskProgress.scope_id == scope.id,
            TaskProgress.round_id.is_(None),
            TaskProgress.status.in_(["recommended", "accepted", "active"]),
        )
        .order_by(Task.created_at.desc())
        .limit(1)
    )
    return existing


def validate_transition(ctx, task, progress, body):
    if progress.status in ("completed", "skipped", "superseded"):
        reject(409, "该任务已结束")
    if progress.round_id and body.action in ("skip", "replace"):
        reject(409, "诊断片段需要完成才能汇总；可以关闭并稍后继续")
    if not progress.round_id and body.action in ("accept", "start", "complete"):
        if task.decision["knowledge_id"] in locked_course_points(ctx.db, ctx.user.id):
            reject(409, "先修条件已变化，请先复习前驱知识点")


def apply_transition(ctx, task, progress, body):
    replacement = None
    if body.action in ("accept", "start"):
        if task.decision["status"] == "content_unavailable":
            reject(409, "内容不足，不能接受为空任务")
        progress.status = "accepted" if body.action == "accept" else "active"
        progress.data = {**progress.data, "accepted_at": ctx.request.app.state.clock()}
    elif body.action == "complete":
        assert_task_actionable(ctx.db, task)
        run = learning_run(ctx.db, ctx.user, ctx.request.app.state.clock())
        finish_task(
            run,
            task,
            progress,
        )
    else:
        progress.status = "skipped" if body.action == "skip" else "superseded"
        progress.data = {
            **progress.data,
            "reason": body.reason,
            "ended_at": ctx.request.app.state.clock(),
        }
        if body.action == "replace":
            run = learning_run(ctx.db, ctx.user, ctx.request.app.state.clock())
            replacement = create_recommendation(
                run,
                task.decision["knowledge_id"],
                task.decision["target_level"],
                task.decision["question_keys"],
            )
    return replacement
