"""Map, authorized retrieval, source consent and explicitly invoked model assistance."""

import os
import time
from typing import Annotated, Literal
from uuid import uuid4

from aristotle_core.policy import diagnose
from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select

from .db import Attempt, Audit, Material, ModelCall, Question, ServiceJob
from .model_jobs import REAL_JOBS, _question_content, create_job, ensure_enabled, run_job
from .providers import ProviderFailure, fingerprint, provider_config
from .retrieval import invalidate_material_index, keyword_search, semantic_search, source_units
from .schemas import Identifier, Input


class SearchInput(Input):
    query: str = Field(default="", max_length=500)
    knowledge_id: Identifier | None = None
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword"
    allow_external_query: bool = False
    limit: int = Field(default=6, ge=1, le=12)


class IndexInput(Input):
    knowledge_id: Identifier | None = None
    allow_external: bool = False


class ConsentInput(Input):
    allowed: bool


class ExplainInput(Input):
    knowledge_id: Identifier
    query: str = Field(default="请解释这个知识点的核心规则与常见误区。", min_length=1, max_length=500)
    source_keys: list[Annotated[str, Field(max_length=200)]] = Field(min_length=1, max_length=6)
    allow_external: bool = False
    attempt_id: str | None = Field(default=None, max_length=80)


def install_assistance_routes(app, get_db, current_user, student, maintainer, services):
    state_of, graph_of, _, owned, _ = services

    @app.exception_handler(ProviderFailure)
    async def provider_error(request, exc):
        status = {
            "not_configured": 503,
            "quota_exceeded": 429,
            "consent_required": 403,
            "source_unavailable": 409,
            "disabled": 503,
            "scope_too_large": 413,
        }.get(exc.code, 502)
        return JSONResponse(status_code=status, content={"error": {"message": str(exc), "code": exc.code}})

    def check_knowledge(db, knowledge_id):
        if knowledge_id and knowledge_id not in {n["id"] for n in graph_of(db).nodes}:
            raise HTTPException(422, "知识点不存在")

    def dispatch(background, request, job):
        if os.getenv("ARISTOTLE_INLINE_WORKER", "1") == "1":
            background.add_task(
                run_job,
                request.app.state.sessions,
                job.id,
                getattr(request.app.state, "model_transport", None),
            )

    def view(job):
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "implementation": "openai-compatible",
            "result": job.result,
            "created_at": job.created_at,
            "notice": "模型任务仅提供资料索引、候选或辅助解释；不会自动发布或改变学习证据。",
        }

    @app.get("/api/v1/knowledge-map", tags=["知识地图"])
    def knowledge_map(request: Request, user=Depends(student), db=Depends(get_db)):
        graph, attempts, _ = state_of(db, user, request.app.state.clock())
        states = diagnose(graph.nodes, attempts, request.app.state.clock())
        return {
            "version": graph.version,
            "nodes": graph.nodes,
            "states": states,
            "window_days": 14,
            "edges": [
                {"source": p, "target": n["id"], "kind": "prerequisite"}
                for n in graph.nodes
                for p in n["prerequisites"]
            ],
            "notice": "显示已发布先修关系与作答证据；语义相似不会生成先修边。",
        }

    @app.get("/api/v1/model-status", tags=["模型服务"])
    def model_status(user=Depends(current_user), db=Depends(get_db)):
        result = {}
        for kind in ("generation", "embedding"):
            try:
                cfg = provider_config(kind)
                result[kind] = {
                    "configured": cfg.configured,
                    "model": cfg.model,
                    "namespace": cfg.namespace if cfg.configured else None,
                }
            except ProviderFailure:
                result[kind] = {"configured": False, "error": "后端配置无效"}
        try:
            ensure_enabled(db)
            result["enabled"] = True
        except ProviderFailure:
            result["enabled"] = False
        result["storage"] = "pgvector" if db.bind.dialect.name == "postgresql" else "sqlite-test-only"
        return result

    @app.get("/api/v1/retrieval/sources", tags=["资料检索"])
    def sources(knowledge_id: str | None = Query(default=None), user=Depends(student), db=Depends(get_db)):
        check_knowledge(db, knowledge_id)
        units = source_units(db, user.id, knowledge_id)
        return {"items": keyword_search(units, "", 12), "total": len(units), "mode": "linked-sources"}

    @app.post("/api/v1/retrieval/search", tags=["资料检索"])
    def search(body: SearchInput, request: Request, user=Depends(student), db=Depends(get_db)):
        check_knowledge(db, body.knowledge_id)
        if body.mode != "keyword":
            if not body.query.strip():
                raise HTTPException(422, "请输入语义查询内容")
            ensure_enabled(db)
        return semantic_search(
            db,
            user.id,
            body.query,
            body.knowledge_id,
            body.mode,
            body.allow_external_query,
            body.limit,
            getattr(request.app.state, "model_transport", None),
        )

    @app.post("/api/v1/retrieval/index", status_code=202, tags=["资料检索"])
    def index(
        body: IndexInput,
        request: Request,
        background: BackgroundTasks,
        user=Depends(student),
        db=Depends(get_db),
    ):
        check_knowledge(db, body.knowledge_id)
        if not body.allow_external:
            raise ProviderFailure(
                "consent_required", "建立向量索引需要发送公共资料及已明确授权的私人片段，请先确认。"
            )
        job = create_job(db, user, "live_index", {"knowledge_id": body.knowledge_id})
        result = view(job)
        dispatch(background, request, job)
        return result

    @app.patch("/api/v1/materials/{material_id}/external-consent", tags=["资料权限"])
    def consent(material_id: str, body: ConsentInput, user=Depends(student), db=Depends(get_db)):
        material = db.scalar(
            select(Material).where(Material.id == material_id, Material.user_id == user.id).with_for_update()
        )
        if not material or material.deleted:
            raise HTTPException(404, "资料不存在")
        material.external_processing_allowed = body.allowed
        if not body.allowed:
            invalidate_material_index(db, material.id)
        db.add(
            Audit(
                id=str(uuid4()),
                actor_id=user.id,
                action="allow_material_model_processing"
                if body.allowed
                else "revoke_material_model_processing",
                target=material.id,
                at=time.time(),
            )
        )
        db.commit()
        return {"id": material.id, "external_processing_allowed": material.external_processing_allowed}

    @app.post("/api/v1/explanations", status_code=202, tags=["辅助解释"])
    def explanation(
        body: ExplainInput,
        request: Request,
        background: BackgroundTasks,
        user=Depends(student),
        db=Depends(get_db),
    ):
        check_knowledge(db, body.knowledge_id)
        if not body.allow_external:
            raise ProviderFailure("consent_required", "请明确允许将本次问题和选定来源发送给生成模型。")
        units = {u.key: u for u in source_units(db, user.id, body.knowledge_id)}
        if len(set(body.source_keys)) != len(body.source_keys) or any(
            key not in units or not units[key].external_allowed for key in body.source_keys
        ):
            raise ProviderFailure(
                "source_unavailable", "部分来源未确认、已删除或未授权模型处理，请重新选择。"
            )
        if body.attempt_id:
            attempt = owned(db, Attempt, body.attempt_id, user)
            question = db.get(Question, attempt.question_key)
            if not question or question.knowledge_id != body.knowledge_id:
                raise HTTPException(409, "作答记录与知识点不匹配")
        params = {
            **body.model_dump(exclude={"allow_external"}),
            "material_ids": sorted(
                {units[key].material_id for key in body.source_keys if units[key].material_id}
            ),
        }
        job = create_job(db, user, "live_explanation", params)
        result = view(job)
        dispatch(background, request, job)
        return result

    @app.post("/api/v1/admin/questions/{question_key}/model-annotations", status_code=202, tags=["模型标注"])
    def annotate(
        question_key: str,
        request: Request,
        background: BackgroundTasks,
        user=Depends(maintainer),
        db=Depends(get_db),
    ):
        question = db.get(Question, question_key)
        if not question or question.status not in ("draft", "pending_review"):
            raise HTTPException(409, "只能对草稿或待审核版本提出模型候选")
        job = create_job(
            db,
            user,
            "live_annotation",
            {"question_key": question_key, "content_hash": fingerprint(_question_content(question))},
        )
        result = view(job)
        dispatch(background, request, job)
        return result

    @app.post("/api/v1/model-jobs/{job_id}/dispatch", status_code=202, tags=["模型服务"])
    def dispatch_queued(
        job_id: str,
        request: Request,
        background: BackgroundTasks,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        job = owned(db, ServiceJob, job_id, user)
        if job.kind not in REAL_JOBS or job.status != "queued":
            raise HTTPException(409, "任务不是待处理的真实模型任务")
        result = view(job)
        background.add_task(
            run_job, request.app.state.sessions, job.id, getattr(request.app.state, "model_transport", None)
        )
        return result

    @app.get("/api/v1/admin/model-calls", tags=["模型服务"])
    def calls(user=Depends(current_user), db=Depends(get_db)):
        if user.role != "admin":
            raise HTTPException(403, "需要管理员权限")
        return {
            "items": [
                {
                    "id": r.id,
                    "purpose": r.purpose,
                    "model": r.model,
                    "status": r.status,
                    "reserved_requests": r.reserved_requests,
                    "external_calls": r.external_calls,
                    "usage": r.usage,
                    "error_code": r.error_code,
                    "duration_seconds": r.duration_seconds,
                    "created_at": r.created_at,
                }
                for r in db.scalars(select(ModelCall).order_by(ModelCall.created_at.desc()).limit(100))
            ]
        }

    @app.post("/api/v1/model-jobs/{job_id}/retry", status_code=202, tags=["模型服务"])
    def retry(
        job_id: str,
        request: Request,
        background: BackgroundTasks,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        previous = owned(db, ServiceJob, job_id, user)
        if (
            previous.kind not in REAL_JOBS
            or previous.status != "failed"
            or not previous.result.get("retryable")
        ):
            raise HTTPException(409, "此任务不能直接重试，请修正输入或配置后建立新任务")
        params = {
            key: value
            for key, value in previous.params.items()
            if key not in ("provider_namespace", "prompt_version", "request_fingerprint")
        }
        job = create_job(db, user, previous.kind, params)
        result = view(job)
        dispatch(background, request, job)
        return result
