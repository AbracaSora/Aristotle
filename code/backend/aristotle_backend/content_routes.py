from datetime import datetime
from threading import Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from sqlalchemy import select

from .api_access import maintainer_session
from .db import (
    Attempt,
    ContentReport,
    Question,
    ServiceJob,
    SystemSetting,
)
from .flow_schemas import (
    ModelJobInput,
    ReportInput,
    ReportResolution,
)
from .flow_support import job_view, provider_settings
from .workflow import (
    reject,
)


def install(app, dependencies, services):
    get_db = dependencies.get_db
    student = dependencies.student
    maintainer = dependencies.maintainer
    content_role = dependencies.content_role
    state_of, graph_of, task_view, owned, audit_record = services
    annotation_quota_lock = Lock()

    @app.post("/api/v1/admin/questions/{question_key}/annotation-jobs", status_code=202, tags=["内容流程"])
    def annotation_job(question_key: str, body: ModelJobInput, ctx=Depends(maintainer_session)):
        with annotation_quota_lock:
            q = ctx.db.get(Question, question_key)
            if not q or q.status not in ("draft", "pending_review"):
                reject(409, "仅草稿或待审核版本可请求标注")
            settings = provider_settings(ctx.db)
            midnight = (
                datetime.fromtimestamp(ctx.request.app.state.clock(), ZoneInfo("Asia/Shanghai"))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            used = sum(
                j.result.get("quota_reserved", 1)
                for j in ctx.db.scalars(
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
                user_id=ctx.user.id,
                kind="annotation",
                status="queued",
                params={"question_key": question_key, **body.model_dump(mode="json")},
                result={"quota_reserved": units},
                created_at=ctx.request.app.state.clock(),
            )
            ctx.db.add(job)
            ctx.db.commit()
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
    def resolve_report(report_id: str, body: ReportResolution, ctx=Depends(maintainer_session)):
        row = ctx.db.get(ContentReport, report_id)
        if not row:
            reject(404, "报告不存在")
        if row.status != "open":
            reject(409, "报告已处理")
        if body.action == "retire":
            ctx.db.get(Question, row.question_key).status = "retired"
            old = ctx.db.get(SystemSetting, "retired:" + row.question_key)
            data = {"reason": body.reason, "actor": ctx.user.id, "at": ctx.request.app.state.clock()}
            if old:
                old.data = data
            else:
                ctx.db.add(SystemSetting(key="retired:" + row.question_key, data=data))
        row.status, row.resolution = body.action, body.reason
        ctx.db.add(audit_record(ctx.user, "resolve_content_report", row.id, ctx.request.app.state.clock()))
        ctx.db.commit()
        return report_view(row)

    return annotation_job
