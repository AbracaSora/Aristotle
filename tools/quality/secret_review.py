"""Apply explicit per-finding reviews; unreviewed or changed findings always fail."""


def identity(path, item):
    return path, item["line_number"], item["type"], item["hashed_secret"]


def review_findings(results, reviews):
    accepted = {
        identity(item["file"], item): item
        for item in reviews
        if item.get("disposition") == "not_secret" and item.get("reason")
    }
    reviewed, unresolved = [], []
    for path, findings in results.items():
        for item in findings:
            match = accepted.get(identity(path, item))
            view = {"file": path, "line": item["line_number"], "type": item["type"]}
            if match:
                reviewed.append({**view, "reason": match["reason"]})
            else:
                unresolved.append(view)
    return {"reviewed": reviewed, "unresolved": unresolved, "passed": not unresolved}
