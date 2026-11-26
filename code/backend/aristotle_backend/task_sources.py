"""Ordered learning-task references. Resolve their content against current ownership and status."""

from sqlalchemy import select

from .db import LearningResource, Material, SourceChunk


def owned_materials(user_id):
    return Material.user_id == user_id, Material.deleted.is_(False)


def confirmed_chunks(user_id):
    return (
        select(SourceChunk, Material)
        .join(Material)
        .where(*owned_materials(user_id), SourceChunk.status == "confirmed")
    )


def source_refs(db, user, knowledge_id):
    public = select(LearningResource.id).where(LearningResource.knowledge_id == knowledge_id)
    chunks = confirmed_chunks(user.id).where(SourceChunk.knowledge_id == knowledge_id)
    has_chunks = select(SourceChunk.id).where(SourceChunk.material_id == Material.id).exists()
    whole = select(Material.id).where(
        *owned_materials(user.id),
        Material.knowledge_id == knowledge_id,
        Material.confirmed.is_(True),
        ~has_chunks,
    )
    return [
        *({"type": "public", "id": key} for key in db.scalars(public)),
        *({"type": "chunk", "id": chunk.id} for chunk in db.scalars(chunks)),
        *({"type": "material", "id": key} for key in db.scalars(whole)),
    ]


def referenced_materials(user_id, ids, knowledge_id):
    chunks = confirmed_chunks(user_id).where(SourceChunk.id.in_(ids))
    whole = select(Material).where(
        *owned_materials(user_id), Material.confirmed.is_(True), Material.id.in_(ids)
    )
    if knowledge_id:
        chunks = chunks.where(SourceChunk.knowledge_id == knowledge_id)
        whole = whole.where(Material.knowledge_id == knowledge_id)
    return chunks, whole


def resolve_sources(db, user_id, refs, knowledge_id=None):
    ids = {ref["id"] for ref in refs}
    if not ids:
        return []
    chunks, whole = referenced_materials(user_id, ids, knowledge_id)
    visible = {}
    for row in db.scalars(select(LearningResource).where(LearningResource.id.in_(ids))):
        visible["public", row.id] = dict(
            title=row.title,
            text=row.text,
            location=row.source,
            implementation="demo-content",
            knowledge_id=row.knowledge_id,
        )
    for chunk, material in db.execute(chunks):
        visible["chunk", chunk.id] = dict(
            title=material.title,
            text=chunk.text,
            location=chunk.location,
            implementation=chunk.implementation,
            knowledge_id=chunk.knowledge_id,
        )
    for row in db.scalars(whole):
        visible["material", row.id] = dict(
            title=row.title,
            text=row.text,
            location="粘贴文本第 1 段",
            implementation="manual",
            knowledge_id=row.knowledge_id,
        )
    unavailable = {"unavailable": True, "reason": "来源已删除或关联已取消"}
    return [
        {"id": ref["id"], "type": ref["type"], **visible.get((ref["type"], ref["id"]), unavailable)}
        for ref in refs
    ]
