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

DEFAULT_DB = "sqlite:///" + str(Path(__file__).resolve().parents[3] / ".local" / "aristotle.db")
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
    engine, sessions = open_database(database_url or os.getenv("ARISTOTLE_DATABASE_URL", DEFAULT_DB))

    @asynccontextmanager
    async def lifespan(_):
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
    # Same-origin /demo works without CORS; Vue development ports are explicit.
    origins = os.getenv("ARISTOTLE_CORS_ORIGINS", "http://localhost:5173,http://localhost:5179").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        actor_id = getattr(request.state, "auth_user_id", None)
        if exc.status_code == 403 and actor_id:
            with request.app.state.sessions() as db:
                db.add(
                    Audit(
                        id=str(uuid4()),
                        actor_id=actor_id,
                        action="access_denied",
                        target=request.method + " " + request.url.path,
                        at=request.app.state.clock(),
                    )
                )
                db.commit()
        return JSONResponse(status_code=exc.status_code, content={"error": {"message": exc.detail}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        # Do not echo passwords, private materials or raw input back into error bodies.
        fields = [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"message": "输入校验失败", "fields": fields}})

    @app.exception_handler(IntegrityError)
    async def conflict_error(_, exc):
        return JSONResponse(
            status_code=409, content={"error": {"message": "记录已存在或版本冲突，请刷新后重试"}}
        )

    @app.get("/health", tags=["运行状态"])
    def health(db=Depends(get_db)):
        db.execute(select(1))
        return {
            "status": "ok",
            "version": "0.1.0",
            "policy_version": POLICY_VERSION,
            "external_model": "not_configured",
        }

    @app.get("/", include_in_schema=False)
    @app.get("/demo", include_in_schema=False)
    def demo():
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    @app.post("/api/v1/auth/login", response_model=LoginView, tags=["会话"])
    def login(body: Login, request: Request, db=Depends(get_db)):
        user = db.scalar(select(User).where(User.username == body.username))
        # Use an equally expensive dummy hash to reduce username timing leakage.
        password_hash = user.password_hash if user else app.state.dummy_hash
        valid = verify_password(body.password, password_hash)
        if not user or not valid:
            fail(401, "用户名或密码错误")
        token = secrets.token_urlsafe(32)
        expires = request.app.state.clock() + 8 * 60 * 60
        db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
        db.commit()
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires,
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @app.get("/api/v1/auth/me", response_model=UserView, tags=["会话"])
    def me(user=Depends(current_user)):
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.post("/api/v1/auth/logout", status_code=204, tags=["会话"])
    def logout(
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        db.delete(db.get(LoginSession, token_hash(credentials.credentials)))
        db.commit()
        return Response(status_code=204)

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

    @app.post("/api/v1/tasks", status_code=201, response_model=TaskView, tags=["学习"])
    def create_task(body: TaskInput, request: Request, user=Depends(student), db=Depends(get_db)):
        now = request.app.state.clock()
        graph, attempts, states = learning_state(db, user, now)
        if selected_scope(db, user):
            if body.mode == "diagnostic":
                fail(409, "请选择诊断流程接口创建独立诊断轮次")
            task = create_recommendation(
                db, user, graph, attempts, states, now, body.knowledge_id, body.target_level
            )
            db.commit()
            return task_view(db, task)
        published = db.scalars(select(Question).where(Question.status == "published")).all()
        # A revision is not a new independent question: assign only latest published version.
        latest = {}
        for q in published:
            if q.question_id not in latest or q.version > latest[q.question_id].version:
                latest[q.question_id] = q
        candidates = [
            {"key": q.key, "question_id": q.question_id, "knowledge_id": q.knowledge_id, "level": q.level}
            for q in latest.values()
        ]
        try:
            decision = recommend(
                graph.nodes, states, candidates, attempts, body.knowledge_id, body.target_level
            )
        except ValueError as e:
            fail(409, str(e))
        materials = db.scalars(
            select(Material).where(
                Material.user_id == user.id,
                Material.deleted.is_(False),
                Material.confirmed.is_(True),
                Material.knowledge_id == decision["knowledge_id"],
            )
        ).all()
        decision["material_ids"] = [m.id for m in materials]
        decision["status"] = (
            "ready"
            if decision["question_keys"]
            else ("material_review" if materials else "content_unavailable")
        )
        task = Task(
            id=str(uuid4()),
            user_id=user.id,
            mode=body.mode,
            graph_version=graph.version,
            decision=decision,
            evidence_snapshot=states,
            created_at=now,
        )
        db.add(task)
        db.flush()
        for i, key in enumerate(decision["question_keys"]):
            db.add(TaskQuestion(task_id=task.id, question_key=key, position=i))
        db.commit()
        return task_view(db, task)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskView, tags=["学习"])
    def get_task(task_id: str, user=Depends(student), db=Depends(get_db)):
        return task_view(db, owned(db, Task, task_id, user))

    @app.post("/api/v1/tasks/{task_id}/attempts", response_model=AttemptView, tags=["学习"])
    def submit(task_id: str, body: AttemptInput, request: Request, user=Depends(student), db=Depends(get_db)):
        task = owned(db, Task, task_id, user)
        q = db.get(Question, body.question_key)
        if not q or not db.get(TaskQuestion, (task_id, body.question_key)):
            fail(404, "题目不属于该任务")

        def existing_result():
            by_submission = db.scalar(
                select(Attempt).where(Attempt.user_id == user.id, Attempt.submission_id == body.submission_id)
            )
            by_question = db.scalar(
                select(Attempt).where(Attempt.task_id == task_id, Attempt.question_key == body.question_key)
            )
            if by_submission and (
                by_submission.task_id != task_id
                or by_submission.question_key != body.question_key
                or by_submission.selected != body.selected
            ):
                fail(409, "同一 submission_id 不能用于不同作答")
            row = by_submission or by_question
            if row and row.selected != body.selected:
                fail(409, "本任务的该题已经提交，不能覆盖首次答案")
            return row

        existing = existing_result()
        if existing:
            return {**attempt_view(existing, q, db), "replayed": True}
        assert_task_actionable(db, task)
        if q.status != "published":
            fail(409, "题目已停用，不接受新作答；请重新请求任务")
        if body.selected not in q.options:
            fail(422, "提交答案必须属于题目选项")
        row = Attempt(
            id=str(uuid4()),
            user_id=user.id,
            task_id=task_id,
            question_key=q.key,
            submission_id=body.submission_id,
            selected=body.selected,
            correct=body.selected == q.answer,
            created_at=request.app.state.clock(),
        )
        progress = db.get(TaskProgress, task.id)
        db.add(row)
        if progress:
            progress.status = "active"
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = existing_result()
            if not row:
                fail(409, "作答保存冲突，请重试")
            return {**attempt_view(row, q, db), "replayed": True}
        return {**attempt_view(row, q, db), "replayed": False}

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
        total = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == user.id))
        correct_total = db.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(Attempt.user_id == user.id, Attempt.correct.is_(True))
        )
        return {
            "items": [attempt_view(a, q, db) for a, q in rows],
            "limit": limit,
            "offset": offset,
            "total": total,
            "correct_total": correct_total,
        }

    @app.get("/api/v1/materials", tags=["个人资料"])
    def materials(user=Depends(student), db=Depends(get_db)):
        rows = db.scalars(
            select(Material).where(Material.user_id == user.id, Material.deleted.is_(False))
        ).all()
        return {"items": [material_view(m, db) for m in rows]}

    @app.post("/api/v1/materials", status_code=201, tags=["个人资料"])
    def add_material(body: MaterialInput, user=Depends(student), db=Depends(get_db)):
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        row = Material(id=str(uuid4()), user_id=user.id, **body.model_dump(), confirmed=False, deleted=False)
        db.add(row)
        db.commit()
        return material_view(row, db)

    @app.patch("/api/v1/materials/{material_id}", tags=["个人资料"])
    def update_material(material_id: str, body: MaterialUpdate, user=Depends(student), db=Depends(get_db)):
        row = owned(db, Material, material_id, user)
        if row.deleted:
            fail(404, "资源不存在")
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        row.knowledge_id, row.confirmed = body.knowledge_id, body.confirmed
        from .db import SourceChunk

        for chunk in db.scalars(select(SourceChunk).where(SourceChunk.material_id == row.id)):
            chunk.knowledge_id = body.knowledge_id
            chunk.status = "confirmed" if body.confirmed else "pending"
        db.commit()
        return material_view(row, db)

    @app.delete("/api/v1/materials/{material_id}", status_code=204, tags=["个人资料"])
    def delete_material(material_id: str, user=Depends(student), db=Depends(get_db)):
        row = owned(db, Material, material_id, user)
        purge_material_derivatives(db, row)
        row.deleted, row.confirmed, row.title, row.text = True, False, "来源已删除", ""
        db.commit()
        return Response(status_code=204)

    @app.post("/api/v1/admin/graphs", status_code=201, tags=["内容维护"])
    def publish_graph(body: GraphInput, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        nodes = [n.model_dump() for n in body.nodes]
        try:
            validate_graph(nodes)
        except ValueError as e:
            fail(422, str(e))
        ids = {n["id"] for n in nodes}
        referenced = set(db.scalars(select(Question.knowledge_id))) | set(
            db.scalars(select(Material.knowledge_id).where(Material.deleted.is_(False)))
        )
        if not referenced <= ids:
            fail(409, "不能移除已被题目或个人资料引用的知识点")
        db.add(Graph(version=body.version, nodes=nodes))
        audit(db, user, "publish_graph", body.version, request.app.state.clock())
        db.commit()
        return {"version": body.version, "nodes": nodes}

    @app.get("/api/v1/admin/questions", tags=["内容维护"])
    def list_questions(user=Depends(maintainer), db=Depends(get_db)):
        return {
            "items": [
                {**question_view(q), "answer": q.answer, "explanation": q.explanation, "source": q.source}
                for q in db.scalars(select(Question).order_by(Question.key))
            ]
        }

    @app.post("/api/v1/admin/questions", status_code=201, response_model=QuestionView, tags=["内容维护"])
    def create_question(body: QuestionInput, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        latest = db.scalar(select(func.max(Question.version)).where(Question.question_id == body.question_id))
        if latest is not None and body.version <= latest:
            fail(409, "题目修订必须使用递增的新版本")
        row = Question(key=f"{body.question_id}:v{body.version}", **body.model_dump(), status="draft")
        db.add(row)
        audit(db, user, "create_question", row.key, request.app.state.clock())
        db.commit()
        return question_view(row)

    @app.post("/api/v1/admin/questions/{question_key}/candidates", status_code=201, tags=["内容维护"])
    def add_candidate(
        question_key: str,
        body: CandidateInput,
        request: Request,
        user=Depends(maintainer),
        db=Depends(get_db),
    ):
        q = db.get(Question, question_key)
        if not q:
            fail(404, "题目不存在")
        if q.status not in ("draft", "pending_review"):
            fail(409, "已发布或停用的版本不可重新标注，请建立新题目版本")
        if (q.question_id, q.version) != (body.question_id, body.question_version):
            fail(409, "候选标签的题目版本不匹配")
        row = Annotation(
            id=str(uuid4()),
            question_key=q.key,
            payload=body.model_dump(mode="json"),
            provider="manual-prototype",
            rule_version="bloom-0.1",
            created_at=request.app.state.clock(),
        )
        db.add(row)
        q.status = "pending_review"
        audit(db, user, "add_candidate", row.id, request.app.state.clock())
        db.commit()
        return {
            "id": row.id,
            "question_key": q.key,
            "provider": row.provider,
            "rule_version": row.rule_version,
            "candidate": row.payload,
            "notice": "手动录入候选，未调用 LLM；仍须独立执行审核。",
        }

    @app.get("/api/v1/admin/candidates", tags=["内容维护"])
    def list_candidates(user=Depends(maintainer), db=Depends(get_db)):
        rows = db.execute(
            select(Annotation, Review).outerjoin(Review, Review.annotation_id == Annotation.id)
        ).all()
        return {
            "items": [
                {
                    "id": a.id,
                    "question_key": a.question_key,
                    "candidate": a.payload,
                    "provider": a.provider,
                    "rule_version": a.rule_version,
                    "created_at": a.created_at,
                    "decision": r.decision if r else "pending",
                    "needs_attention": a.payload.get("confidence", 0) < 0.8
                    or bool(a.payload.get("ambiguity_note", "").strip()),
                    "review": {
                        "reviewer_id": r.reviewer_id,
                        "reason": r.reason,
                        "final_level": r.final_level,
                        "content_verified": r.content_verified,
                        "created_at": r.created_at,
                    }
                    if r
                    else None,
                }
                for a, r in rows
            ]
        }

    @app.post("/api/v1/admin/candidates/{candidate_id}/review", tags=["内容维护"])
    def review(
        candidate_id: str, body: ReviewInput, request: Request, user=Depends(maintainer), db=Depends(get_db)
    ):
        a = db.get(Annotation, candidate_id)
        if not a:
            fail(404, "候选不存在")
        q = db.get(Question, a.question_key)
        if db.scalar(select(Review).where(Review.annotation_id == a.id)) or q.status != "pending_review":
            fail(409, "候选已审核或题目版本已锁定")
        # Compare-and-set the publication state in the same transaction as review.
        # Two concurrent approvals for different candidates cannot both become effective.
        values = (
            {"status": "published", "level": body.final_level.value}
            if body.decision == "approve"
            else {"status": "draft"}
        )
        changed = db.execute(
            update(Question)
            .where(Question.key == q.key, Question.status == "pending_review")
            .values(**values)
        )
        if changed.rowcount != 1:
            fail(409, "题目状态已变化，请刷新审核记录")
        db.add(
            Review(
                id=str(uuid4()),
                annotation_id=a.id,
                reviewer_id=user.id,
                decision=body.decision,
                reason=body.reason,
                final_level=body.final_level.value if body.final_level else None,
                content_verified=body.content_verified,
                created_at=request.app.state.clock(),
            )
        )
        audit(db, user, "review_" + body.decision, a.id, request.app.state.clock())
        db.commit()
        return {"question_key": q.key, "status": q.status, "level": q.level}

    @app.post("/api/v1/admin/questions/{question_key}/retire", tags=["内容维护"])
    def retire(question_key: str, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        q = db.get(Question, question_key)
        if not q:
            fail(404, "题目不存在")
        q.status = "retired"
        existing_reason = db.get(SystemSetting, "retired:" + q.key)
        if not existing_reason:
            db.add(
                SystemSetting(
                    key="retired:" + q.key,
                    data={
                        "reason": "维护者停用此版本；旧版接口未补充详细说明",
                        "actor": user.id,
                        "at": request.app.state.clock(),
                    },
                )
            )
        audit(db, user, "retire_question", q.key, request.app.state.clock())
        db.commit()
        return {"question_key": q.key, "status": q.status}

    @app.get("/api/v1/admin/audit", tags=["内容维护"])
    def audit_log(limit: int = Query(100, ge=1, le=200), user=Depends(current_user), db=Depends(get_db)):
        if user.role not in ("maintainer", "admin"):
            fail(403, "此操作需要维护或管理权限")
        rows = db.scalars(select(Audit).order_by(Audit.at.desc()).limit(limit)).all()
        return {
            "items": [
                {"id": a.id, "actor_id": a.actor_id, "action": a.action, "target": a.target, "at": a.at}
                for a in rows
            ]
        }

    install_flow_routes(
        app,
        get_db,
        current_user,
        student,
        maintainer,
        (learning_state, active_graph, task_view, owned, audit),
    )
    app.state.dummy_hash = hash_password("unused-" + secrets.token_urlsafe(16))
    return app
