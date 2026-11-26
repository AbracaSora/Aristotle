"""Versioned rule baseline. All timestamps are UTC Unix seconds."""

from collections import defaultdict
from typing import Any, NamedTuple

POLICY_VERSION = "baseline-0.1"
WINDOW_SECONDS = 14 * 24 * 60 * 60
LEVELS = ("remember", "understand", "apply", "analyze")


def validate_graph(nodes: list[dict]) -> list[str]:
    """Validate references and cycles, returning a deterministic topological order."""
    by_id = {n["id"]: n for n in nodes}
    if not nodes or len(by_id) != len(nodes):
        raise ValueError("知识点不能为空，ID 不能重复")
    order, visiting, visited = [], set(), set()

    def visit(key):
        if key not in by_id:
            raise ValueError(f"先修引用不存在：{key}")
        if key in visiting:
            raise ValueError("知识结构含自环或环路")
        if key in visited:
            return
        visiting.add(key)
        for parent in by_id[key]["prerequisites"]:
            visit(parent)
        visiting.remove(key)
        visited.add(key)
        order.append(key)

    for key in by_id:
        visit(key)
    return order


def independent_evidence(attempts, by_id, now):
    grouped = defaultdict(list)
    latest = {}
    seen = set()
    for attempt in sorted(attempts, key=lambda a: (a["at"], a["id"])):
        point = attempt["knowledge_id"]
        if point not in by_id or not now - WINDOW_SECONDS <= attempt["at"] <= now:
            continue
        latest[point, attempt["level"]] = attempt["at"]
        if attempt["question_id"] not in seen:
            seen.add(attempt["question_id"])
            grouped[point].append(attempt)
    return grouped, latest


def correct_rate(rows):
    return sum(a["correct"] for a in rows) / len(rows) if rows else None


def cognitive_evidence(key, evidence, latest):
    dimensions = []
    for level in LEVELS:
        rows = [attempt for attempt in evidence if attempt["level"] == level]
        dimensions.append(
            {
                "level": level,
                "count": len(rows),
                "correct_rate": correct_rate(rows),
                "evidence_status": "sufficient" if len(rows) >= 3 else "insufficient",
                "last_at": latest.get((key, level)),
            }
        )
    return dimensions


def evidence_status(count, rate, missing):
    if count < 3:
        return "insufficient"
    return "provisional" if rate >= 0.8 and not missing else "needs_review"


def diagnose(nodes: list[dict], attempts: list[dict], now: float) -> list[dict]:
    """Use the first valid attempt per stable question ID inside the 14-day window."""
    by_id = {node["id"]: node for node in nodes}
    grouped, latest = independent_evidence(attempts, by_id, now)
    states: dict[str, dict[str, Any]] = {}
    for key in validate_graph(nodes):
        evidence = grouped[key]
        rate = correct_rate(evidence)
        missing = [p for p in by_id[key]["prerequisites"] if states[p]["status"] != "provisional"]
        states[key] = {
            "knowledge_id": key,
            "name": by_id[key]["name"],
            "status": evidence_status(len(evidence), rate, missing),
            "evidence_count": len(evidence),
            "correct_rate": rate,
            "unmet_prerequisites": missing,
            "cognitive": cognitive_evidence(key, evidence, latest),
        }
    return list(states.values())


def dimension_needs_evidence(dimension):
    return dimension["evidence_status"] == "insufficient" or (dimension["correct_rate"] or 0) < 0.8


def eligible_targets(order, states, knowledge_id):
    if knowledge_id is not None and knowledge_id not in states:
        raise ValueError("目标知识点不存在")
    eligible = [key for key in order if not states[key]["unmet_prerequisites"]]
    if knowledge_id is None:
        return eligible
    if knowledge_id not in eligible:
        raise ValueError("先修证据不足，请先完成先修知识点的诊断或巩固")
    return [knowledge_id]


def ranking_key(key, context):
    states, questions, attempts, order = context
    cognitive = {item["level"]: item for item in states[key]["cognitive"]}
    available = {q["level"] for q in questions if q["knowledge_id"] == key and q["level"] in LEVELS}
    has_gap = any(dimension_needs_evidence(cognitive[level]) for level in available)
    recent = max((a["at"] for a in attempts if a["knowledge_id"] == key), default=-1)
    priority = {"needs_review": 0, "insufficient": 1, "provisional": 2}
    return priority[states[key]["status"]], not has_gap, recent, order.index(key)


def choose_level(cognitive, available, explicit):
    if explicit:
        return explicit
    levels = [level for level in LEVELS if any(q["level"] == level for q in available)]
    return next(
        (level for level in levels if dimension_needs_evidence(cognitive[level])),
        levels[0] if levels else "understand",
    )


def select_questions(available, chosen_level, attempts):
    last_seen: dict[str, float] = {}
    for attempt in attempts:
        qid = attempt["question_id"]
        last_seen[qid] = max(attempt["at"], last_seen.get(qid, 0))
    candidates = [q for q in available if q["level"] == chosen_level]
    candidates.sort(key=lambda q: (last_seen.get(q["question_id"], -1), q["key"]))
    return candidates[:3]


class RecommendationEvidence(NamedTuple):
    nodes: list
    states: list
    attempts: list


def recommend(evidence: RecommendationEvidence, questions, knowledge_id=None, level=None):
    """Select a recommendation from the supplied versioned evidence."""
    nodes, states, attempts = evidence
    state_by_id = {state["knowledge_id"]: state for state in states}
    order = validate_graph(nodes)
    eligible = eligible_targets(order, state_by_id, knowledge_id)
    context = (state_by_id, questions, attempts, order)
    target = min(eligible, key=lambda key: ranking_key(key, context))
    available = [q for q in questions if q["knowledge_id"] == target and q["level"] in LEVELS]
    cognitive = {item["level"]: item for item in state_by_id[target]["cognitive"]}
    chosen_level = choose_level(cognitive, available, level)
    selected = select_questions(available, chosen_level, attempts)
    status_text = {"insufficient": "证据不足", "needs_review": "待巩固", "provisional": "初步掌握"}
    return {
        "knowledge_id": target,
        "target_level": chosen_level,
        "question_keys": [q["key"] for q in selected],
        "reason": f"{state_by_id[target]['name']}目前{status_text[state_by_id[target]['status']]}；"
        f"先修约束已满足，安排 {chosen_level} 任务。该结果是规则基线判断。",
        "warnings": (
            [f"目标标签仅有 {len(selected)} 道可用题，未达到 3 道标准关卡"] if len(selected) < 3 else []
        ),
        "policy_version": POLICY_VERSION,
    }
