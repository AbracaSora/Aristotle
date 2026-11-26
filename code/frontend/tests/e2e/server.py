"""Local-only browser fixture. Uses a fresh temporary DB and an in-process model transport."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from sqlalchemy import select

from aristotle_backend.app import active_graph, create_app
from aristotle_backend.curriculum_publication import SUBJECT_IDS, publish_curriculum
from aristotle_backend.curriculum_schemas import CurriculumPublication
from aristotle_backend.db import Question, User
from aristotle_backend.design_seed import seed_design_flow
from aristotle_backend.migrations import upgrade_database
from aristotle_backend.seed import seed_demo


def course_fixture(db):
    subject_id = "data-structures"
    subjects = [{"id": sid, "name": sid, "order": i} for i, sid in enumerate(sorted(SUBJECT_IDS))]
    questions, points = [], []
    for i, node in enumerate(active_graph(db).nodes):
        rows = db.scalars(
            select(Question)
            .where(Question.knowledge_id == node["id"], Question.status == "published")
            .order_by(Question.key)
            .limit(3)
        ).all()
        points.append(
            dict(
                id=node["id"],
                name=node["name"],
                order=i,
                subject_id=subject_id,
                chapter_id="ds",
                prerequisite_ids=node["prerequisites"],
                preset_set=dict(id="preset-" + node["id"], version=1, question_keys=[q.key for q in rows]),
            )
        )
        for q in rows:
            options = [{"id": chr(65 + k), "text": v} for k, v in enumerate(q.options)]
            questions.append(
                dict(
                    key=q.key,
                    question_id=q.question_id,
                    version=q.version,
                    knowledge_id=q.knowledge_id,
                    stem=q.prompt,
                    options=options,
                    answer={"option_id": chr(65 + q.options.index(q.answer))},
                    explanation=q.explanation,
                    bloom_level=q.level,
                    source={"type": "authored", "title": q.source},
                    review_status="published",
                    dataset=q.dataset,
                    created_at="2026-11-26T00:00:00Z",
                    updated_at="2026-11-26T00:00:00Z",
                )
            )
    catalog = CurriculumPublication.model_validate(
        dict(
            graph_version="browser-course",
            subjects=subjects,
            chapters=[dict(id="ds", subject_id=subject_id, name="线性结构与栈", order=0)],
            knowledge_points=points,
            questions=questions,
        )
    )
    publish_curriculum(db, catalog, demo=True)
    db.commit()


def fixture_response(request):
    payload = json.loads(request.content)
    content = json.loads(payload["messages"][-1]["content"])
    if "question_count" in content:
        result = {
            "questions": [
                {
                    "stem": f"练习场景 {i}：入栈后从哪一端弹出？",
                    "options": [{"id": "A", "text": "栈顶"}, {"id": "B", "text": "栈底"}],
                    "answer": {"option_id": "A"},
                    "explanation": "从栈顶操作。",
                    "bloom_level": "apply",
                }
                for i in range(content["question_count"])
            ]
        }
    elif "sources" in content:
        result = {
            "answer": "请核对所引段落。",
            "citations": [content["sources"][0]["id"]],
            "insufficient_evidence": False,
        }
    else:
        result = {"summary": "已保存本轮结果。", "suggestions": ["复习错题对应的概念。"]}
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}
    )


if __name__ == "__main__":
    os.environ.update(
        ARISTOTLE_ENV="test",
        ARISTOTLE_LLM_LOCAL="1",
        ARISTOTLE_LLM_MODEL="browser-fixture",
        ARISTOTLE_LLM_BASE_URL="http://127.0.0.1",
        ARISTOTLE_LLM_API_KEY="",
        ARISTOTLE_EMBEDDING_BASE_URL="",
        ARISTOTLE_EMBEDDING_API_KEY="",
        ARISTOTLE_MODEL_PROXY="",
        ARISTOTLE_INLINE_WORKER="1",
    )
    with TemporaryDirectory() as directory:
        url = "sqlite:///" + str(Path(directory) / "browser.db")
        upgrade_database(url)
        app = create_app(url)
        app.state.model_transport = httpx.MockTransport(fixture_response)
        seed_demo(app.state.sessions)
        seed_design_flow(app.state.sessions)
        with app.state.sessions() as db:
            demo_user = db.get(User, "student2")
            db.add(
                User(
                    id="pdf-reader",
                    username="pdf-reader",
                    role="student",
                    password_hash=demo_user.password_hash,
                )
            )
            course_fixture(db)
        worker = subprocess.Popen(
            [sys.executable, "-m", "aristotle_backend.import_worker"],
            env={**os.environ, "ARISTOTLE_DATABASE_URL": url},
        )
        try:
            uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]))
        finally:
            worker.terminate()
            worker.wait()
