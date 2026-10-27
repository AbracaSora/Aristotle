"""Versioned rule baseline. All timestamps are UTC Unix seconds."""

from collections import defaultdict

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


def diagnose(nodes: list[dict], attempts: list[dict], now: float) -> list[dict]:
    """Use the first valid attempt per stable question ID inside the 14-day window.

    New question versions do not create independent evidence for the same question.
    Callers exclude retired/invalid content. History itself remains immutable.
    """
    by_id = {n["id"]: n for n in nodes}
    grouped = defaultdict(list)
    latest_attempts = {}
    seen = set()
    for a in sorted(attempts, key=lambda a: (a["at"], a["id"])):
        if not now - WINDOW_SECONDS <= a["at"] <= now:
            continue
        if a["knowledge_id"] in by_id:
            key = (a["knowledge_id"], a["level"])
            latest_attempts[key] = max(a["at"], latest_attempts.get(key, a["at"]))
        if a["question_id"] in seen or a["knowledge_id"] not in by_id:
            continue
        seen.add(a["question_id"])
        grouped[a["knowledge_id"]].append(a)
    states = {}
    for key in validate_graph(nodes):
        evidence = grouped[key]
        rate = sum(a["correct"] for a in evidence) / len(evidence) if evidence else None
        missing = [p for p in by_id[key]["prerequisites"] if states[p]["status"] != "provisional"]
        status = (
            "insufficient"
            if len(evidence) < 3
            else ("provisional" if rate >= 0.8 and not missing else "needs_review")
        )
        cognitive = []
        for level in LEVELS:
            rows = [a for a in evidence if a["level"] == level]
            cognitive.append(
                {
                    "level": level,
                    "count": len(rows),
                    "correct_rate": sum(a["correct"] for a in rows) / len(rows) if rows else None,
                    "evidence_status": "sufficient" if len(rows) >= 3 else "insufficient",
                    "last_at": latest_attempts.get((key, level)),
                }
            )
        states[key] = {
            "knowledge_id": key,
            "name": by_id[key]["name"],
            "status": status,
            "evidence_count": len(evidence),
            "correct_rate": rate,
            "unmet_prerequisites": missing,
            "cognitive": cognitive,
        }
    return list(states.values())


def recommend(nodes, states, questions, attempts, knowledge_id=None, level=None):
    """Select only prerequisite-eligible nodes and published first-release labels.

    Returns a decision even when content is absent; callers must surface that gap.
    Explicit targets can never bypass prerequisite constraints.
    """
    state_by_id = {s["knowledge_id"]: s for s in states}
    order = validate_graph(nodes)
    if knowledge_id is not None and knowledge_id not in state_by_id:
        raise ValueError("目标知识点不存在")
    eligible = [k for k in order if not state_by_id[k]["unmet_prerequisites"]]
    if knowledge_id is not None:
        if knowledge_id not in eligible:
            raise ValueError("先修证据不足，请先完成先修知识点的诊断或巩固")
        eligible = [knowledge_id]
    priority = {"needs_review": 0, "insufficient": 1, "provisional": 2}

    def rank(key):
        cognitive = {c["level"]: c for c in state_by_id[key]["cognitive"]}
        available = {q["level"] for q in questions if q["knowledge_id"] == key and q["level"] in LEVELS}
        has_gap = any(
            cognitive[lv]["evidence_status"] == "insufficient" or (cognitive[lv]["correct_rate"] or 0) < 0.8
            for lv in available
        )
        recent = max((a["at"] for a in attempts if a["knowledge_id"] == key), default=-1)
        return priority[state_by_id[key]["status"]], not has_gap, recent, order.index(key)

    eligible.sort(key=rank)
    target = eligible[0]
    available = [q for q in questions if q["knowledge_id"] == target and q["level"] in LEVELS]
    cognitive = {c["level"]: c for c in state_by_id[target]["cognitive"]}
    available_levels = [lv for lv in LEVELS if any(q["level"] == lv for q in available)]
    chosen_level = level or next(
        (
            lv
            for lv in available_levels
            if cognitive[lv]["evidence_status"] == "insufficient"
            or (cognitive[lv]["correct_rate"] or 0) < 0.8
        ),
        available_levels[0] if available_levels else "understand",
    )
    last_seen = {}
    for a in attempts:
        last_seen[a["question_id"]] = max(a["at"], last_seen.get(a["question_id"], 0))
    candidates = [q for q in available if q["level"] == chosen_level]
    candidates.sort(key=lambda q: (last_seen.get(q["question_id"], -1), q["key"]))
    selected = candidates[:3]
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
