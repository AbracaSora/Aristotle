import re
from datetime import datetime
from threading import Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from sqlalchemy import select, update

from .db import (
    Annotation,
    Attempt,
    ContentReport,
    DiagnosticRound,
    LearnerProfile,
    LearningScope,
    LoginSession,
    Material,
    Question,
    ServiceJob,
    SourceChunk,
    SystemSetting,
    Task,
    TaskProgress,
    User,
)
from .flow_schemas import (
    ChunkChoice,
    DiagnosticInput,
    ImportInput,
    ModelJobInput,
    ProviderSettings,
    ReportInput,
    ReportResolution,
    RoleChange,
    ScopeChoice,
    TaskAction,
)
from .schemas import CandidateInput, TaskInput
from .workflow import (
    assert_task_actionable,
    create_diagnostic,
    create_recommendation,
    diagnostic_view,
    finish_task,
    reject,
    selected_scope,
)


def provider_settings(db):
    row = db.get(SystemSetting, "provider")
    return row.data if row else {**ProviderSettings().model_dump(), "revision": "provider-0.1"}


def chunks_view(db, material):
    return [
        {
            "id": c.id,
            "text": c.text,
            "knowledge_id": c.knowledge_id,
            "status": c.status,
            "location": c.location,
            "implementation": c.implementation,
        }
        for c in db.scalars(select(SourceChunk).where(SourceChunk.material_id == material.id))
    ]


def purge_material_derivatives(db, material):
    for chunk in db.scalars(select(SourceChunk).where(SourceChunk.material_id == material.id)):
        chunk.text, chunk.status = "", "rejected"
    for job in db.scalars(
        select(ServiceJob).where(ServiceJob.user_id == material.user_id, ServiceJob.kind == "import")
    ):
        if job.result.get("material_id") == material.id:
            job.params, job.result = (
                {"source_deleted": True},
                {"material_id": material.id, "source_deleted": True},
            )


def job_view(job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "implementation": "mock",
        "created_at": job.created_at,
        "result": job.result,
        "notice": "这是可替换的 mock 任务，不执行真实 PDF 抽取或模型推理，不是质量/时延实测结果。",
    }


def install_flow_routes(app, get_db, current_user, student, maintainer, services):
    state_of, graph_of, task_view, owned, audit = services
    annotation_quota_lock = Lock()

    def administrator(user=Depends(current_user)):
        if user.role != "admin":
            reject(403, "此操作需要系统管理员权限")
        return user

    def content_role(user=Depends(current_user)):
        if user.role not in ("maintainer", "admin"):
            reject(403, "此操作需要维护权限")
        return user

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
        return {
            "flow_version": "learning-flow-0.2",
            "modules": {
                "identity_and_storage": "implemented",
                "scope_and_task_lifecycle": "implemented",
                "diagnosis_and_recommendation": "rule-baseline",
                "content_bank": "demo-fixtures",
                "pdf_extraction": "mock",
                "knowledge_association": "mock",
                "llm_annotation": "mock",
                "llm_explanation": "api-placeholder",
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
        tasks = db.execute(
            select(Task, TaskProgress)
            .join(TaskProgress)
            .where(Task.user_id == user.id, TaskProgress.scope_id == scope.id)
            .order_by(Task.created_at.desc(), Task.id.desc())
        ).all()
        active = next(
            (t for t, p in tasks if p.status in ("recommended", "accepted", "active") and not p.round_id),
            None,
        )
        completed = [p for _, p in tasks if p.status == "completed"]
        feedback = (
            max(completed, key=lambda p: p.data.get("completed_at", 0)).data.get("feedback")
            if completed
            else None
        )
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
        graph, attempts, states = state_of(db, user, request.app.state.clock())
        row = create_diagnostic(
            db, user, graph, attempts, states, request.app.state.clock(), body.knowledge_id, body.target_level
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
        graph, attempts, states = state_of(db, user, request.app.state.clock())
        target = old.blueprint[0] if len(old.blueprint) == 1 else {}
        row = create_diagnostic(
            db,
            user,
            graph,
            attempts,
            states,
            request.app.state.clock(),
            target.get("knowledge_id"),
            target.get("level"),
        )
        db.commit()
        return diagnostic_view(db, row)

    @app.post("/api/v1/recommendations", status_code=201, tags=["学习流程"])
    def recommendation(body: TaskInput, request: Request, user=Depends(student), db=Depends(get_db)):
        graph, attempts, states = state_of(db, user, request.app.state.clock())
        scope = selected_scope(db, user, True)
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
        if existing:
            return task_view(db, existing)
        task = create_recommendation(
            db, user, graph, attempts, states, request.app.state.clock(), body.knowledge_id, body.target_level
        )
        db.commit()
        return task_view(db, task)

    @app.post("/api/v1/tasks/{task_id}/actions", tags=["学习流程"])
    def task_action(
        task_id: str, body: TaskAction, request: Request, user=Depends(student), db=Depends(get_db)
    ):
        task = owned(db, Task, task_id, user)
        progress = db.get(TaskProgress, task.id)
        if not progress:
            reject(409, "这是旧版练习记录，请从学习计划请求新任务")
        scope = selected_scope(db, user, True)
        if progress.scope_id != scope.id:
            reject(409, "请先切回任务所属范围")
        if progress.status == "completed" and body.action == "complete":
            return {"task": task_view(db, task), "replacement": None}
        if progress.status in ("completed", "skipped", "superseded"):
            reject(409, "该任务已结束")
        if progress.round_id and body.action in ("skip", "replace"):
            reject(409, "诊断片段需要完成才能汇总；可以关闭并稍后继续")
        replacement = None
        if body.action in ("accept", "start"):
            if task.decision["status"] == "content_unavailable":
                reject(409, "内容不足，不能接受为空任务")
            progress.status = "accepted" if body.action == "accept" else "active"
            progress.data = {**progress.data, "accepted_at": request.app.state.clock()}
        elif body.action == "complete":
            assert_task_actionable(db, task)
            _, _, states = state_of(db, user, request.app.state.clock())
            finish_task(db, task, progress, request.app.state.clock(), states)
        else:
            progress.status = "skipped" if body.action == "skip" else "superseded"
            progress.data = {**progress.data, "reason": body.reason, "ended_at": request.app.state.clock()}
            if body.action == "replace":
                graph, attempts, states = state_of(db, user, request.app.state.clock())
                replacement = create_recommendation(
                    db,
                    user,
                    graph,
                    attempts,
                    states,
                    request.app.state.clock(),
                    task.decision["knowledge_id"],
                    task.decision["target_level"],
                    task.decision["question_keys"],
                )
        db.commit()
        return {
            "task": task_view(db, task),
            "replacement": task_view(db, replacement) if replacement else None,
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

    @app.post("/api/v1/material-imports", status_code=202, tags=["资料流程"])
    def create_import(body: ImportInput, request: Request, user=Depends(student), db=Depends(get_db)):
        selected_scope(db, user, True)
        if body.source_type == "text" and not body.text.strip():
            reject(422, "正文不能为空")
        job = ServiceJob(
            id=str(uuid4()),
            user_id=user.id,
            kind="import",
            status="queued",
            params=body.model_dump(),
            result={},
            created_at=request.app.state.clock(),
        )
        db.add(job)
        db.commit()
        return job_view(job)

    @app.post("/api/v1/material-imports/pdf", tags=["资料流程"])
    def real_pdf_placeholder(user=Depends(student)):
        reject(501, "真实 PDF 抽取接口已预留，当前只开放明确标记的 PDF 样例流程")

    @app.get("/api/v1/jobs", tags=["任务状态"])
    def own_jobs(user=Depends(student), db=Depends(get_db)):
        return {
            "items": [
                job_view(j)
                for j in db.scalars(
                    select(ServiceJob)
                    .where(ServiceJob.user_id == user.id, ServiceJob.kind == "import")
                    .order_by(ServiceJob.created_at.desc())
                    .limit(50)
                )
            ]
        }

    @app.get("/api/v1/jobs/{job_id}", tags=["任务状态"])
    def get_job(job_id: str, user=Depends(current_user), db=Depends(get_db)):
        return job_view(owned(db, ServiceJob, job_id, user))

    @app.post("/api/v1/jobs/{job_id}/run", tags=["任务状态"])
    def run_job(job_id: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
        job = owned(db, ServiceJob, job_id, user)
        if job.kind == "annotation" and user.role != "maintainer":
            reject(403, "标注任务需要内容维护者权限")
        if job.status != "queued":
            return job_view(job)
        changed = db.execute(
            update(ServiceJob)
            .where(ServiceJob.id == job.id, ServiceJob.status == "queued")
            .values(status="running")
        )
        if changed.rowcount != 1:
            db.rollback()
            db.refresh(job)
            return job_view(job)
        if job.kind == "import":
            scenario = job.params["scenario"]
            if scenario != "normal":
                reasons = {
                    "scanned": "扫描件未提供可抽取文本",
                    "encrypted": "文件已加密",
                    "oversize": "超过 20 MB 或 100 页限制",
                    "timeout": "样例任务模拟处理超时",
                }
                job.status, job.result = (
                    "failed",
                    {"error": reasons[scenario], "simulated": True, "retryable": scenario == "timeout"},
                )
            else:
                pdf = job.params["source_type"] == "pdf_mock"
                texts = (
                    [
                        "栈在同一端入栈和出栈，最后进入的元素最先离开。函数嵌套调用的返回过程符合后进先出。",
                        "推演操作时先记下每步栈内容。push(A)、push(B)、pop() 后只剩 A；再次入栈 C 后栈顶为 C。",
                    ]
                    if pdf
                    else [p.strip() for p in re.split(r"\n\s*\n", job.params["text"]) if p.strip()]
                )
                graph = graph_of(db)
                ids = {n["id"] for n in graph.nodes}
                default = selected_scope(db, user, True).knowledge_ids[0]
                material = Material(
                    id=str(uuid4()),
                    user_id=user.id,
                    title=job.params["title"],
                    text="\n\n".join(texts),
                    knowledge_id=default,
                    confirmed=False,
                    deleted=False,
                )
                db.add(material)
                db.flush()
                for i, text in enumerate(texts):
                    kid = "stack" if "栈" in text and "stack" in ids else default
                    db.add(
                        SourceChunk(
                            id=str(uuid4()),
                            material_id=material.id,
                            text=text,
                            knowledge_id=kid,
                            status="pending",
                            location=f"第 {i + 1} 页" if pdf else f"第 {i + 1} 段",
                            implementation="mock-pdf+mock-association" if pdf else "text+mock-association",
                        )
                    )
                job.status, job.result = (
                    "succeeded",
                    {
                        "material_id": material.id,
                        "chunk_count": len(texts),
                        "implementation": "mock-pdf" if pdf else "text-split",
                        "association": "mock",
                        "requires_confirmation": True,
                        "notice": "样例正文，不是实际上传 PDF 的解析结果"
                        if pdf
                        else "段落已保留；知识点候选来自可替换的 mock 映射",
                    },
                )
        else:
            settings = provider_settings(db)
            scenario = job.params["scenario"]
            q = db.get(Question, job.params["question_key"])
            error = None
            if settings["mode"] == "disabled":
                error = "模型服务已禁用，已发布内容的学习不受影响"
            elif not q or q.status not in ("draft", "pending_review"):
                error = "题目版本已发布或停用，不能写入候选"
            elif scenario != "normal":
                error = {
                    "timeout": "模拟超时预算到达",
                    "rate_limited": "模拟外部限流",
                    "invalid_output": "模拟模型输出不符合结构",
                    "stale_version": "模拟返回旧题版本",
                }[scenario]
            metadata = {
                "implementation": "mock",
                "model": "mock-bloom-v1",
                "prompt_version": "bloom-prompt-0.1",
                "rule_version": "bloom-0.1",
                "provider_revision": settings["revision"],
                "real_external_calls": 0,
                "quota_reserved": job.result.get("quota_reserved", 1),
                "token_usage": None,
                "simulated_budget_seconds": min(
                    settings["total_budget_seconds"], settings["timeout_seconds"] * (settings["retries"] + 1)
                ),
            }
            if error:
                job.status, job.result = (
                    "failed",
                    {**metadata, "error": error, "retryable": scenario in ("timeout", "rate_limited")},
                )
            else:
                payload = CandidateInput(
                    question_id=q.question_id,
                    question_version=q.version,
                    primary_level=job.params["suggested_level"],
                    rationale="这是样例候选理由，需审核者结合具体解题过程修改与核验。",
                    confidence=0.55,
                    ambiguity_note="mock 候选，不代表模型真实判断",
                )
                annotation = Annotation(
                    id=str(uuid4()),
                    question_key=q.key,
                    payload=payload.model_dump(mode="json"),
                    provider="mock-bloom-v1",
                    rule_version="bloom-0.1",
                    created_at=request.app.state.clock(),
                )
                db.add(annotation)
                q.status = "pending_review"
                job.status, job.result = (
                    "succeeded",
                    {**metadata, "candidate_id": annotation.id, "requires_review": True},
                )
                audit(db, user, "mock_annotation_candidate", annotation.id, request.app.state.clock())
        db.commit()
        return job_view(job)

    @app.post("/api/v1/jobs/{job_id}/retry", status_code=202, tags=["任务状态"])
    def retry_job(job_id: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
        old = owned(db, ServiceJob, job_id, user)
        if old.kind == "annotation" and user.role != "maintainer":
            reject(403, "标注任务需要内容维护者权限")
        if old.status != "failed" or not old.result.get("retryable"):
            reject(409, "该任务不能自动重试，请修正输入或人工处理")
        # Annotation retry uses the same quota reservation path as a new call.
        if old.kind == "annotation":
            return annotation_job(
                old.params["question_key"],
                ModelJobInput(**{k: old.params[k] for k in ("scenario", "suggested_level")}),
                request,
                user,
                db,
            )
        new = ServiceJob(
            id=str(uuid4()),
            user_id=user.id,
            kind=old.kind,
            status="queued",
            params=old.params,
            result={},
            created_at=request.app.state.clock(),
        )
        db.add(new)
        db.commit()
        return job_view(new)

    @app.patch("/api/v1/materials/{material_id}/chunks/{chunk_id}", tags=["资料流程"])
    def confirm_chunk(
        material_id: str, chunk_id: str, body: ChunkChoice, user=Depends(student), db=Depends(get_db)
    ):
        material = owned(db, Material, material_id, user)
        chunk = db.get(SourceChunk, chunk_id)
        if material.deleted or not chunk or chunk.material_id != material.id:
            reject(404, "片段不存在")
        if body.knowledge_id not in {n["id"] for n in graph_of(db).nodes}:
            reject(422, "知识点不存在")
        chunk.knowledge_id, chunk.status = body.knowledge_id, body.status
        db.flush()
        material.confirmed = any(c["status"] == "confirmed" for c in chunks_view(db, material))
        db.commit()
        return {"material_id": material.id, "chunks": chunks_view(db, material)}

    @app.post("/api/v1/admin/questions/{question_key}/annotation-jobs", status_code=202, tags=["内容流程"])
    def annotation_job(
        question_key: str, body: ModelJobInput, request: Request, user=Depends(maintainer), db=Depends(get_db)
    ):
        with annotation_quota_lock:
            q = db.get(Question, question_key)
            if not q or q.status not in ("draft", "pending_review"):
                reject(409, "仅草稿或待审核版本可请求标注")
            settings = provider_settings(db)
            midnight = (
                datetime.fromtimestamp(request.app.state.clock(), ZoneInfo("Asia/Shanghai"))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            used = sum(
                j.result.get("quota_reserved", 1)
                for j in db.scalars(
                    select(ServiceJob).where(
                        ServiceJob.kind == "annotation", ServiceJob.created_at >= midnight
                    )
                )
            )
            units = 1 + (settings["retries"] if body.scenario in ("timeout", "rate_limited") else 0)
            if used + units > settings["daily_annotation_limit"]:
                reject(429, "今日标注样例配额已用尽，明日按北京时间重置")
            job = ServiceJob(
                id=str(uuid4()),
                user_id=user.id,
                kind="annotation",
                status="queued",
                params={"question_key": question_key, **body.model_dump(mode="json")},
                result={"quota_reserved": units},
                created_at=request.app.state.clock(),
            )
            db.add(job)
            db.commit()
            return job_view(job)

    @app.get("/api/v1/admin/jobs", tags=["内容流程"])
    def public_jobs(user=Depends(content_role), db=Depends(get_db)):
        return {
            "items": [
                {**job_view(j), "can_run": j.user_id == user.id}
                for j in db.scalars(
                    select(ServiceJob)
                    .where(ServiceJob.kind == "annotation")
                    .order_by(ServiceJob.created_at.desc())
                    .limit(100)
                )
            ]
        }

    @app.get("/api/v1/admin/provider-settings", tags=["系统管理"])
    def get_settings(user=Depends(administrator), db=Depends(get_db)):
        return {
            "settings": provider_settings(db),
            "implementation": "mock",
            "real_provider": "api-placeholder",
        }

    @app.patch("/api/v1/admin/provider-settings", tags=["系统管理"])
    def set_settings(
        body: ProviderSettings, request: Request, user=Depends(administrator), db=Depends(get_db)
    ):
        data = {**body.model_dump(), "revision": str(uuid4())}
        row = db.get(SystemSetting, "provider")
        if row:
            row.data = data
        else:
            db.add(SystemSetting(key="provider", data=data))
        audit(db, user, "provider_config_changed", data["revision"], request.app.state.clock())
        db.commit()
        return {"settings": data, "implementation": "mock"}

    @app.post("/api/v1/admin/providers/live", tags=["系统管理"])
    def live_provider_placeholder(user=Depends(administrator)):
        reject(501, "真实模型适配器为 API 占位，当前不会接收密钥或发起外部调用")

    @app.get("/api/v1/admin/users", tags=["系统管理"])
    def users(user=Depends(administrator), db=Depends(get_db)):
        return {
            "items": [{"id": u.id, "username": u.username, "role": u.role} for u in db.scalars(select(User))]
        }

    @app.patch("/api/v1/admin/users/{user_id}/role", tags=["系统管理"])
    def change_role(
        user_id: str, body: RoleChange, request: Request, user=Depends(administrator), db=Depends(get_db)
    ):
        row = db.get(User, user_id)
        if not row:
            reject(404, "用户不存在")
        if row.id == user.id:
            reject(409, "原型中不允许修改当前管理员自身角色")
        row.role = body.role
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id == row.id)):
            db.delete(session)
        audit(db, user, "role_changed", row.id + ":" + body.role, request.app.state.clock())
        db.commit()
        return {"id": row.id, "role": row.role, "sessions_revoked": True}

    @app.post("/api/v1/content-reports", status_code=201, tags=["内容纠错"])
    def report(body: ReportInput, request: Request, user=Depends(student), db=Depends(get_db)):
        if not db.scalar(
            select(Attempt.id)
            .where(Attempt.user_id == user.id, Attempt.question_key == body.question_key)
            .limit(1)
        ):
            reject(404, "只能报告自己已作答的题目版本")
        row = ContentReport(
            id=str(uuid4()),
            user_id=user.id,
            **body.model_dump(),
            status="open",
            resolution="",
            created_at=request.app.state.clock(),
        )
        db.add(row)
        db.commit()
        return {"id": row.id, "status": row.status}

    def report_view(r):
        return {
            "id": r.id,
            "question_key": r.question_key,
            "category": r.category,
            "message": r.message,
            "status": r.status,
            "resolution": r.resolution,
            "created_at": r.created_at,
        }

    @app.get("/api/v1/content-reports", tags=["内容纠错"])
    def own_reports(user=Depends(student), db=Depends(get_db)):
        return {
            "items": [
                report_view(r)
                for r in db.scalars(select(ContentReport).where(ContentReport.user_id == user.id))
            ]
        }

    @app.get("/api/v1/admin/content-reports", tags=["内容纠错"])
    def content_reports(user=Depends(maintainer), db=Depends(get_db)):
        return {
            "items": [
                report_view(r)
                for r in db.scalars(select(ContentReport).order_by(ContentReport.created_at.desc()))
            ]
        }

    @app.post("/api/v1/admin/content-reports/{report_id}/resolve", tags=["内容纠错"])
    def resolve_report(
        report_id: str, body: ReportResolution, request: Request, user=Depends(maintainer), db=Depends(get_db)
    ):
        row = db.get(ContentReport, report_id)
        if not row:
            reject(404, "报告不存在")
        if row.status != "open":
            reject(409, "报告已处理")
        if body.action == "retire":
            db.get(Question, row.question_key).status = "retired"
            old = db.get(SystemSetting, "retired:" + row.question_key)
            data = {"reason": body.reason, "actor": user.id, "at": request.app.state.clock()}
            if old:
                old.data = data
            else:
                db.add(SystemSetting(key="retired:" + row.question_key, data=data))
        row.status, row.resolution = body.action, body.reason
        audit(db, user, "resolve_content_report", row.id, request.app.state.clock())
        db.commit()
        return report_view(row)
