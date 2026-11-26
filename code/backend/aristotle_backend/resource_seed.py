"""Explicitly publish the bundled 408 resources as local demo content.

The canonical resource files remain pending review. This importer is therefore
only for the local demo environment and does not create review approvals.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from aristotle_core.policy import LEVELS, validate_graph
from sqlalchemy import select

from .config import PROJECT_ROOT, require_demo_mode
from .db import Graph, LearnerProfile, LearningResource, LearningScope, Question

LEGACY_SCOPE_IDS = {"foundations", "stack", "stack-analysis", "os-planned"}
RESOURCE_SCOPE_PREFIX = "resource-"


@dataclass
class ResourceBundle:
    graph: dict
    points: list[dict]
    questions: list[dict]
    manifest: dict

    def chapter_groups(self):
        grouped = defaultdict(list)
        for point in self.points:
            grouped[point["subject_code"], point["chapter_number"]].append(point)
        for subject in self.manifest["subjects"]:
            code = subject["subject_code"]
            for number in sorted(n for sid, n in grouped if sid == code):
                yield subject, number, grouped[code, number]


def _json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_bundle(resource_root: Path) -> ResourceBundle:
    manifest = json.loads((resource_root / "manifest.json").read_text(encoding="utf-8"))
    graph = json.loads((resource_root / manifest["exports"]["graph"]).read_text(encoding="utf-8"))
    points, questions = [], []
    for subject in manifest["subjects"]:
        directory = resource_root / subject["directory"]
        subject_points = _json_lines(directory / "knowledge_points.jsonl")
        subject_questions = _json_lines(directory / "questions.jsonl")
        if len(subject_points) != subject["knowledge_points"]:
            raise ValueError(f"{subject['subject']}知识点数量与 manifest 不一致")
        if len(subject_questions) != subject["questions"]:
            raise ValueError(f"{subject['subject']}题目数量与 manifest 不一致")
        points.extend(subject_points)
        questions.extend(subject_questions)
    if len(points) != manifest["total_knowledge_points"]:
        raise ValueError("知识点总数与 manifest 不一致")
    if len(questions) != manifest["total_questions"]:
        raise ValueError("题目总数与 manifest 不一致")
    validate_bundle(graph, points, questions)
    return ResourceBundle(graph, points, questions, manifest)


def validate_bundle(graph, points, questions):
    point_ids = {point["id"] for point in points}
    if len(point_ids) != len(points) or point_ids != {node["id"] for node in graph["nodes"]}:
        raise ValueError("知识点与导出知识图不一致")
    validate_graph(graph["nodes"])
    for question in questions:
        if question["knowledge_point_id"] not in point_ids:
            raise ValueError(f"题目引用未知知识点：{question['id']}")
        if question["cognitive_level_candidate"] not in LEVELS:
            raise ValueError(f"题目认知层级无效：{question['id']}")
        if question["answer"] not in question["options"]:
            raise ValueError(f"题目答案不在选项中：{question['id']}")
        if len(set(question["options"].values())) != len(question["options"]):
            raise ValueError(f"题目选项文本重复：{question['id']}")


def import_resource_demo(sessions, resource_root: Path | None = None) -> dict[str, int | str]:
    """Load the four-subject resource bundle without deleting learning history."""

    require_demo_mode()
    bundle = _load_bundle(resource_root or PROJECT_ROOT / "resource")
    graph_version = (
        "resource-demo-"
        + hashlib.sha256(json.dumps(bundle.graph["nodes"], sort_keys=True).encode()).hexdigest()[:12]
    )
    with sessions() as db:
        store_resource_graph(db, graph_version, bundle.graph)
        inserted_questions = store_resources(db, bundle)
        scope_count = store_chapter_scopes(db, bundle)
        db.flush()
        publish_resource_catalog(db, graph_version, bundle)
        db.commit()

    return {
        "knowledge_points": len(bundle.points),
        "questions": len(bundle.questions),
        "inserted_questions": inserted_questions,
        "scopes": scope_count,
        "graph_version": graph_version,
    }


def store_resource_graph(db, graph_version, graph):
    stored_graph = db.scalar(select(Graph).where(Graph.version == graph_version))
    if stored_graph and stored_graph.nodes != graph["nodes"]:
        raise ValueError("同版本知识图内容不一致")
    if not stored_graph:
        db.add(Graph(version=graph_version, nodes=graph["nodes"]))


def store_question(db, item):
    key = f"{item['id']}:v{item['version']}"
    if db.get(Question, key):
        return 0
    db.add(
        Question(
            key=key,
            question_id=item["id"],
            version=item["version"],
            knowledge_id=item["knowledge_point_id"],
            prompt=item["stem"],
            options=list(item["options"].values()),
            answer=item["options"][item["answer"]],
            explanation=item["explanation"],
            source=(f"resource 本地演示题；{item['source_type']}；{item['review_status']}，未完成人工审核"),
            status="published",
            level=item["cognitive_level_candidate"],
            dataset="demo-seed",
        )
    )
    return 1


def store_guide(db, point, point_questions):
    resource_id = "resource-guide-" + point["id"]
    resource = db.get(LearningResource, resource_id)
    if not resource:
        resource = LearningResource(id=resource_id)
        db.add(resource)
    resource.knowledge_id = point["id"]
    resource.title = point["name"] + " · 练习要点"
    resource.text = "\n\n".join(dict.fromkeys(item["explanation"] for item in point_questions))
    resource.source = "resource 题目解析汇编；本地演示资料，待人工审核"


def store_resources(db, bundle):
    questions_by_point = defaultdict(list)
    for question in bundle.questions:
        questions_by_point[question["knowledge_point_id"]].append(question)
    inserted = 0
    for point in bundle.points:
        items = questions_by_point[point["id"]]
        if not items:
            raise ValueError(f"知识点没有题目：{point['id']}")
        inserted += sum(store_question(db, item) for item in items)
        store_guide(db, point, items)
    return inserted


def store_chapter_scopes(db, bundle):
    first_scope_id = None
    scope_count = 0
    for subject, chapter_number, chapter_points in bundle.chapter_groups():
        scope_id = f"{RESOURCE_SCOPE_PREFIX}{subject['subject_code']}-{chapter_number}"
        first_scope_id = first_scope_id or scope_id
        scope = db.get(LearningScope, scope_id)
        if not scope:
            scope = LearningScope(id=scope_id)
            db.add(scope)
        scope.title = f"{subject['subject']} · {chapter_points[0]['chapter']}"
        scope.knowledge_ids = [point["id"] for point in chapter_points]
        scope.published = True
        scope.description = "与四科学习地图一致的章节；题目与认知标签为待审核演示内容。"
        scope_count += 1

    for legacy_id in LEGACY_SCOPE_IDS:
        legacy = db.get(LearningScope, legacy_id)
        if legacy:
            legacy.published = False
    for profile in db.scalars(select(LearnerProfile)):
        if profile.scope_id in LEGACY_SCOPE_IDS:
            profile.scope_id = first_scope_id
    return scope_count


def publish_resource_catalog(db, graph_version, bundle):
    """Adapt explicit demo imports to the fixed curriculum without claiming review approval."""
    from .curriculum import publish_curriculum
    from .curriculum_schemas import CurriculumPublication

    graph = bundle.graph
    by_node = {node["id"]: node for node in graph["nodes"]}
    keys = defaultdict(list)
    for item in bundle.questions:
        keys[item["knowledge_point_id"]].append(f"{item['id']}:v{item['version']}")
    subjects = [catalog_subject(s, i) for i, s in enumerate(bundle.manifest["subjects"])]
    chapters, knowledge = [], []
    for subject, number, members in bundle.chapter_groups():
        chapter = catalog_chapter(subject, number, members)
        chapters.append(chapter)
        for i, p in enumerate(members):
            knowledge.append(
                catalog_point(p, chapter, i, keys[p["id"]])
                | {"prerequisite_ids": by_node[p["id"]]["prerequisites"]}
            )
    standard = [catalog_question(db, q) for q in bundle.questions]
    # Export order is authoritative for the shared graph; UI order stays chapter-local.
    order_by_id = {p["id"]: p for p in knowledge}
    knowledge = [order_by_id[n["id"]] for n in graph["nodes"]]
    publish_curriculum(
        db,
        CurriculumPublication.model_validate(
            {
                "graph_version": graph_version,
                "subjects": subjects,
                "chapters": chapters,
                "knowledge_points": knowledge,
                "questions": standard,
            }
        ),
        demo=True,
    )


def catalog_subject(subject, order):
    return {
        "id": subject["directory"],
        "name": subject["subject"],
        "description": "408 本地演示课程",
        "order": order,
        "status": "published",
    }


def catalog_chapter(subject, number, members):
    return {
        "id": f"{subject['subject_code']}-chapter-{number}",
        "subject_id": subject["directory"],
        "name": members[0]["chapter"],
        "description": "",
        "order": number,
        "status": "published",
    }


def catalog_point(p, chapter, i, keys):
    return {
        "id": p["id"],
        "subject_id": chapter["subject_id"],
        "chapter_id": chapter["id"],
        "name": p["name"],
        "description": "",
        "order": i,
        "status": "published",
        "tag_ids": [],
        "preset_set": {"id": "preset-" + p["id"], "version": 1, "question_keys": keys},
    }


def catalog_question(db, q):
    import time

    from .curriculum import iso
    from .db import StandardQuestion

    key = f"{q['id']}:v{q['version']}"
    existing = db.get(StandardQuestion, key)
    if existing:
        return existing.data
    row = db.get(Question, key)
    return {
        "question_id": row.question_id,
        "version": row.version,
        "key": key,
        "knowledge_id": row.knowledge_id,
        "related_knowledge_ids": q["secondary_knowledge_point_ids"],
        "stem": row.prompt,
        "options": [{"id": chr(65 + i), "text": v} for i, v in enumerate(row.options)],
        "answer": {"option_id": chr(65 + row.options.index(row.answer))},
        "explanation": row.explanation,
        "bloom_level": row.level,
        "tag_ids": [],
        "source": {
            "type": "authored" if q["source_type"] == "past_exam_adapted" else q["source_type"],
            "title": row.source,
            "year": q["year"],
            "question_number": str(q["original_question_number"])
            if q["original_question_number"] is not None
            else None,
            "url": q["source_url"],
        },
        "review_status": row.status,
        "dataset": row.dataset,
        "created_at": iso(time.time()),
        "updated_at": iso(time.time()),
    }
