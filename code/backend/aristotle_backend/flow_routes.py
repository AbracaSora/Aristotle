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
    from .retrieval import invalidate_material_index

    invalidate_material_index(db, material.id)
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
        "implementation": job.result.get("implementation", "mock"),
        "created_at": job.created_at,
        "result": job.result,
        "knowledge_id": job.params.get("knowledge_id"),
        "attempt_id": job.params.get("attempt_id"),
        "notice": "真实模型任务，不自动发布或改变学习证据。"
        if job.kind.startswith("live_")
        else "这是可替换的 mock 任务，不执行真实 PDF 抽取或模型推理，不是质量/时延实测结果。",
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

    from types import SimpleNamespace
    from . import learning_routes, material_routes
    from .api_access import RequestSession
    from .api_views import audit_record
    deps = SimpleNamespace(get_db=get_db, current_user=current_user, student=student)
    route_services = (*services[:4], audit_record)
    learning_routes.install(app, deps, route_services)

    def retry_annotation(key, body, ctx):
        return annotation_job(key, body, ctx.request, ctx.user, ctx.db)
    deps.annotation_job = retry_annotation
    material_routes.install(app, deps, route_services)

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
                    .where(ServiceJob.kind.in_(("annotation", "live_annotation")))
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
    def live_provider_status(user=Depends(administrator)):
        from .providers import provider_config

        cfg = provider_config("generation")
        if not cfg.configured:
            reject(501, "真实模型尚未配置，请在后端环境变量中填写地址、模型名和密钥")
        return {
            "implementation": "openai-compatible",
            "model": cfg.model,
            "configured": True,
            "notice": "配置已就绪；此接口不发起付费调用，标注需显式建立任务。",
        }

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
