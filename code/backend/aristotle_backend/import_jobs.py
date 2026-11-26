"""Durable material imports shared by the API and standalone worker."""

import logging
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.sql.functions import coalesce

from .curriculum import lock_user
from .db import Graph, LearningScope, ServiceJob, User
from .material_imports import import_segments, persist_import
from .workflow import selected_scope

logger = logging.getLogger(__name__)
RUNNING_TTL = 60
QUEUED_TTL = 24 * 60 * 60


class ImportFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def enqueue_context(db, user):
    scope = selected_scope(db, user, True)
    graph = db.scalar(select(Graph).order_by(Graph.sequence.desc()).limit(1))
    if not graph or not scope.knowledge_ids:
        raise HTTPException(409, "学习范围或知识结构不可用")
    return {"scope_id": scope.id, "knowledge_ids": scope.knowledge_ids, "graph_version": graph.version}


def claim_import(sessions, job_id, include_mock):
    with sessions() as db:
        query = select(ServiceJob).where(ServiceJob.kind == "import", ServiceJob.status == "queued")
        if job_id:
            query = query.where(ServiceJob.id == job_id)
        if not include_mock:
            query = query.where(ServiceJob.params["source_type"].as_string().in_(("pdf", "text")))
        job = db.scalar(query.order_by(ServiceJob.created_at).with_for_update(skip_locked=True).limit(1))
        if not job:
            return None
        token = str(uuid4())
        changed = db.execute(
            update(ServiceJob)
            .where(ServiceJob.id == job.id, ServiceJob.status == "queued")
            .values(
                status="running",
                result={
                    "claim_id": token,
                    "started_at": time.time(),
                    "implementation": "pypdf-text" if job.params["source_type"] == "pdf" else "text-split",
                },
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return job.id, token


def prepare_import(db, job):
    user = db.get(User, job.user_id)
    if not user or user.role != "student":
        raise ImportFailure("role_changed", "账号权限已改变，未导入资料")
    params = job.params
    if "graph_version" not in params:
        params = {**params, **enqueue_context(db, user)}
    return resolve_import_scope(db, params)


def resolve_import_scope(db, params):
    scope = db.get(LearningScope, params["scope_id"])
    graph = db.scalar(select(Graph).where(Graph.version == params["graph_version"]))
    if not scope or not scope.published or not graph:
        raise ImportFailure("scope_unavailable", "原学习范围或知识结构已不可用，请重新上传")
    nodes = [node for node in graph.nodes if node["id"] in params["knowledge_ids"]]
    if not nodes or params["knowledge_ids"][0] not in {node["id"] for node in nodes}:
        raise ImportFailure("scope_unavailable", "原学习范围没有有效知识点")
    return dict(params), nodes, params["knowledge_ids"][0]


def check_scenario(params):
    scenario = params.get("scenario", "normal")
    if scenario == "normal":
        return
    messages = {
        "scanned": "扫描件未提供可抽取文本",
        "encrypted": "文件已加密",
        "oversize": "超过20 MB或100页限制",
        "timeout": "样例任务模拟处理超时",
    }
    raise ImportFailure("simulated_" + scenario, messages[scenario])


def clear_pdf(job):
    if "pdf_base64" in job.params:
        job.params = {key: value for key, value in job.params.items() if key != "pdf_base64"}


def record_failure(sessions, claim, error):
    code = error.code if isinstance(error, ImportFailure) else "internal_error"
    message, status = "资料导入失败，请检查后重新上传", 500
    if isinstance(error, HTTPException):
        status, message = error.status_code, str(error.detail)
        code = "timeout" if status == 408 else "invalid_pdf"
    elif isinstance(error, ImportFailure):
        message = str(error)
    logger.warning("material_import_failed job_id=%s error_code=%s", claim[0], code)
    with sessions() as db:
        job = db.scalar(select(ServiceJob).where(ServiceJob.id == claim[0]).with_for_update())
        if job.status != "running" or job.result.get("claim_id") != claim[1]:
            return
        simulated = (
            job.params.get("source_type") == "pdf_mock" or job.params.get("scenario", "normal") != "normal"
        )
        job.status, job.result = (
            "failed",
            {
                "error_code": code,
                "error": message,
                "status_code": status,
                "retryable": simulated and code == "simulated_timeout",
                "simulated": simulated,
                "implementation": "mock" if simulated else job.result.get("implementation", "text-split"),
            },
        )
        clear_pdf(job)
        db.commit()


def finish_import(sessions, claim, work, parsed):
    with sessions() as db:
        job = db.get(ServiceJob, claim[0])
        lock_user(db, job.user_id)
        db.refresh(job)
        if job.status != "running" or job.result.get("claim_id") != claim[1]:
            return None
        prepare_import(db, job)  # Re-check role/scope after extraction, before writing material.
        persist_import(db, job, (work[1], work[2]), parsed)
        clear_pdf(job)
        db.commit()
        return {"id": job.id, "status": job.status}


def run_import(sessions, job_id=None, *, include_mock=False):
    claim = claim_import(sessions, job_id, include_mock)
    if claim is None:
        return None
    try:
        with sessions() as db:
            work = prepare_import(db, db.get(ServiceJob, claim[0]))
        check_scenario(work[0])
        parsed = import_segments(work[0])
        return finish_import(sessions, claim, work, parsed)
    except Exception as exc:
        # Worker boundary: errors are durable and visible; raw PDF/provider text is never logged.
        record_failure(sessions, claim, exc)
        return {"id": claim[0], "status": "failed"}


def expire_imports(sessions, now=None):
    now = time.time() if now is None else now
    with sessions() as db:
        started = coalesce(ServiceJob.result["started_at"].as_float(), ServiceJob.created_at)
        overdue = or_(
            and_(ServiceJob.status == "running", started < now - RUNNING_TTL),
            and_(ServiceJob.status == "queued", ServiceJob.created_at < now - QUEUED_TTL),
        )
        query = (
            select(ServiceJob)
            .where(ServiceJob.kind == "import", overdue)
            .order_by(ServiceJob.created_at)
            .limit(100)
        )
        expired = 0
        for job in db.scalars(query.with_for_update(skip_locked=True)):
            code = "interrupted" if job.status == "running" else "expired"
            job.status, job.result = (
                "failed",
                {
                    "error_code": code,
                    "error": "任务中断或过期，请重新上传",
                    "retryable": False,
                    "implementation": "pypdf-text"
                    if job.params.get("source_type") == "pdf"
                    else "text-split",
                },
            )
            clear_pdf(job)
            expired += 1
        db.commit()
        return expired
