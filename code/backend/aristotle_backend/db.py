from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


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
        UniqueConstraint("user_id", "submission_id"),
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


def open_database(url: str):
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 15}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=15000")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
