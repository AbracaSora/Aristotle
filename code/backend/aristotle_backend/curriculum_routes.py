"""408 curriculum routes; old diagnostic endpoints keep their existing contract."""

from uuid import uuid4

from fastapi import BackgroundTasks, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.sql.functions import count

from aristotle_backend.learning_context import LearnerAction

from .api_access import student_session
from .curriculum import (
    assert_unlocked,
    fail,
    point_or_404,
    preset_questions,
    preset_task_view,
    progress_views,
    publish_curriculum,
    retry_preset,
    subjects_view,
    summary,
)
from .curriculum_schemas import (
    CreateTest,
    CurriculumPublication,
    PresetTaskView,
    ProgressDetail,
    ProgressSummary,
    QuestionContent,
    QuestionPublic,
    SubjectWithChapters,
    SubmitTest,
    Tag,
    TestCreated,
    TestDetail,
    TestList,
    TestResult,
)
from .db import Audit, CurriculumSubject, FinalTest, StandardQuestion, SystemSetting
from .final_tests import (
    create_test,
    created_view,
    detail_view,
    enrich_feedback,
    own_test,
    run_generation,
    submit_test,
    test_summary,
)


def install_curriculum_routes(app, get_db, student, maintainer):
    @app.post(
        "/api/v1/tasks/{task_id}/retry-preset",
        status_code=201,
        response_model=PresetTaskView,
        tags=["408 课程"],
    )
    def repeat(task_id: str, response: Response, ctx=Depends(student_session)):
        task, created = retry_preset(ctx.db, ctx.user.id, task_id, ctx.request.app.state.clock())
        ctx.db.commit()
        response.status_code = 201 if created else 200
        return preset_task_view(ctx.db, task)

    @app.get("/api/v1/subjects", response_model=list[SubjectWithChapters], tags=["408 课程"])
    def subjects(user=Depends(student), db=Depends(get_db)):
        return subjects_view(db)

    @app.get("/api/v1/tags", response_model=list[Tag], tags=["408 课程"])
    def tags(user=Depends(student), db=Depends(get_db)):
        row = db.get(SystemSetting, "curriculum-tags")
        return row.data["items"] if row else []

    @app.post("/api/v1/admin/curriculum", tags=["408 内容维护"])
    def publish(body: CurriculumPublication, request: Request, user=Depends(maintainer), db=Depends(get_db)):
        try:
            publish_curriculum(db, body, now=request.app.state.clock())
        except ValueError as exc:
            fail(422, str(exc))
        db.add(
            Audit(
                id=str(uuid4()),
                actor_id=user.id,
                action="publish_curriculum",
                target=body.graph_version,
                at=request.app.state.clock(),
            )
        )
        db.commit()
        return {"graph_version": body.graph_version, "knowledge_points": len(body.knowledge_points)}

    @app.get(
        "/api/v1/admin/standard-questions/{question_key}",
        response_model=QuestionContent,
        tags=["408 内容维护"],
    )
    def question_full(question_key: str, user=Depends(maintainer), db=Depends(get_db)):
        row = db.get(StandardQuestion, question_key)
        if not row:
            fail(404, "标准题版本不存在")
        return row.data

    @app.get(
        "/api/v1/knowledge-points/{knowledge_id}/questions",
        response_model=list[QuestionPublic],
        tags=["408 课程"],
    )
    def questions(knowledge_id: str, user=Depends(student), db=Depends(get_db)):
        return preset_questions(db, assert_unlocked(db, user.id, knowledge_id))

    @app.get(
        "/api/v1/knowledge-points/{knowledge_id}/progress",
        response_model=ProgressSummary,
        tags=["408 学习进度"],
    )
    def progress(knowledge_id: str, user=Depends(student), db=Depends(get_db)):
        point_or_404(db, knowledge_id)
        return summary(progress_views(db, user.id)[knowledge_id])

    @app.get(
        "/api/v1/knowledge-points/{knowledge_id}/progress-detail",
        response_model=ProgressDetail,
        tags=["408 学习进度"],
    )
    def progress_detail(knowledge_id: str, user=Depends(student), db=Depends(get_db)):
        point_or_404(db, knowledge_id)
        return progress_views(db, user.id)[knowledge_id]

    @app.get("/api/v1/progress", response_model=list[ProgressSummary], tags=["408 学习进度"])
    def all_progress(subject_id: str | None = None, user=Depends(student), db=Depends(get_db)):
        subjects = subjects_view(db)
        if subject_id is not None:
            row = db.get(CurriculumSubject, subject_id)
            if not row or row.data["status"] != "published":
                fail(404, "科目不存在")
        states = progress_views(db, user.id)
        return [
            summary(states[p["id"]])
            for s in subjects
            if subject_id is None or s["id"] == subject_id
            for c in s["chapters"]
            for p in c["knowledge_points"]
        ]

    install_final_test_routes(app, get_db, student)


def install_final_test_routes(app, get_db, student):
    @app.post(
        "/api/v1/knowledge-points/{knowledge_id}/ai-tests",
        status_code=202,
        response_model=TestCreated,
        tags=["408 最终小测"],
    )
    def new_test(
        knowledge_id: str,
        body: CreateTest,
        background: BackgroundTasks,
        ctx=Depends(student_session),
    ):
        row, created = create_test(
            LearnerAction(ctx.db, ctx.user, ctx.request.app.state.clock()), knowledge_id, body
        )
        ctx.db.commit()
        result = created_view(row)
        if created:
            background.add_task(
                run_generation,
                ctx.request.app.state.sessions,
                row.id,
                getattr(ctx.request.app.state, "model_transport", None),
            )
        return result

    @app.get(
        "/api/v1/knowledge-points/{knowledge_id}/ai-tests", response_model=TestList, tags=["408 最终小测"]
    )
    def tests(
        knowledge_id: str,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        ctx=Depends(student_session),
    ):
        point_or_404(ctx.db, knowledge_id)
        where = (FinalTest.user_id == ctx.user.id, FinalTest.knowledge_id == knowledge_id)
        rows = ctx.db.scalars(
            select(FinalTest).where(*where).order_by(FinalTest.version.desc()).limit(limit).offset(offset)
        )
        return {
            "items": [test_summary(row) for row in rows],
            "total": ctx.db.scalar(select(count()).select_from(FinalTest).where(*where)),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/ai-tests/{test_id}", response_model=TestDetail, tags=["408 最终小测"])
    def detail(test_id: str, user=Depends(student), db=Depends(get_db)):
        return detail_view(own_test(db, user.id, test_id))

    @app.post("/api/v1/ai-tests/{test_id}/submit", response_model=TestResult, tags=["408 最终小测"])
    def submit(test_id: str, body: SubmitTest, ctx=Depends(student_session)):
        result, fresh = submit_test(
            LearnerAction(ctx.db, ctx.user, ctx.request.app.state.clock()), test_id, body
        )
        ctx.db.commit()  # Grade + pass evidence are durable before any feedback I/O.
        if fresh:
            enrich_feedback(
                ctx.request.app.state.sessions,
                test_id,
                getattr(ctx.request.app.state, "model_transport", None),
            )
            ctx.db.expire_all()
            result = own_test(ctx.db, ctx.user.id, test_id).result
        return result
