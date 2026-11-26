from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .database_connection import create_database_engine as create_database_engine
from .database_connection import open_database as open_database
from .vector_type import Vector


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[float] = mapped_column(Float)


class Graph(Base):
    __tablename__ = "graphs"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String, unique=True)
    nodes: Mapped[list] = mapped_column(JSON)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("question_id", "version"),)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    question_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    knowledge_id: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset: Mapped[str] = mapped_column(String, default="team-authored")


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    question_key: Mapped[str] = mapped_column(ForeignKey("questions.key"))
    payload: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String)
    rule_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"), unique=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    final_level: Mapped[str | None] = mapped_column(String, nullable=True)
    content_verified: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[float] = mapped_column(Float)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String)
    graph_version: Mapped[str] = mapped_column(String)
    decision: Mapped[dict] = mapped_column(JSON)
    evidence_snapshot: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)


class TaskQuestion(Base):
    __tablename__ = "task_questions"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    question_key: Mapped[str] = mapped_column(ForeignKey("questions.key"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "question_key"),
        UniqueConstraint("user_id", "task_id", "submission_id", name="uq_attempt_task_submission"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    question_key: Mapped[str] = mapped_column(ForeignKey("questions.key"))
    submission_id: Mapped[str] = mapped_column(String)
    selected: Mapped[str] = mapped_column(String)
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[float] = mapped_column(Float)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    knowledge_id: Mapped[str] = mapped_column(String)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    external_processing_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    at: Mapped[float] = mapped_column(Float)


class LearningScope(Base):
    __tablename__ = "learning_scopes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    knowledge_ids: Mapped[list] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(Text)


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    scope_id: Mapped[str] = mapped_column(ForeignKey("learning_scopes.id"))


class DiagnosticRound(Base):
    __tablename__ = "diagnostic_rounds"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scope_id: Mapped[str] = mapped_column(ForeignKey("learning_scopes.id"))
    status: Mapped[str] = mapped_column(String)
    blueprint: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)


class TaskProgress(Base):
    __tablename__ = "task_progress"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    scope_id: Mapped[str] = mapped_column(ForeignKey("learning_scopes.id"))
    round_id: Mapped[str | None] = mapped_column(ForeignKey("diagnostic_rounds.id"), nullable=True)
    status: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


class LearningResource(Base):
    __tablename__ = "learning_resources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String)


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    knowledge_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    implementation: Mapped[str] = mapped_column(String)


class ServiceJob(Base):
    __tablename__ = "service_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)


class ContentReport(Base):
    __tablename__ = "content_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    question_key: Mapped[str] = mapped_column(ForeignKey("questions.key"))
    category: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    resolution: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class SourceEmbedding(Base):
    __tablename__ = "source_embeddings"
    __table_args__ = (
        UniqueConstraint("source_key", "namespace"),
        CheckConstraint(
            "(resource_id IS NOT NULL AND material_id IS NULL AND owner_id IS NULL AND chunk_id IS NULL) OR "
            "(resource_id IS NULL AND material_id IS NOT NULL AND owner_id IS NOT NULL)",
            name="embedding_source_owner",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_key: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("learning_resources.id"), nullable=True)
    material_id: Mapped[str | None] = mapped_column(ForeignKey("materials.id"), nullable=True, index=True)
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("source_chunks.id"), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    namespace: Mapped[str] = mapped_column(String, index=True)
    source_hash: Mapped[str] = mapped_column(String)
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(JSON().with_variant(Vector(), "postgresql"))
    created_at: Mapped[float] = mapped_column(Float)


class ModelCall(Base):
    __tablename__ = "model_calls"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String, index=True)
    namespace: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    reserved_requests: Mapped[int] = mapped_column(Integer)
    external_calls: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str] = mapped_column(String, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[float] = mapped_column(Float, index=True)


class CurriculumSubject(Base):
    __tablename__ = "curriculum_subjects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class CurriculumChapter(Base):
    __tablename__ = "curriculum_chapters"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("curriculum_subjects.id"))
    data: Mapped[dict] = mapped_column(JSON)


class CurriculumPoint(Base):
    __tablename__ = "curriculum_points"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("curriculum_chapters.id"))
    graph_version: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float)


class PresetSet(Base):
    __tablename__ = "preset_sets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("curriculum_points.id"))
    question_keys: Mapped[list] = mapped_column(JSON)


class StandardQuestion(Base):
    __tablename__ = "standard_questions"
    key: Mapped[str] = mapped_column(ForeignKey("questions.key"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class PresetTask(Base):
    __tablename__ = "preset_tasks"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    preset_set_id: Mapped[str] = mapped_column(String, primary_key=True)
    preset_set_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)


class FinalTest(Base):
    __tablename__ = "final_tests"
    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_id", "version"),
        UniqueConstraint("user_id", "request_id"),
        CheckConstraint("version > 0", name="positive_test_version"),
        CheckConstraint(
            "status IN ('generating','ready','generation_failed','submitted')", name="test_status"
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("curriculum_points.id"))
    version: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String)
    preset_set_id: Mapped[str] = mapped_column(String)
    preset_set_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    rules: Mapped[dict] = mapped_column(JSON)
    generation_context: Mapped[dict] = mapped_column(JSON)
    questions: Mapped[list] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submission_id: Mapped[str | None] = mapped_column(String, nullable=True)
    submission_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    client_context: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[float | None] = mapped_column(Float, nullable=True)


# A unique partial index protects against different request IDs racing to create sheets.
from sqlalchemy import Index  # noqa: E402

Index(
    "uq_final_test_active",
    FinalTest.user_id,
    FinalTest.knowledge_id,
    unique=True,
    postgresql_where=FinalTest.status.in_(("generating", "ready")),
    sqlite_where=FinalTest.status.in_(("generating", "ready")),
)
