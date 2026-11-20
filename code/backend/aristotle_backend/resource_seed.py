"""Explicitly publish the bundled 408 resources as local demo content.

The canonical resource files remain pending review. This importer is therefore
only for the local demo environment and does not create review approvals.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from aristotle_core.policy import LEVELS, validate_graph
from sqlalchemy import select

from .config import PROJECT_ROOT
from .db import Graph, LearnerProfile, LearningResource, LearningScope, Question

LEGACY_SCOPE_IDS = {"foundations", "stack", "stack-analysis", "os-planned"}
RESOURCE_SCOPE_PREFIX = "resource-"


def _json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_bundle(resource_root: Path) -> tuple[dict, list[dict], list[dict], dict]:
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
    return graph, points, questions, manifest


def import_resource_demo(sessions, resource_root: Path | None = None) -> dict[str, int | str]:
    """Load the four-subject resource bundle without deleting learning history."""

    graph, points, questions, manifest = _load_bundle(resource_root or PROJECT_ROOT / "resource")
    graph_version = (
        "resource-demo-"
        + hashlib.sha256(json.dumps(graph["nodes"], sort_keys=True).encode()).hexdigest()[:12]
    )
    questions_by_point = defaultdict(list)
    for question in questions:
        questions_by_point[question["knowledge_point_id"]].append(question)

    inserted_questions = 0
    with sessions() as db:
        stored_graph = db.scalar(select(Graph).where(Graph.version == graph_version))
        if stored_graph and stored_graph.nodes != graph["nodes"]:
            raise ValueError("同版本知识图内容不一致")
        if not stored_graph:
            db.add(Graph(version=graph_version, nodes=graph["nodes"]))

        for point in points:
            point_questions = questions_by_point[point["id"]]
            if not point_questions:
                raise ValueError(f"知识点没有题目：{point['id']}")
            for item in point_questions:
                key = f"{item['id']}:v{item['version']}"
                if db.get(Question, key):
                    continue
                db.add(
                    Question(
                        key=key,
                        question_id=item["id"],
                        version=item["version"],
                        knowledge_id=point["id"],
                        prompt=item["stem"],
                        options=list(item["options"].values()),
                        answer=item["options"][item["answer"]],
                        explanation=item["explanation"],
                        source=(
                            f"resource 本地演示题；{item['source_type']}；"
                            f"{item['review_status']}，未完成人工审核"
                        ),
                        status="published",
                        level=item["cognitive_level_candidate"],
                        dataset="demo-seed",
                    )
                )
                inserted_questions += 1

            resource_id = "resource-guide-" + point["id"]
            resource = db.get(LearningResource, resource_id)
            if not resource:
                resource = LearningResource(id=resource_id)
                db.add(resource)
            resource.knowledge_id = point["id"]
            resource.title = point["name"] + " · 练习要点"
            resource.text = "\n\n".join(dict.fromkeys(item["explanation"] for item in point_questions))
            resource.source = "resource 题目解析汇编；本地演示资料，待人工审核"

        first_scope_id = None
        scope_count = 0
        for subject in manifest["subjects"]:
            subject_points = [point for point in points if point["subject_code"] == subject["subject_code"]]
            chapter_numbers = sorted({point["chapter_number"] for point in subject_points})
            for chapter_number in chapter_numbers:
                chapter_points = [
                    point for point in subject_points if point["chapter_number"] == chapter_number
                ]
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
        db.commit()

    return {
        "knowledge_points": len(points),
        "questions": len(questions),
        "inserted_questions": inserted_questions,
        "scopes": scope_count,
        "graph_version": graph_version,
    }
