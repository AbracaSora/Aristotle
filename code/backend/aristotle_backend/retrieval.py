"""Authorized source segments and real pgvector cosine search; keyword mode stays explicit."""

import math
import re
import time
from functools import partial
from uuid import uuid4

from sqlalchemy import Float, bindparam, cast, delete, or_, select

from .db import SourceEmbedding
from .providers import ModelContext, ProviderFailure, embed, provider_config
from .source_units import SourceScope, unchanged
from .source_units import SourceUnit as SourceUnit
from .source_units import source_units as source_units
from .vector_type import Vector


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


def pending_sources(db, user_id, namespace, allowed):
    hashes = dict(
        db.execute(
            select(SourceEmbedding.source_key, SourceEmbedding.source_hash).where(
                SourceEmbedding.namespace == namespace,
                or_(SourceEmbedding.owner_id.is_(None), SourceEmbedding.owner_id == user_id),
            )
        ).all()
    )
    return [unit for unit in allowed if hashes.get(unit.key) != unit.content_hash]


def index_sources(db, user_id, knowledge_id=None, transport=None):
    cfg = provider_config("embedding")
    units = source_units(db, user_id, knowledge_id)
    allowed = [unit for unit in units if unit.external_allowed]
    if len(allowed) > 200:
        raise ProviderFailure("scope_too_large", "本次资料超过 200 个片段，请缩小知识点范围。")
    pending = pending_sources(db, user_id, cfg.namespace, allowed)
    scope = SourceScope(db, user_id, knowledge_id)
    calls, written = [], 0
    for start in range(0, len(pending), 8):
        current = scope.authorized()
        batch = [u for u in pending[start : start + 8] if unchanged(u, current)]
        if not batch:
            continue
        vectors, metadata = embed(
            ModelContext(db, user_id, transport),
            [u.text for u in batch],
            validate_sources=partial(scope.require_current, batch),
        )
        calls.append(metadata["call_id"])
        written += save_batch(scope, cfg.namespace, batch, vectors)
    return {
        "indexed": written,
        "reused": len(allowed) - len(pending),
        "skipped_private": len(units) - len(allowed),
        "call_ids": calls,
        "model": cfg.model,
        "namespace": cfg.namespace,
    }


def save_batch(scope, namespace, batch, vectors):
    current = scope.authorized(lock=True)
    written = 0
    for unit, vector in zip(batch, vectors, strict=True):
        if unchanged(unit, current):
            upsert_vector(scope.db, namespace, unit, vector)
            written += 1
    scope.db.commit()
    return written


def upsert_vector(db, namespace, unit, vector):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(SourceEmbedding).values(
        id=str(uuid4()),
        source_key=unit.key,
        resource_id=unit.resource_id,
        material_id=unit.material_id,
        chunk_id=unit.chunk_id,
        owner_id=unit.owner_id,
        namespace=namespace,
        source_hash=unit.content_hash,
        dimensions=len(vector),
        vector=vector,
        created_at=time.time(),
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["source_key", "namespace"],
            set_={
                k: getattr(statement.excluded, k)
                for k in ("source_hash", "dimensions", "vector", "created_at")
            },
        )
    )


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


def valid_entries(db, user_id, cfg, lookup):
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
    return entries


def vector_scores(db, entries, vector, limit):
    if not entries:
        return {}
    if db.bind.dialect.name == "postgresql":
        distance = SourceEmbedding.vector.op("<=>", return_type=Float())(
            cast(bindparam("query_vector", type_=Vector()), Vector())
        ).label("distance")
        rows = db.execute(
            select(SourceEmbedding.source_key, distance)
            .where(SourceEmbedding.id.in_([r.id for r in entries]), SourceEmbedding.dimensions == len(vector))
            .order_by(distance, SourceEmbedding.source_key)
            .limit(max(limit * 4, 24)),
            {"query_vector": vector},
        )
        return {key: max(0, 1 - float(d)) for key, d in rows if d is not None}
    # SQLite exercises the same cosine metric in portable test databases.
    norm = math.hypot(*vector)
    return {row.source_key: cosine_score(row.vector, vector, norm) for row in entries}


def cosine_score(source, query, query_norm):
    dot = sum(a * b for a, b in zip(source, query, strict=True))
    return max(0, dot / (math.hypot(*source) * query_norm))


def rank_results(scores, live, lookup, lexical):
    ranked = []
    for key, score in scores.items():
        if not unchanged(lookup[key], live):
            continue
        if lexical is not None:
            score = 0.8 * score + 0.2 * lexical.get(key, 0)
        if score >= 0.25:
            ranked.append((score, live[key]))
    ranked.sort(key=lambda item: (-item[0], item[1].key))
    return ranked


def semantic_config(allow_query):
    if not allow_query:
        raise ProviderFailure(
            "consent_required", "语义查询需要将本次查询发送给配置的 embedding 服务，请先确认。"
        )
    cfg = provider_config("embedding")
    if not cfg.configured:
        raise ProviderFailure("not_configured", "embedding 服务尚未配置；可先使用明确标记的关键词检索。")
    return cfg


def outbound_sources(units):
    """Only explicitly authorized source units may enter semantic retrieval."""
    return {unit.key: unit for unit in units if unit.external_allowed}


def semantic_search(db, user_id, search, transport=None):
    units = source_units(db, user_id, search.knowledge_id)
    if search.mode == "keyword":
        return {
            "mode": "keyword",
            "items": keyword_search(units, search.query, search.limit),
            "missing_index": 0,
        }
    cfg = semantic_config(search.allow_external_query)
    lookup = outbound_sources(units)
    entries = valid_entries(db, user_id, cfg, lookup)
    if not entries:
        return {
            "mode": search.mode,
            "items": [],
            "missing_index": len(lookup),
            "notice": "没有当前模型的有效索引，请先建立资料索引。",
        }
    vectors, metadata = embed(ModelContext(db, user_id, transport), [search.query])
    vector = vectors[0]
    entries = [row for row in entries if row.dimensions == len(vector)]
    scores = vector_scores(db, entries, vector, search.limit)
    live = outbound_sources(source_units(db, user_id, search.knowledge_id))
    lexical = None
    if search.mode == "hybrid":
        lexical = {item["id"]: item["score"] for item in keyword_search(units, search.query, len(units))}
    ranked = rank_results(scores, live, lookup, lexical)
    return {
        "mode": search.mode,
        "items": [{**u.view(), "score": round(score, 5)} for score, u in ranked[: search.limit]],
        "missing_index": max(0, len(lookup) - len(entries)),
        "model": cfg.model,
        "call_id": metadata["call_id"],
        "notice": "相似度用于检索排序，不表示资料正确性或学生掌握程度。",
    }
