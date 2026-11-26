"""Resolve current source permissions and page-preserving retrieval segments."""

from dataclasses import dataclass, replace
from itertools import chain

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import LearningResource, Material, SourceChunk
from .providers import ProviderFailure, fingerprint


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


def public_sources(db, knowledge_id):
    query = select(LearningResource).execution_options(populate_existing=True)
    if knowledge_id:
        query = query.where(LearningResource.knowledge_id == knowledge_id)
    for row in db.scalars(query):
        yield SourceUnit(
            "public:" + row.id, row.title, row.text, row.source, row.knowledge_id, resource_id=row.id
        )


def private_sources(db, user_id, knowledge_id, lock):
    # A material with chunks must never fall back to its unconfirmed whole text.
    whole = SourceChunk.id.is_(None)
    confirmed = SourceChunk.status == "confirmed"
    if knowledge_id:
        whole = whole & (Material.knowledge_id == knowledge_id)
        confirmed = confirmed & (SourceChunk.knowledge_id == knowledge_id)
    query = (
        select(Material, SourceChunk)
        .outerjoin(SourceChunk, SourceChunk.material_id == Material.id)
        .where(
            Material.user_id == user_id,
            Material.deleted.is_(False),
            Material.confirmed.is_(True),
            whole | confirmed,
        )
        .order_by(Material.id, SourceChunk.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(of=Material)
    for material, chunk in db.execute(query):
        yield private_unit(material, chunk)


def private_unit(material, chunk):
    ownership = dict(
        material_id=material.id,
        owner_id=material.user_id,
        external_allowed=material.external_processing_allowed,
    )
    if chunk is None:
        return SourceUnit(
            "material:" + material.id,
            material.title,
            material.text,
            "粘贴文本第 1 段",
            material.knowledge_id,
            **ownership,
        )
    return SourceUnit(
        "chunk:" + chunk.id,
        material.title,
        chunk.text,
        chunk.location,
        chunk.knowledge_id,
        chunk_id=chunk.id,
        **ownership,
    )


def segments(source):
    text = source.text.strip()
    for start in range(0, len(text), 1050):
        part = text[start : start + 1200]
        if part.strip():
            yield replace(
                source,
                key=f"{source.key}:{start}",
                text=part,
                location=f"{source.location} · 字符 {start + 1}–{start + len(part)}",
            )
        if start + 1200 >= len(text):
            break


def source_units(db, user_id, knowledge_id=None, lock=False):
    sources = chain(public_sources(db, knowledge_id), private_sources(db, user_id, knowledge_id, lock))
    return [segment for source in sources for segment in segments(source)]


@dataclass(frozen=True)
class SourceScope:
    db: Session
    user_id: str
    knowledge_id: str | None

    def authorized(self, lock=False):
        with self.db.no_autoflush:
            return {
                u.key: u
                for u in source_units(self.db, self.user_id, self.knowledge_id, lock)
                if u.external_allowed
            }

    def require_current(self, expected):
        current = self.authorized()
        if any(not unchanged(u, current) for u in expected):
            raise ProviderFailure("source_unavailable", "资料授权、内容或关联已变化，请重新检索。")


def unchanged(unit, current):
    latest = current.get(unit.key)
    return latest is not None and latest.content_hash == unit.content_hash
