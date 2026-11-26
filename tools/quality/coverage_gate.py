"""Measure changed lines against HEAD, including not-yet-tracked production files."""

import difflib
import json
import subprocess

from coverage.parser import PythonParser


def added_lines(before, after):
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    return {
        line + 1
        for tag, _, _, first, last in matcher.get_opcodes()
        if tag in ("insert", "replace")
        for line in range(first, last)
    }


def changed_coverage(root, files, report, base="HEAD"):
    results = []
    for name, source in files.items():
        previous = subprocess.run(
            ["git", "show", base + ":" + name], cwd=root, capture_output=True, text=True, check=False
        )
        changed = added_lines(previous.stdout if previous.returncode == 0 else "", source)
        data = report["files"].get(name)
        if not changed:
            results.append({"file": name, "changed_executable": 0, "covered": 0, "percent": 100})
            continue
        if data is None:
            parser = PythonParser(text=source)
            parser.parse_source()
            results.append(
                {
                    "file": name,
                    "status": "missing_coverage",
                    "percent": 0,
                    "changed_executable": len(changed & parser.statements),
                    "covered": 0,
                }
            )
            continue
        executed, missing = set(data["executed_lines"]), set(data["missing_lines"])
        relevant = changed & (executed | missing)
        covered = relevant & executed
        results.append(
            {
                "file": name,
                "changed_executable": len(relevant),
                "covered": len(covered),
                "percent": 100 * len(covered) / len(relevant) if relevant else 100,
            }
        )
    count = sum(item.get("changed_executable", 0) for item in results)
    hits = sum(item.get("covered", 0) for item in results)
    return {
        "files": results,
        "changed_executable": count,
        "covered": hits,
        "percent": 100 * hits / count if count else 100,
    }


def inspect_coverage(root, files, path, core, base="HEAD"):
    if not path.is_file():
        return {"status": "not_run", "passed": False}
    report = json.loads(path.read_text())
    changed = changed_coverage(root, files, report, base)
    branches = []
    for name in core:
        summary = report["files"].get(name, {}).get("summary", {})
        total = summary.get("num_branches", 0)
        percent = 100 * summary.get("covered_branches", 0) / total if total else 0
        branches.append({"file": name, "percent": percent, "branches": total})
    missing = any(item.get("status") == "missing_coverage" for item in changed["files"])
    return {
        "status": "measured",
        "changed": changed,
        "core_branches": branches,
        "passed": not missing and changed["percent"] >= 80 and all(x["percent"] >= 80 for x in branches),
    }
