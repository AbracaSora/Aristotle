from uuid import uuid4

from aristotle_core.policy import validate_graph
from fastapi import Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select, update

from .api_access import current_user, fail, get_db, maintainer, maintainer_session, student
from .api_views import active_graph, audit_record, material_view, owned, question_view
from .db import (
    Annotation,
    Audit,
    CurriculumPoint,
    Graph,
    Material,
    Question,
    Review,
    SystemSetting,
)
from .flow_support import erase_material
from .schemas import (
    CandidateInput,
    GraphInput,
    MaterialInput,
    MaterialUpdate,
    QuestionInput,
    QuestionView,
    ReviewInput,
)


def install_legacy_content_routes(app):
    @app.get("/api/v1/materials", tags=["个人资料"])
    def materials(user=Depends(student), db=Depends(get_db)):
        rows = db.scalars(
            select(Material).where(Material.user_id == user.id, Material.deleted.is_(False))
        ).all()
        return {"items": [material_view(m, db) for m in rows]}

    @app.post("/api/v1/materials", status_code=201, tags=["个人资料"])
    def add_material(body: MaterialInput, user=Depends(student), db=Depends(get_db)):
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        row = Material(id=str(uuid4()), user_id=user.id, **body.model_dump(), confirmed=False, deleted=False)
        db.add(row)
        db.commit()
        return material_view(row, db)

    @app.patch("/api/v1/materials/{material_id}", tags=["个人资料"])
    def update_material(material_id: str, body: MaterialUpdate, user=Depends(student), db=Depends(get_db)):
        row = db.scalar(
            select(Material).where(Material.id == material_id, Material.user_id == user.id).with_for_update()
        )
        if not row:
            fail(404, "资源不存在")
        if row.deleted:
            fail(404, "资源不存在")
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        row.knowledge_id, row.confirmed = body.knowledge_id, body.confirmed
        from .retrieval import invalidate_material_index

        invalidate_material_index(db, row.id)
        from .db import SourceChunk

        for chunk in db.scalars(select(SourceChunk).where(SourceChunk.material_id == row.id)):
            chunk.knowledge_id = body.knowledge_id
            chunk.status = "confirmed" if body.confirmed else "pending"
        db.commit()
        return material_view(row, db)

    @app.delete("/api/v1/materials/{material_id}", status_code=204, tags=["个人资料"])
    def delete_material(material_id: str, user=Depends(student), db=Depends(get_db)):
        row = owned(db, Material, material_id, user)
        erase_material(db, row)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/v1/admin/graphs", status_code=201, tags=["内容维护"])
    def publish_graph(body: GraphInput, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        if db.scalar(select(CurriculumPoint.id).limit(1)):
            fail(409, "408 课程已启用，请通过 /admin/curriculum 一并校验章节与预设题后发布")
        nodes = [n.model_dump() for n in body.nodes]
        try:
            validate_graph(nodes)
        except ValueError as e:
            fail(422, str(e))
        ids = {n["id"] for n in nodes}
        referenced = set(db.scalars(select(Question.knowledge_id))) | set(
            db.scalars(select(Material.knowledge_id).where(Material.deleted.is_(False)))
        )
        if not referenced <= ids:
            fail(409, "不能移除已被题目或个人资料引用的知识点")
        db.add(Graph(version=body.version, nodes=nodes))
        db.add(audit_record(user, "publish_graph", body.version, request.app.state.clock()))
        db.commit()
        return {"version": body.version, "nodes": nodes}

    @app.get("/api/v1/admin/questions", tags=["内容维护"])
    def list_questions(user=Depends(maintainer), db=Depends(get_db)):
        return {
            "items": [
                {**question_view(q), "answer": q.answer, "explanation": q.explanation, "source": q.source}
                for q in db.scalars(select(Question).order_by(Question.key))
            ]
        }

    @app.post("/api/v1/admin/questions", status_code=201, response_model=QuestionView, tags=["内容维护"])
    def create_question(body: QuestionInput, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        if body.knowledge_id not in {n["id"] for n in active_graph(db).nodes}:
            fail(422, "知识点不存在")
        latest = db.scalar(select(func.max(Question.version)).where(Question.question_id == body.question_id))
        if latest is not None and body.version <= latest:
            fail(409, "题目修订必须使用递增的新版本")
        row = Question(key=f"{body.question_id}:v{body.version}", **body.model_dump(), status="draft")
        db.add(row)
        db.add(audit_record(user, "create_question", row.key, request.app.state.clock()))
        db.commit()
        return question_view(row)

    @app.post("/api/v1/admin/questions/{question_key}/candidates", status_code=201, tags=["内容维护"])
    def add_candidate(
        question_key: str,
        body: CandidateInput,
        ctx=Depends(maintainer_session),
    ):
        q = ctx.db.get(Question, question_key)
        if not q:
            fail(404, "题目不存在")
        if q.status not in ("draft", "pending_review"):
            fail(409, "已发布或停用的版本不可重新标注，请建立新题目版本")
        if (q.question_id, q.version) != (body.question_id, body.question_version):
            fail(409, "候选标签的题目版本不匹配")
        row = Annotation(
            id=str(uuid4()),
            question_key=q.key,
            payload=body.model_dump(mode="json"),
            provider="manual-prototype",
            rule_version="bloom-0.1",
            created_at=ctx.request.app.state.clock(),
        )
        ctx.db.add(row)
        q.status = "pending_review"
        ctx.db.add(audit_record(ctx.user, "add_candidate", row.id, ctx.request.app.state.clock()))
        ctx.db.commit()
        return {
            "id": row.id,
            "question_key": q.key,
            "provider": row.provider,
            "rule_version": row.rule_version,
            "candidate": row.payload,
            "notice": "手动录入候选，未调用 LLM；仍须独立执行审核。",
        }

    @app.get("/api/v1/admin/candidates", tags=["内容维护"])
    def list_candidates(user=Depends(maintainer), db=Depends(get_db)):
        rows = db.execute(
            select(Annotation, Review).outerjoin(Review, Review.annotation_id == Annotation.id)
        ).all()
        return {
            "items": [
                {
                    "id": a.id,
                    "question_key": a.question_key,
                    "candidate": a.payload,
                    "provider": a.provider,
                    "rule_version": a.rule_version,
                    "created_at": a.created_at,
                    "decision": r.decision if r else "pending",
                    "needs_attention": a.payload.get("confidence", 0) < 0.8
                    or bool(a.payload.get("ambiguity_note", "").strip()),
                    "review": {
                        "reviewer_id": r.reviewer_id,
                        "reason": r.reason,
                        "final_level": r.final_level,
                        "content_verified": r.content_verified,
                        "created_at": r.created_at,
                    }
                    if r
                    else None,
                }
                for a, r in rows
            ]
        }

    @app.post("/api/v1/admin/candidates/{candidate_id}/review", tags=["内容维护"])
    def review(candidate_id: str, body: ReviewInput, ctx=Depends(maintainer_session)):
        a = ctx.db.get(Annotation, candidate_id)
        if not a:
            fail(404, "候选不存在")
        q = ctx.db.get(Question, a.question_key)
        if ctx.db.scalar(select(Review).where(Review.annotation_id == a.id)) or q.status != "pending_review":
            fail(409, "候选已审核或题目版本已锁定")
        # Compare-and-set the publication state in the same transaction as review.
        # Two concurrent approvals for different candidates cannot both become effective.
        values = {"status": "draft"}
        if body.decision == "approve":
            if body.final_level is None:
                fail(422, "批准标签必须指定最终认知层级")
            values = {"status": "published", "level": body.final_level.value}
        changed = ctx.db.execute(
            update(Question)
            .where(Question.key == q.key, Question.status == "pending_review")
            .values(**values)
        )
        if changed.rowcount != 1:
            fail(409, "题目状态已变化，请刷新审核记录")
        ctx.db.add(
            Review(
                id=str(uuid4()),
                annotation_id=a.id,
                reviewer_id=ctx.user.id,
                decision=body.decision,
                reason=body.reason,
                final_level=body.final_level.value if body.final_level else None,
                content_verified=body.content_verified,
                created_at=ctx.request.app.state.clock(),
            )
        )
        ctx.db.add(audit_record(ctx.user, "review_" + body.decision, a.id, ctx.request.app.state.clock()))
        ctx.db.commit()
        return {"question_key": q.key, "status": q.status, "level": q.level}

    @app.post("/api/v1/admin/questions/{question_key}/retire", tags=["内容维护"])
    def retire(question_key: str, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        q = db.get(Question, question_key)
        if not q:
            fail(404, "题目不存在")
        q.status = "retired"
        existing_reason = db.get(SystemSetting, "retired:" + q.key)
        if not existing_reason:
            db.add(
                SystemSetting(
                    key="retired:" + q.key,
                    data={
                        "reason": "维护者停用此版本；旧版接口未补充详细说明",
                        "actor": user.id,
                        "at": request.app.state.clock(),
                    },
                )
            )
        db.add(audit_record(user, "retire_question", q.key, request.app.state.clock()))
        db.commit()
        return {"question_key": q.key, "status": q.status}

    @app.get("/api/v1/admin/audit", tags=["内容维护"])
    def audit_log(limit: int = Query(100, ge=1, le=200), user=Depends(current_user), db=Depends(get_db)):
        if user.role not in ("maintainer", "admin"):
            fail(403, "此操作需要维护或管理权限")
        rows = db.scalars(select(Audit).order_by(Audit.at.desc()).limit(limit)).all()
        return {
            "items": [
                {"id": a.id, "actor_id": a.actor_id, "action": a.action, "target": a.target, "at": a.at}
                for a in rows
            ]
        }
