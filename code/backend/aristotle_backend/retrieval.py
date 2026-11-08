"""Authorized source segments and real pgvector cosine search; keyword mode stays explicit."""

import math
import re
import time
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Float, bindparam, cast, delete, or_, select

from .db import LearningResource, Material, SourceChunk, SourceEmbedding
from .providers import ProviderFailure, embed, fingerprint, provider_config
from .vector_type import Vector


@dataclass(frozen=True)
class SourceUnit:
    key: str
    title: str
    text: str
    location: str
    knowledge_id: str
    resource_id: str | None = None
    material_id: str | None = None
    chunk_id: str | None = None
    owner_id: str | None = None
    external_allowed: bool = True

    @property
    def content_hash(self):
        return fingerprint([self.text, self.location, self.knowledge_id, self.title])

    def view(self):
        return {
            "id": self.key,
            "title": self.title,
            "text": self.text,
            "location": self.location,
            "knowledge_id": self.knowledge_id,
            "source_type": "personal" if self.material_id else "public",
            "material_id": self.material_id,
            "external_processing_allowed": self.external_allowed,
        }


def source_units(db, user_id, knowledge_id=None, lock=False):
    sources = []
    public = select(LearningResource)
    if knowledge_id:
        public = public.where(LearningResource.knowledge_id == knowledge_id)
    for resource in db.scalars(public):
        sources.append(
            SourceUnit(
                "public:" + resource.id,
                resource.title,
                resource.text,
                resource.source,
                resource.knowledge_id,
                resource_id=resource.id,
            )
        )
    query = (
        select(Material)
        .where(Material.user_id == user_id, Material.deleted.is_(False), Material.confirmed.is_(True))
        .order_by(Material.id)
    )
    if lock:
        query = query.with_for_update()
    for material in db.scalars(query.execution_options(populate_existing=True)):
        chunks = list(
            db.scalars(
                select(SourceChunk)
                .where(SourceChunk.material_id == material.id)
                .execution_options(populate_existing=True)
            )
        )
        if chunks:
            for chunk in chunks:
                if chunk.status == "confirmed" and (not knowledge_id or chunk.knowledge_id == knowledge_id):
                    sources.append(
                        SourceUnit(
                            "chunk:" + chunk.id,
                            material.title,
                            chunk.text,
                            chunk.location,
                            chunk.knowledge_id,
                            material_id=material.id,
                            chunk_id=chunk.id,
                            owner_id=user_id,
                            external_allowed=material.external_processing_allowed,
                        )
                    )
        elif not knowledge_id or material.knowledge_id == knowledge_id:
            sources.append(
                SourceUnit(
                    "material:" + material.id,
                    material.title,
                    material.text,
                    "粘贴文本第 1 段",
                    material.knowledge_id,
                    material_id=material.id,
                    owner_id=user_id,
                    external_allowed=material.external_processing_allowed,
                )
            )
    segments = []
    for source in sources:
        text = source.text.strip()
        for start in range(0, len(text), 1050):
            part = text[start : start + 1200]
            if not part.strip():
                continue
            segments.append(
                SourceUnit(
                    **{
                        **source.__dict__,
                        "key": f"{source.key}:{start}",
                        "text": part,
                        "location": f"{source.location} · 字符 {start + 1}–{start + len(part)}",
                    }
                )
            )
            if start + 1200 >= len(text):
                break
    return segments


def invalidate_material_index(db, material_id):
    db.execute(delete(SourceEmbedding).where(SourceEmbedding.material_id == material_id))
    # A generated answer may quote a private source. Remove it with the source.
    from .db import ServiceJob

    for job in db.scalars(select(ServiceJob).where(ServiceJob.kind == "live_explanation")):
        if material_id in job.params.get("material_ids", []):
            job.status = "failed"
            job.params = {"source_deleted": True, "material_ids": []}
            job.result = {
                "implementation": "openai-compatible",
                "error_code": "source_unavailable",
                "error": "引用来源已删除、撤销或改变，旧解释不再显示。",
                "retryable": False,
            }


def index_sources(db, user_id, knowledge_id=None, transport=None):
    cfg = provider_config("embedding")
    units = source_units(db, user_id, knowledge_id)
    allowed = [unit for unit in units if unit.external_allowed]
    if len(allowed) > 200:
        raise ProviderFailure("scope_too_large", "本次资料超过 200 个片段，请缩小知识点范围。")
    cached = {
        row.source_key: row
        for row in db.scalars(
            select(SourceEmbedding).where(
                SourceEmbedding.namespace == cfg.namespace,
                or_(SourceEmbedding.owner_id.is_(None), SourceEmbedding.owner_id == user_id),
            )
        )
    }
    pending = [u for u in allowed if u.key not in cached or cached[u.key].source_hash != u.content_hash]
    calls, written = [], 0
    for start in range(0, len(pending), 8):
        batch = pending[start : start + 8]
        vectors, metadata = embed(db, user_id, [u.text for u in batch], transport)
        calls.append(metadata["call_id"])
        db.expire_all()
        # Recheck and lock private source owners after inference, before saving an index.
        live = {u.key: u for u in source_units(db, user_id, knowledge_id, lock=True) if u.external_allowed}
        for unit, vector in zip(batch, vectors, strict=True):
            if unit.key not in live or live[unit.key].content_hash != unit.content_hash:
                continue
            values = dict(
                id=str(uuid4()),
                source_key=unit.key,
                resource_id=unit.resource_id,
                material_id=unit.material_id,
                chunk_id=unit.chunk_id,
                owner_id=unit.owner_id,
                namespace=cfg.namespace,
                source_hash=unit.content_hash,
                dimensions=len(vector),
                vector=vector,
                created_at=time.time(),
            )
            if db.bind.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            statement = insert(SourceEmbedding).values(**values)
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["source_key", "namespace"],
                    set_={
                        k: getattr(statement.excluded, k)
                        for k in ("source_hash", "dimensions", "vector", "created_at")
                    },
                )
            )
            written += 1
        db.commit()
    return {
        "indexed": written,
        "reused": len(allowed) - len(pending),
        "skipped_private": len(units) - len(allowed),
        "call_ids": calls,
        "model": cfg.model,
        "namespace": cfg.namespace,
    }


def tokens(query):
    values = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", query.lower())
    return set(values)


def keyword_search(units, query, limit=6):
    terms = tokens(query)
    ranked = []
    for unit in units:
        content = (unit.title + " " + unit.text).lower()
        score = sum(1 for term in terms if term in content)
        if not terms or score:
            ranked.append((score / max(1, len(terms)), unit))
    ranked.sort(key=lambda item: (-item[0], item[1].key))
    return [{**unit.view(), "score": score} for score, unit in ranked[:limit]]


def semantic_search(db, user_id, query, knowledge_id, mode, allow_query, limit=6, transport=None):
    units = source_units(db, user_id, knowledge_id)
    if mode == "keyword":
        return {"mode": "keyword", "items": keyword_search(units, query, limit), "missing_index": 0}
    if not allow_query:
        raise ProviderFailure(
            "consent_required", "语义查询需要将本次查询发送给配置的 embedding 服务，请先确认。"
        )
    cfg = provider_config("embedding")
    if not cfg.configured:
        raise ProviderFailure("not_configured", "embedding 服务尚未配置；可先使用明确标记的关键词检索。")
    lookup = {u.key: u for u in units if u.external_allowed}
    entries = [
        row
        for row in db.scalars(
            select(SourceEmbedding).where(
                SourceEmbedding.namespace == cfg.namespace,
                or_(SourceEmbedding.owner_id.is_(None), SourceEmbedding.owner_id == user_id),
            )
        )
        if row.owner_id in (None, user_id)
        and row.source_key in lookup
        and row.source_hash == lookup[row.source_key].content_hash
    ]
    if not entries:
        return {
            "mode": mode,
            "items": [],
            "missing_index": len(lookup),
            "notice": "没有当前模型的有效索引，请先建立资料索引。",
        }
    vectors, metadata = embed(db, user_id, [query], transport)
    vector = vectors[0]
    entries = [row for row in entries if row.dimensions == len(vector)]
    if db.bind.dialect.name == "postgresql" and entries:
        distance = SourceEmbedding.vector.op("<=>", return_type=Float())(
            cast(bindparam("query_vector", type_=Vector()), Vector())
        ).label("distance")
        rows = db.execute(
            select(SourceEmbedding.source_key, distance)
            .where(SourceEmbedding.id.in_([r.id for r in entries]), SourceEmbedding.dimensions == len(vector))
            .order_by(distance)
            .limit(max(limit * 4, 24)),
            {"query_vector": vector},
        ).all()
        scores = {key: max(0, 1 - float(d)) for key, d in rows if d is not None}
    else:
        # Test portability only: production PostgreSQL uses the actual pgvector operator above.
        norm = math.sqrt(sum(v * v for v in vector))
        scores = {
            row.source_key: max(
                0,
                sum(a * b for a, b in zip(row.vector, vector, strict=True))
                / (math.sqrt(sum(v * v for v in row.vector)) * norm),
            )
            for row in entries
        }
    db.expire_all()
    live = {u.key: u for u in source_units(db, user_id, knowledge_id) if u.external_allowed}
    ranked = []
    lexical = {item["id"]: item["score"] for item in keyword_search(units, query, len(units))}
    for key, score in scores.items():
        if key not in live or live[key].content_hash != lookup[key].content_hash:
            continue
        if mode == "hybrid":
            score = 0.8 * score + 0.2 * lexical.get(key, 0)
        if score >= 0.25:
            ranked.append((score, live[key]))
    ranked.sort(key=lambda item: (-item[0], item[1].key))
    return {
        "mode": mode,
        "items": [{**u.view(), "score": round(score, 5)} for score, u in ranked[:limit]],
        "missing_index": max(0, len(lookup) - len(entries)),
        "model": cfg.model,
        "call_id": metadata["call_id"],
        "notice": "相似度用于检索排序，不表示资料正确性或学生掌握程度。",
    }
