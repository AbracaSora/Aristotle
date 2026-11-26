from sqlalchemy import select

from .db import (
    ServiceJob,
    SourceChunk,
    SystemSetting,
)
from .flow_schemas import (
    ProviderSettings,
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


def erase_material(db, material):
    purge_material_derivatives(db, material)
    material.deleted, material.confirmed, material.title, material.text = True, False, "来源已删除", ""
    material.external_processing_allowed = False


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
        else (
            "真实文本导入，候选关联需本人确认。"
            if job.kind == "import" and job.params.get("source_type") != "pdf_mock"
            else "这是明确标记的模拟任务，不是模型质量或时延实测结果。"
        ),
    }
