from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Level(str, Enum):
    remember = "remember"
    understand = "understand"
    apply = "apply"
    analyze = "analyze"
    evaluate = "evaluate"
    create = "create"


class Login(Input):
    username: Annotated[Text, Field(max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=200)]


class Node(Input):
    id: Identifier
    name: Annotated[Text, Field(max_length=100)]
    prerequisites: list[Identifier] = Field(default_factory=list, max_length=100)


class GraphInput(Input):
    version: Identifier
    nodes: list[Node] = Field(min_length=1, max_length=200)


class QuestionInput(Input):
    question_id: Identifier
    version: int = Field(ge=1)
    knowledge_id: Identifier
    prompt: Annotated[Text, Field(max_length=5000)]
    options: list[Annotated[Text, Field(max_length=500)]] = Field(min_length=2, max_length=8)
    answer: Annotated[Text, Field(max_length=500)]
    explanation: Annotated[Text, Field(max_length=5000)]
    source: Annotated[Text, Field(max_length=1000)]

    @model_validator(mode="after")
    def valid_options(self):
        if len(set(self.options)) != len(self.options) or self.answer not in self.options:
            raise ValueError("选项必须唯一，标准答案必须属于选项")
        return self


class CandidateInput(Input):
    question_id: Identifier
    question_version: int = Field(ge=1)
    primary_level: Level
    secondary_levels: list[Level] = Field(default_factory=list, max_length=5)
    rationale: Annotated[Text, Field(max_length=3000)]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    ambiguity_note: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def valid_secondary(self):
        if self.primary_level in self.secondary_levels or len(set(self.secondary_levels)) != len(
            self.secondary_levels
        ):
            raise ValueError("次标签不能重复或包含主标签")
        return self


class ReviewInput(Input):
    decision: Literal["approve", "reject"]
    reason: Annotated[Text, Field(max_length=2000)]
    final_level: Level | None = None
    content_verified: bool = False

    @model_validator(mode="after")
    def require_content_review(self):
        if self.decision == "approve" and (not self.content_verified or self.final_level is None):
            raise ValueError("批准前需核验答案和解析，并确认最终认知标签")
        return self


class TaskInput(Input):
    mode: Literal["diagnostic", "practice"] = "practice"
    knowledge_id: Identifier | None = None
    target_level: Literal["remember", "understand", "apply", "analyze"] | None = None


class AttemptInput(Input):
    question_key: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}:v[1-9][0-9]*$")]
    selected: Annotated[Text, Field(max_length=500)]
    submission_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")]


class MaterialInput(Input):
    title: Annotated[Text, Field(max_length=80)]
    text: Annotated[Text, Field(max_length=20000)]
    knowledge_id: Identifier


class MaterialUpdate(Input):
    knowledge_id: Identifier
    confirmed: bool


class UserView(BaseModel):
    id: str
    username: str
    role: Literal["student", "maintainer"]


class ErrorField(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorDetail(BaseModel):
    message: str
    fields: list[ErrorField] | None = None


class ErrorView(BaseModel):
    error: ErrorDetail


class LoginView(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_at: float
    user: UserView


class CognitiveView(BaseModel):
    level: Level
    count: int
    correct_rate: float | None
    evidence_status: Literal["sufficient", "insufficient"]
    last_at: float | None


class KnowledgeStateView(BaseModel):
    knowledge_id: str
    name: str
    status: Literal["insufficient", "needs_review", "provisional"]
    evidence_count: int
    correct_rate: float | None
    unmet_prerequisites: list[str]
    cognitive: list[CognitiveView]


class LearningStateView(BaseModel):
    graph_version: str
    policy_version: str
    window_days: int
    states: list[KnowledgeStateView]
    notice: str


class QuestionView(BaseModel):
    key: str
    question_id: str
    version: int
    knowledge_id: str
    prompt: str
    options: list[str]
    level: Level | None
    status: Literal["draft", "pending_review", "published", "retired"]
    dataset: str


class AttemptView(BaseModel):
    id: str
    task_id: str
    question_key: str
    submission_id: str
    selected: str
    correct: bool
    created_at: float
    answer: str
    explanation: str
    level: Level
    question_version: int
    content_status: str
    replayed: bool = False


class TaskView(BaseModel):
    id: str
    mode: Literal["diagnostic", "practice"]
    graph_version: str
    created_at: float
    knowledge_id: str
    target_level: Level
    question_keys: list[str]
    reason: str
    warnings: list[str]
    policy_version: str
    material_ids: list[str]
    status: Literal["ready", "material_review", "content_unavailable"]
    questions: list[QuestionView]
    materials: list[dict]
    attempts: list[AttemptView]
    evidence_snapshot: list[KnowledgeStateView]
    notice: str
