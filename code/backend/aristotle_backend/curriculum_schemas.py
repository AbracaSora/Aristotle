"""408 handoff v1.5: public content, progress and frozen final-test contracts."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .schemas import Identifier, Input, Level, Text

Key = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}:v[1-9][0-9]*$")]
Status = Literal["draft", "pending_review", "published", "retired"]


class Option(Input):
    id: Identifier
    text: Text = Field(max_length=500)


class Source(Input):
    type: Literal["past_exam", "authored", "ai_generated"]
    title: Text = Field(max_length=1000)
    year: int | None = Field(default=None, ge=1900, le=2200)
    question_number: str | None = None
    url: str | None = None


def validate_option_uniqueness(options):
    if len({o.id for o in options}) != len(options) or len({o.text for o in options}) != len(options):
        raise ValueError("选项 ID 和文本必须唯一")


class QuestionPublic(Input):
    question_id: Identifier
    version: int = Field(ge=1)
    key: Key
    knowledge_id: Identifier
    related_knowledge_ids: list[Identifier] = Field(default_factory=list)
    type: Literal["single_choice"] = "single_choice"
    stem: Text = Field(max_length=5000)
    content_format: Literal["plain_text"] = "plain_text"
    options: list[Option] = Field(min_length=2, max_length=8)
    tag_ids: list[Identifier] = Field(default_factory=list)
    bloom_level: Level | None = None
    secondary_bloom_levels: list[Level] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    source: Source
    review_status: Status
    dataset: Text

    @model_validator(mode="after")
    def coherent(self):
        if self.key != f"{self.question_id}:v{self.version}":
            raise ValueError("题目版本键不匹配")
        validate_option_uniqueness(self.options)
        for values in (self.related_knowledge_ids, self.tag_ids, self.secondary_bloom_levels):
            if len(set(values)) != len(values):
                raise ValueError("标签和关联不能重复")
        if self.knowledge_id in self.related_knowledge_ids or self.bloom_level in self.secondary_bloom_levels:
            raise ValueError("关联不能包含主知识点或主认知层级")
        if self.review_status == "published" and self.bloom_level is None:
            raise ValueError("发布题目必须有确认认知层级")
        return self


class Answer(Input):
    option_id: Identifier


class QuestionContent(QuestionPublic):
    answer: Answer
    explanation: Text = Field(max_length=5000)
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("时间必须为带时区的 ISO 8601") from None
        if parsed.tzinfo is None:
            raise ValueError("时间必须包含时区")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def valid_answer(self):
        if self.answer.option_id not in {o.id for o in self.options}:
            raise ValueError("答案不属于选项")
        return self


class Preset(Input):
    id: Identifier
    version: int = Field(ge=1)
    question_keys: list[Key]

    @model_validator(mode="after")
    def unique_keys(self):
        if len(set(self.question_keys)) != len(self.question_keys):
            raise ValueError("预设题版本不能重复")
        return self


class Subject(Input):
    id: Identifier
    name: Text = Field(max_length=100)
    description: str = ""
    order: int = Field(ge=0)
    status: Literal["draft", "published", "retired"] = "published"


class Chapter(Subject):
    subject_id: Identifier


class KnowledgePoint(Chapter):
    chapter_id: Identifier
    prerequisite_ids: list[Identifier] = Field(default_factory=list)
    tag_ids: list[Identifier] = Field(default_factory=list)
    preset_set: Preset


class PresetPublic(Preset):
    question_count: int


class KnowledgePointPublic(KnowledgePoint):
    preset_set: PresetPublic
    updated_at: str


class ChapterWithKnowledge(Chapter):
    knowledge_points: list[KnowledgePointPublic]


class SubjectWithChapters(Subject):
    chapters: list[ChapterWithKnowledge]


class Tag(Input):
    id: Identifier
    name: Text


class CurriculumPublication(Input):
    graph_version: Identifier
    subjects: list[Subject] = Field(min_length=1, max_length=4)
    chapters: list[Chapter]
    knowledge_points: list[KnowledgePoint] = Field(min_length=1, max_length=250)
    tags: list[Tag] = Field(default_factory=list)
    # Full, explicitly sourced metadata for existing published question versions.
    questions: list[QuestionContent]


class Rules(Input):
    question_count: int = Field(ge=1, le=20, strict=True)
    pass_score: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)


class CreateTest(Input):
    request_id: Identifier
    rules: Rules


class TestAnswer(Input):
    question_key: Key
    selected_option_id: Identifier


class ClientContext(Input):
    elapsed_seconds: float | None = Field(default=None, ge=0, le=86400, allow_inf_nan=False)
    used_hint: bool | None = None
    learning_goal: str | None = Field(default=None, max_length=500)


class SubmitTest(Input):
    submission_id: Identifier
    answers: list[TestAnswer] = Field(min_length=1, max_length=20)
    client_context: ClientContext | None = None


class ProgressSummary(BaseModel):
    latest_correct_count: int
    required_correct_count: int
    prerequisite_qualified: bool
    knowledge_id: str
    status: Literal["locked", "available", "completed", "mastered"]
    unlocked: bool
    completed_count: int
    total_count: int
    unmet_prerequisite_ids: list[str]
    ai_test_eligible: bool
    passed_test_id: str | None


class AITestEligibility(BaseModel):
    eligible: bool
    latest_test_id: str | None
    passed_test_id: str | None


class CompletionEvent(BaseModel):
    event_id: str
    type: Literal["ai_test_submitted", "knowledge_mastered"]
    knowledge_id: str
    occurred_at: str


class LearningFeedbackView(BaseModel):
    error_code: str | None = None
    source: Literal["rule", "ai"]
    status: Literal["pending", "complete", "fallback"]
    summary: str
    suggestions: list[str]
    history_count: int


class TestQuestionFeedback(BaseModel):
    question_key: str
    selected_option_id: str
    correct: bool
    answer: Answer
    explanation: str


class TestError(BaseModel):
    code: str
    message: str


class ProgressDetail(BaseModel):
    latest_correct_count: int
    required_correct_count: int
    prerequisite_qualified: bool
    knowledge_id: str
    policy_version: str
    preset_set_id: str
    preset_set_version: int
    mastery_status: Literal["new", "learning", "covered", "mastered"]
    unlocked: bool
    unmet_prerequisite_ids: list[str]
    preset_total: int
    preset_completed: int
    completion_rate: float | None
    attempt_count: int
    correct_attempt_count: int
    accuracy: float | None
    ai_test: AITestEligibility
    updated_at: str


class QuestionFeedback(BaseModel):
    attempt_id: str
    question_key: str
    selected_option_id: str
    correct: bool
    answer: Answer
    explanation: str
    replayed: bool
    created_at: str
    events: list[CompletionEvent] = Field(default_factory=list)


class PresetTaskView(BaseModel):
    id: str
    mode: Literal["practice"]
    activity: Literal["preset_practice"]
    graph_version: str
    knowledge_id: str
    preset_set_id: str
    preset_set_version: int
    question_keys: list[str]
    questions: list[QuestionPublic]
    attempts: list[QuestionFeedback]
    next_question_key: str | None
    policy_version: str
    created_at: float  # Existing task time unit remains Unix seconds.


class TestCreated(BaseModel):
    test_id: str
    knowledge_id: str
    version: int
    status: Literal["generating", "ready", "generation_failed", "submitted"]
    created_at: str


class TestSummary(TestCreated):
    score: float | None
    passed: bool | None
    submitted_at: str | None


class TestList(BaseModel):
    items: list[TestSummary]
    total: int
    limit: int
    offset: int


class TestResult(BaseModel):
    test_id: str
    status: Literal["submitted"]
    score: float
    passed: bool
    knowledge_status: Literal["completed", "mastered"]
    submitted_at: str
    replayed: bool
    feedback: list[TestQuestionFeedback]
    learning_feedback: LearningFeedbackView
    events: list[CompletionEvent]


class TestDetail(TestCreated):
    questions: list[QuestionPublic]
    rules: Rules | None
    result: TestResult | None
    error: TestError | None
