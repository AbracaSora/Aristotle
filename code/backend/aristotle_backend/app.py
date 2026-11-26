import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from aristotle_core.policy import POLICY_VERSION, diagnose, recommend, validate_graph
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .assistance_routes import install_assistance_routes
from .config import database_url as configured_database_url
from .db import (
    Annotation,
    Attempt,
    Audit,
    Graph,
    LoginSession,
    Material,
    Question,
    Review,
    SystemSetting,
    Task,
    TaskProgress,
    TaskQuestion,
    User,
    open_database,
)
from .flow_routes import chunks_view, install_flow_routes, purge_material_derivatives
from .schemas import (
    AttemptInput,
    AttemptView,
    CandidateInput,
    ErrorView,
    GraphInput,
    HistoryView,
    LearningStateView,
    Login,
    LoginView,
    MaterialInput,
    MaterialUpdate,
    QuestionInput,
    QuestionView,
    ReviewInput,
    TaskInput,
    TaskView,
    UserView,
)
from .security import hash_password, token_hash, verify_password
from .workflow import (
    assert_task_actionable,
    create_recommendation,
    flow_view,
    round_evidence,
    scoped_nodes,
    selected_scope,
)

bearer = HTTPBearer(auto_error=False)


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


def get_db(request: Request):
    with request.app.state.sessions() as session:
        yield session


def current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)
):
    if not credentials or credentials.scheme.lower() != "bearer":
        fail(401, "请先登录")
    session = db.get(LoginSession, token_hash(credentials.credentials))
    if not session or session.expires_at <= request.app.state.clock():
        fail(401, "会话无效或已过期，请重新登录")
    user = db.get(User, session.user_id)
    request.state.auth_user_id = user.id
    return user


def maintainer(user=Depends(current_user)):
    if user.role != "maintainer":
        fail(403, "此操作需要内容维护者权限")
    return user


def student(user=Depends(current_user)):
    if user.role != "student":
        fail(403, "请使用学生账号执行学习操作")
    return user


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


def audit(db, user, action, target, now):
    db.add(Audit(id=str(uuid4()), actor_id=user.id, action=action, target=target, at=now))


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
    materials = []
    for key in task.decision.get("material_ids", []):
        m = db.get(Material, key)
        if (
            m
            and m.user_id == task.user_id
            and not m.deleted
            and m.confirmed
            and m.knowledge_id == task.decision["knowledge_id"]
        ):
            materials.append(material_view(m))
        else:
            materials.append({"id": key, "unavailable": True, "reason": "来源已删除或关联已取消/变更"})
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


def create_app(database_url: str | None = None):
    engine, sessions = open_database(configured_database_url(database_url))

    @asynccontextmanager
    async def lifespan(_):
        from .model_jobs import expire_running

        expire_running(sessions)
        yield
        engine.dispose()

    app = FastAPI(
        title="Aristotle 408 后端原型",
        version="0.1.0",
        lifespan=lifespan,
        responses={code: {"model": ErrorView} for code in (401, 403, 404, 409, 422, 503)},
        description="规则学习流程、账号隔离、内容审核和持久化。真实 LLM/PDF 尚未接入。",
    )
    app.state.sessions, app.state.engine, app.state.clock = sessions, engine, time.time
    from .migrations import schema_head

    app.state.schema_revision = schema_head()
    # Same-origin /demo works without CORS; Vue development ports are explicit.
    origins = os.getenv("ARISTOTLE_CORS_ORIGINS", "http://localhost:5173,http://localhost:5179").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    from .session_routes import install_session_routes
    install_session_routes(app)

    from .task_routes import install_task_routes
    install_task_routes(app)

    from .legacy_content_routes import install_legacy_content_routes
    install_legacy_content_routes(app)

    install_flow_routes(
        app,
        get_db,
        current_user,
        student,
        maintainer,
        (learning_state, active_graph, task_view, owned, audit),
    )
    install_assistance_routes(
        app,
        get_db,
        current_user,
        student,
        maintainer,
        (learning_state, active_graph, task_view, owned, audit),
    )
    app.state.dummy_hash = hash_password("unused-" + secrets.token_urlsafe(16))
    return app
