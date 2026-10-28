from typing import Annotated, Literal

from pydantic import Field

from .schemas import Identifier, Input, Level, Text


class ScopeChoice(Input):
    scope_id: Identifier


class DiagnosticInput(Input):
    knowledge_id: Identifier | None = None
    target_level: Literal["remember", "understand", "apply", "analyze"] | None = None


class TaskAction(Input):
    action: Literal["accept", "start", "complete", "skip", "replace"]
    reason: Annotated[str, Field(max_length=1000)] = ""


class ImportInput(Input):
    source_type: Literal["text", "pdf_mock"]
    title: Annotated[Text, Field(max_length=80)]
    text: Annotated[str, Field(max_length=20000)] = ""
    scenario: Literal["normal", "scanned", "encrypted", "oversize", "timeout"] = "normal"


class ChunkChoice(Input):
    knowledge_id: Identifier
    status: Literal["confirmed", "rejected", "pending"]


class ModelJobInput(Input):
    scenario: Literal["normal", "timeout", "rate_limited", "invalid_output", "stale_version"] = "normal"
    suggested_level: Level = Level.understand


class ReportInput(Input):
    question_key: str
    category: Literal["answer", "explanation", "label"]
    message: Annotated[Text, Field(max_length=1000)]


class ReportResolution(Input):
    action: Literal["retire", "resolve", "dismiss"]
    reason: Annotated[Text, Field(max_length=1000)]


class ProviderSettings(Input):
    mode: Literal["mock", "disabled"] = "mock"
    model_name: Literal["mock-bloom-v1"] = "mock-bloom-v1"
    timeout_seconds: int = Field(default=30, ge=1, le=30)
    retries: int = Field(default=1, ge=0, le=1)
    total_budget_seconds: int = Field(default=65, ge=1, le=65)
    daily_annotation_limit: int = Field(default=200, ge=1, le=200)


class RoleChange(Input):
    role: Literal["student", "maintainer", "admin"]
