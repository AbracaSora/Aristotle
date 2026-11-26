import base64
from uuid import uuid4

from fastapi import Depends, File, Form, Request, UploadFile
from sqlalchemy import select, update

from .api_access import RequestSession, student_session
from .db import (
    Annotation,
    Material,
    Question,
    ServiceJob,
    SourceChunk,
)
from .flow_schemas import (
    ChunkChoice,
    ImportInput,
    ModelJobInput,
)
from .flow_support import chunks_view, job_view, provider_settings
from .import_jobs import enqueue_context, run_import
from .material_imports import MAX_PDF_BYTES
from .schemas import CandidateInput
from .workflow import (
    reject,
    selected_scope,
)


def install(app, dependencies, services):
    get_db = dependencies.get_db
    current_user = dependencies.current_user
    student = dependencies.student
    state_of, graph_of, task_view, owned, audit_record = services

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
            params={**body.model_dump(), **enqueue_context(db, user)},
            result={"implementation": "mock" if body.source_type == "pdf_mock" else "text-split"},
            created_at=request.app.state.clock(),
        )
        db.add(job)
        db.commit()
        return job_view(job)

    @app.post("/api/v1/material-imports/pdf", status_code=202, tags=["资料流程"])
    async def import_pdf(
        file: UploadFile = File(...),
        title: str = Form("PDF 资料", min_length=1, max_length=80),
        ctx=Depends(student_session),
    ):
        selected_scope(ctx.db, ctx.user, True)
        try:
            data = await file.read(MAX_PDF_BYTES + 1)
        finally:
            await file.close()
        if len(data) > MAX_PDF_BYTES:
            reject(413, "PDF 超过 20 MB 限制")
        if not data.startswith(b"%PDF-"):
            reject(422, "文件不是有效 PDF")
        job = ServiceJob(
            id=str(uuid4()),
            user_id=ctx.user.id,
            kind="import",
            status="queued",
            params={
                **enqueue_context(ctx.db, ctx.user),
                "source_type": "pdf",
                "title": title,
                "pdf_base64": base64.b64encode(data).decode("ascii"),
                "scenario": "normal",
            },
            result={"implementation": "pypdf-text"},
            created_at=ctx.request.app.state.clock(),
        )
        ctx.db.add(job)
        ctx.db.commit()
        return job_view(job)

    @app.get("/api/v1/jobs", tags=["任务状态"])
    def own_jobs(user=Depends(student), db=Depends(get_db)):
        return {
            "items": [
                job_view(j)
                for j in db.scalars(
                    select(ServiceJob)
                    .where(
                        ServiceJob.user_id == user.id,
                        ServiceJob.kind.in_(("import", "live_index", "live_explanation")),
                    )
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
        if job.kind.startswith("live_"):
            reject(409, "真实模型任务由 worker 或 model-jobs dispatch 处理，不能作为 mock 运行")
        if job.kind == "annotation" and user.role != "maintainer":
            reject(403, "标注任务需要内容维护者权限")
        if job.kind == "import":
            run_import(request.app.state.sessions, job.id, include_mock=True)
            db.expire_all()
            return job_view(owned(db, ServiceJob, job_id, user))
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
        db.commit()
        return complete_mock_job(RequestSession(request, user, db), job, audit_record)

    @app.post("/api/v1/jobs/{job_id}/retry", status_code=202, tags=["任务状态"])
    def retry_job(job_id: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
        old = owned(db, ServiceJob, job_id, user)
        if old.kind.startswith("live_"):
            reject(409, "请通过 model-jobs retry 显式重试真实模型任务")
        if old.kind == "annotation" and user.role != "maintainer":
            reject(403, "标注任务需要内容维护者权限")
        if old.status != "failed" or not old.result.get("retryable"):
            reject(409, "该任务不能自动重试，请修正输入或人工处理")
        # Annotation retry uses the same quota reservation path as a new call.
        if old.kind == "annotation":
            return dependencies.annotation_job(
                old.params["question_key"],
                ModelJobInput(**{k: old.params[k] for k in ("scenario", "suggested_level")}),
                RequestSession(request, user, db),
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
    def confirm_chunk(material_id: str, chunk_id: str, body: ChunkChoice, ctx=Depends(student_session)):
        from .retrieval import invalidate_material_index

        material = ctx.db.scalar(
            select(Material)
            .where(Material.id == material_id, Material.user_id == ctx.user.id)
            .with_for_update()
        )
        if not material:
            reject(404, "资料不存在")
        chunk = ctx.db.get(SourceChunk, chunk_id)
        if material.deleted or not chunk or chunk.material_id != material.id:
            reject(404, "片段不存在")
        if body.knowledge_id not in {n["id"] for n in graph_of(ctx.db).nodes}:
            reject(422, "知识点不存在")
        chunk.knowledge_id, chunk.status = body.knowledge_id, body.status
        invalidate_material_index(ctx.db, material.id)
        ctx.db.flush()
        material.confirmed = any(c["status"] == "confirmed" for c in chunks_view(ctx.db, material))
        ctx.db.commit()
        return {"material_id": material.id, "chunks": chunks_view(ctx.db, material)}


def mock_annotation_error(q, settings, scenario):
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
    return error


def mock_metadata(settings, job):
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
    return metadata


def store_mock_candidate(db, job, q, request):
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
    return annotation


def complete_mock_job(ctx, job, audit_record):
    request, user, db = ctx.request, ctx.user, ctx.db
    settings = provider_settings(db)
    scenario = job.params["scenario"]
    q = db.get(Question, job.params["question_key"])
    error = mock_annotation_error(q, settings, scenario)
    metadata = mock_metadata(settings, job)
    if error:
        job.status, job.result = (
            "failed",
            {**metadata, "error": error, "retryable": scenario in ("timeout", "rate_limited")},
        )
    else:
        annotation = store_mock_candidate(db, job, q, request)
        job.status, job.result = (
            "succeeded",
            {**metadata, "candidate_id": annotation.id, "requires_review": True},
        )
        db.add(audit_record(user, "mock_annotation_candidate", annotation.id, request.app.state.clock()))
    db.commit()
    return job_view(job)
