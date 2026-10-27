import pytest
from aristotle_core.policy import WINDOW_SECONDS, diagnose, recommend, validate_graph

NOW = 2_000_000_000
NODES = [
    {"id": "root", "name": "基础", "prerequisites": []},
    {"id": "child", "name": "应用", "prerequisites": ["root"]},
]


def evidence(qid, correct=True, kid="root", at=NOW - 10, level="remember", row_id=None):
    return {
        "id": row_id or qid,
        "question_id": qid,
        "knowledge_id": kid,
        "at": at,
        "correct": correct,
        "level": level,
    }


@pytest.mark.parametrize(
    "nodes",
    [
        [],
        [{"id": "a", "prerequisites": ["a"]}],
        [{"id": "a", "prerequisites": ["b"]}, {"id": "b", "prerequisites": ["a"]}],
        [{"id": "a", "prerequisites": ["missing"]}],
        [{"id": "a", "prerequisites": []}, {"id": "a", "prerequisites": []}],
    ],
)
def test_invalid_graphs(nodes):
    with pytest.raises(ValueError):
        validate_graph(nodes)


def test_prerequisites_and_cognitive_dimensions_need_independent_evidence():
    attempts = [evidence(str(i), kid="child", level="apply") for i in range(3)]
    root, child = diagnose(NODES, attempts, NOW)
    assert root["status"] == "insufficient"
    assert child["correct_rate"] == 1
    assert child["status"] == "needs_review"
    assert child["unmet_prerequisites"] == ["root"]
    assert child["cognitive"][0]["count"] == 0
    assert child["cognitive"][2]["count"] == 3


def test_first_wrong_answer_cannot_be_erased_by_repetition_or_question_revision():
    attempts = [
        evidence("same", False, at=NOW - 30),
        evidence("same", True, at=NOW - 20, row_id="revision-v2"),
        evidence("other"),
        evidence("third"),
    ]
    state = diagnose(NODES, attempts, NOW)[0]
    assert state["evidence_count"] == 3
    assert state["correct_rate"] == pytest.approx(2 / 3)
    assert state["status"] == "needs_review"


def test_window_boundary_and_future_records():
    rows = [
        evidence("old", at=NOW - WINDOW_SECONDS - 1),
        evidence("boundary", at=NOW - WINDOW_SECONDS),
        evidence("future", at=NOW + 1),
        evidence("recent"),
    ]
    state = diagnose(NODES, rows, NOW)[0]
    assert state["evidence_count"] == 2
    assert state["status"] == "insufficient"


def test_repeated_answer_updates_last_attempt_time_without_changing_first_evidence():
    rows = [evidence("same", False, at=NOW - 20), evidence("same", True, at=NOW - 1, row_id="retry")]
    state = diagnose(NODES, rows, NOW)[0]
    assert state["evidence_count"] == 1
    assert state["correct_rate"] == 0
    assert state["cognitive"][0]["last_at"] == NOW - 1


def test_mastery_requires_eighty_percent():
    rows = [evidence(str(i), correct=i != 0) for i in range(5)]
    assert diagnose(NODES, rows, NOW)[0]["status"] == "provisional"
    assert diagnose(NODES, rows[:4], NOW)[0]["status"] == "needs_review"


def test_recommendation_cannot_bypass_prerequisites_or_silently_change_label():
    states = diagnose(NODES, [], NOW)
    with pytest.raises(ValueError):
        recommend(NODES, states, [], [], knowledge_id="child")
    questions = [{"key": "a:v1", "question_id": "a", "knowledge_id": "root", "level": "remember"}]
    decision = recommend(NODES, states, questions, [], level="analyze")
    assert decision["target_level"] == "analyze"
    assert decision["question_keys"] == []
    assert decision["warnings"]


def test_unseen_questions_are_preferred_and_four_level_inventory_gap_is_recommended():
    rows = [evidence(str(i)) for i in range(3)] + [
        evidence("c" + str(i), kid="child", level="apply") for i in range(3)
    ]
    states = diagnose(NODES, rows, NOW)
    questions = [
        {"key": "new:v1", "question_id": "new", "knowledge_id": "child", "level": "analyze"},
        {"key": "0:v1", "question_id": "0", "knowledge_id": "root", "level": "remember"},
    ]
    decision = recommend(NODES, states, questions, rows)
    assert decision["knowledge_id"] == "child"
    assert decision["target_level"] == "analyze"
