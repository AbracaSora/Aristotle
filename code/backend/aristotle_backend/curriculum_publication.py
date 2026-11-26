"""Validate catalog revisions before persisting a complete publication."""

import time
from dataclasses import dataclass

from aristotle_core.policy import validate_graph
from sqlalchemy import select, text, update

from .curriculum_schemas import CurriculumPublication
from .db import (
    CurriculumChapter,
    CurriculumPoint,
    CurriculumSubject,
    FinalTest,
    Graph,
    PresetSet,
    Question,
    StandardQuestion,
    SystemSetting,
)

SUBJECT_IDS = {"data-structures", "computer-organization", "operating-systems", "computer-networks"}


@dataclass
class Catalog:
    subjects: dict
    chapters: dict
    points: dict
    tags: set
    questions: dict


def catalog_of(body):
    subjects = {s.id: s for s in body.subjects}
    chapters = {c.id: c for c in body.chapters}
    points = {p.id: p for p in body.knowledge_points}
    tags = {t.id for t in body.tags}
    questions = {q.key: q for q in body.questions}
    if any(
        len(a) != len(b)
        for a, b in (
            (subjects, body.subjects),
            (chapters, body.chapters),
            (points, body.knowledge_points),
            (tags, body.tags),
            (questions, body.questions),
        )
    ):
        raise ValueError("课程对象 ID 不能重复")
    if set(subjects) != SUBJECT_IDS:
        raise ValueError("课程必须包含四个固定科目")
    return Catalog(subjects, chapters, points, tags, questions)


def validate_chapters(catalog):
    subjects, chapters = catalog.subjects, catalog.chapters
    for c in chapters.values():
        if c.subject_id not in subjects:
            raise ValueError("章节引用未知科目")
        if c.status == "published" and subjects[c.subject_id].status != "published":
            raise ValueError("已发布章节的科目必须已发布")


def validate_point(p, catalog):
    chapters, points, tags = catalog.chapters, catalog.points, catalog.tags
    if p.chapter_id not in chapters or chapters[p.chapter_id].subject_id != p.subject_id:
        raise ValueError("知识点章节与科目不匹配")
    if p.status == "published" and chapters[p.chapter_id].status != "published":
        raise ValueError("已发布知识点的章节必须已发布")
    validate_point_links(p, points, tags)


def validate_point_links(p, points, tags):
    if len(set(p.prerequisite_ids)) != len(p.prerequisite_ids):
        raise ValueError("先修关系不能重复")
    if len(set(p.tag_ids)) != len(p.tag_ids) or set(p.tag_ids) - tags:
        raise ValueError("知识点含重复或未知标签")
    if any(k not in points or points[k].status != "published" for k in p.prerequisite_ids):
        raise ValueError("前驱不存在或未发布")


def validate_preset_revision(db, p):
    preset = p.preset_set
    old = db.get(PresetSet, (preset.id, preset.version))
    if old and ((old.knowledge_id, old.question_keys) != (p.id, preset.question_keys)):
        raise ValueError("已保存的预设集合不可覆盖，请增加版本")
    versions = db.scalars(select(PresetSet).where(PresetSet.id == preset.id)).all()
    if any(v.knowledge_id != p.id for v in versions):
        raise ValueError("预设集合 ID 不可跨知识点复用")
    current = db.get(CurriculumPoint, p.id)
    if current:
        previous = current.data["preset_set"]
        if previous["id"] == preset.id and preset.version < previous["version"]:
            raise ValueError("不可回退当前预设集合版本")
        if (previous["id"], previous["version"]) != (preset.id, preset.version) and db.scalar(
            select(FinalTest.id)
            .where(FinalTest.knowledge_id == p.id, FinalTest.status.in_(("generating", "ready")))
            .limit(1)
        ):
            raise ValueError("仍有进行中的小测，完成或确认生成失败后才能变更预设集合")


def validate_preset_questions(p, catalog):
    preset, questions = p.preset_set, catalog.questions
    for key in preset.question_keys:
        q = questions.get(key)
        if not q or q.knowledge_id != p.id or q.review_status != "published":
            raise ValueError("预设题必须存在、已发布且主知识点匹配")


def validate_question(db, q, catalog, demo):
    row = db.get(Question, q.key)
    if not row or row.status != "published" or q.review_status != "published":
        raise ValueError("未审核发布题不能进入预设集合")
    if not demo and (row.dataset == "demo-seed" or q.dataset == "demo-seed"):
        raise ValueError("正式课程不能发布演示题；演示导入必须显式启用")
    validate_question_references(q, catalog)
    validate_frozen_question(q, row)
    old = db.get(StandardQuestion, q.key)
    if old and old.data != q.model_dump(mode="json"):
        raise ValueError("已有题目元数据不可覆盖，请发布新题目版本")


def validate_frozen_question(q, row):
    # Stable A-H mapping frozen from the old version's option order.
    expected = [{"id": chr(65 + i), "text": text} for i, text in enumerate(row.options)]
    if len(set(row.options)) != len(row.options) or row.options.count(row.answer) != 1:
        raise ValueError("旧题答案不能唯一对应选项，拒绝迁移")
    frozen = {
        "question_id": row.question_id,
        "version": row.version,
        "knowledge_id": row.knowledge_id,
        "stem": row.prompt,
        "options": expected,
        "answer": {"option_id": chr(65 + row.options.index(row.answer))},
        "explanation": row.explanation,
        "bloom_level": row.level,
        "dataset": row.dataset,
    }
    incoming = q.model_dump(mode="json")
    if any(incoming[key] != value for key, value in frozen.items()):
        raise ValueError("标准题对象必须与已发布版本及最终认知标签一致")


def persist_graph(db, body, catalog):
    points = catalog.points
    nodes = [{"id": p.id, "name": p.name, "prerequisites": p.prerequisite_ids} for p in points.values()]
    nodes = [node for node in nodes if points[node["id"]].status == "published"]
    graph = db.scalar(select(Graph).where(Graph.version == body.graph_version))
    if graph and graph.nodes != nodes:
        raise ValueError("同一 graph_version 不能对应不同结构")
    if not graph:
        db.add(Graph(version=body.graph_version, nodes=nodes))


def persist_hierarchy(db, catalog):
    subjects, chapters = catalog.subjects, catalog.chapters
    for model, items in ((CurriculumSubject, subjects), (CurriculumChapter, chapters)):
        for old in db.scalars(select(model)):
            if old.id not in items:
                old.data = {**old.data, "status": "retired"}
        for item in items.values():
            data = item.model_dump(mode="json")
            row = db.get(model, item.id)
            if row is None:
                row = model(id=item.id)
                db.add(row)
            row.data = data
            if model is CurriculumChapter:
                row.subject_id = item.subject_id
        db.flush()


def persist_points(db, body, catalog, now):
    points = catalog.points
    for row in db.scalars(select(CurriculumPoint)):
        if row.id not in points:
            row.data = {**row.data, "status": "retired"}
    for p in points.values():
        data = p.model_dump(mode="json")
        data["preset_set"]["question_count"] = len(p.preset_set.question_keys)
        row = db.get(CurriculumPoint, p.id)
        if row is None:
            row = CurriculumPoint(id=p.id)
            db.add(row)
        if row.data != data:
            row.updated_at = now
        row.chapter_id, row.graph_version, row.data = p.chapter_id, body.graph_version, data
    db.flush()


def persist_snapshots(db, body, catalog):
    points, questions = catalog.points, catalog.questions
    for p in points.values():
        preset = p.preset_set
        if not db.get(PresetSet, (preset.id, preset.version)):
            db.add(
                PresetSet(
                    id=preset.id,
                    version=preset.version,
                    knowledge_id=p.id,
                    question_keys=preset.question_keys,
                )
            )
    for q in questions.values():
        if not db.get(StandardQuestion, q.key):
            db.add(StandardQuestion(key=q.key, data=q.model_dump(mode="json")))
    setting = db.get(SystemSetting, "curriculum-tags")
    if not setting:
        setting = SystemSetting(key="curriculum-tags")
        db.add(setting)
    setting.data = {"items": [t.model_dump() for t in body.tags]}
    db.flush()


def publish_curriculum(db, body: CurriculumPublication, *, demo=False, now=None):
    """Validate the full graph and frozen versions before changing persistent content."""
    now = time.time() if now is None else now
    db.execute(
        update(SystemSetting).where(SystemSetting.key == "curriculum-tags").values(key=SystemSetting.key)
    )
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": 408202611})
    catalog = catalog_of(body)
    validate_chapters(catalog)
    preset_ids = set()
    for point in catalog.points.values():
        validate_point(point, catalog)
        if point.preset_set.id in preset_ids:
            raise ValueError("不同知识点不能共用预设集合 ID")
        preset_ids.add(point.preset_set.id)
        validate_preset_revision(db, point)
        validate_preset_questions(point, catalog)
    validate_graph(
        [{"id": p.id, "name": p.name, "prerequisites": p.prerequisite_ids} for p in catalog.points.values()]
    )
    for question in catalog.questions.values():
        validate_question(db, question, catalog, demo)
    persist_graph(db, body, catalog)
    persist_hierarchy(db, catalog)
    persist_points(db, body, catalog, now)
    persist_snapshots(db, body, catalog)


def validate_question_references(q, catalog):
    points, tags = catalog.points, catalog.tags
    if q.knowledge_id not in points or set(q.related_knowledge_ids) - set(points) or set(q.tag_ids) - tags:
        raise ValueError("题目引用未知知识点或标签")
