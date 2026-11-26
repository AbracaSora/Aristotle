"""Guardrails must reject actual violations, tool crashes and uncovered changes."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"tools/quality/{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_structural_thresholds_detect_real_function_not_comments():
    metrics = module("structure_metrics")
    limits = {"TH-01": 40, "TH-02": 10, "TH-03": 15, "TH-04": 3, "TH-05": 4, "TH-06": 400, "TH-07": 3}
    source = "def invalid(a,b,c,d,e):\n    if a and b and c and d:\n        return e\n"
    rows, findings = metrics.inspect_source("fixture.py", source, limits)
    assert {item["rule"] for item in findings} == {"TH-05", "TH-07"}
    assert rows[0]["TH-01"] == 3
    assert rows[0]["TH-05"] == 5


def test_nested_callable_has_independent_length_and_import_cycle_is_detected():
    metrics = module("structure_metrics")
    import_graph = module("import_graph")
    import ast

    source = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
    assert metrics.effective_lines(ast.parse(source).body[0], source) == 2
    graph = import_graph.inspect_imports(
        {
            "code/backend/aristotle_backend/a.py": "from .b import run\n",
            "code/backend/aristotle_backend/b.py": "from .a import run\n",
        }
    )
    assert graph["cycles"] == [["aristotle_backend.a", "aristotle_backend.b", "aristotle_backend.a"]]


def test_added_lines_include_entire_new_file_and_uncovered_change_fails(tmp_path):
    gate = module("coverage_gate")
    assert gate.added_lines("", "a\nb\n") == {1, 2}
    assert gate.added_lines("a\nb\n", "a\nc\n") == {2}
    result = gate.changed_coverage(
        tmp_path, {"new.py": "a\nb\n"}, {"files": {"new.py": {"executed_lines": [1], "missing_lines": [2]}}}
    )
    assert result["percent"] == 50
    assert result["files"][0]["changed_executable"] == 2


def test_scanner_crash_is_never_reported_as_clean_scan(tmp_path):
    import sys

    import pytest

    spec = importlib.util.spec_from_file_location("scan_quality", ROOT / "scripts/scan_quality.py")
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    with pytest.raises(RuntimeError, match="failed to execute"):
        scanner.run_scan([sys.executable, "-c", "raise SystemExit(32)"], tmp_path, "pylint")
    assert not (tmp_path / "pylint.json").exists()


def test_installer_does_not_inherit_nested_endpoint_complexity():
    import ast

    metrics = module("structure_metrics")
    source = "def install():\n    def endpoint(x):\n        if x:\n            return 1\n        return 0\n    return endpoint\n"
    root = ast.parse(source).body[0]
    assert metrics.own_cognitive_complexity(root) == 0
    assert metrics.own_cognitive_complexity(root.body[0]) > 0


def test_missing_coverage_still_counts_changed_executable_lines(tmp_path):
    gate = module("coverage_gate")
    result = gate.changed_coverage(tmp_path, {"new.py": "a = 1\nb = 2\n"}, {"files": {}})
    assert result["changed_executable"] == 2
    assert result["covered"] == 0 and result["percent"] == 0
    assert result["files"][0]["status"] == "missing_coverage"


def test_secret_review_requires_exact_finding_and_non_secret_rationale():
    reviewer = module("secret_review")
    finding = {"line_number": 2, "type": "fixture", "hashed_secret": "fixture-hash"}
    review = {
        "file": "fixture.py",
        **finding,
        "disposition": "not_secret",
        "reason": "public authored fixture",
    }
    resolved = reviewer.review_findings({"fixture.py": [finding]}, [review])
    assert resolved["passed"] and len(resolved["reviewed"]) == 1
    changed = {**finding, "hashed_secret": "unexpected-new-hash"}
    assert not reviewer.review_findings({"fixture.py": [changed]}, [review])["passed"]
    assert not reviewer.review_findings(
        {"fixture.py": [finding]}, [{**review, "disposition": "deployment_risk"}]
    )["passed"]
    assert not reviewer.review_findings({"fixture.py": [finding]}, [{**review, "reason": ""}])["passed"]


def test_medium_or_high_security_findings_cannot_pass_guard(tmp_path):
    import json

    spec = importlib.util.spec_from_file_location("guard_runner", ROOT / "scripts/check_guardrails.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert not runner.security_findings(tmp_path)["passed"]
    (tmp_path / "scans").mkdir()
    report = tmp_path / "scans/bandit.json"
    report.write_text(json.dumps({"results": [{"issue_severity": "HIGH", "test_id": "fixture"}]}))
    assert not runner.security_findings(tmp_path)["passed"]
    report.write_text(json.dumps({"results": [{"issue_severity": "LOW", "test_id": "fixture"}]}))
    assert runner.security_findings(tmp_path)["passed"]


def test_timed_out_tools_report_failure_and_keep_command_output(tmp_path, monkeypatch):
    import subprocess

    spec = importlib.util.spec_from_file_location("guard_runner", ROOT / "scripts/check_guardrails.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output=b"started\n")

    monkeypatch.setattr(guard.subprocess, "run", timeout)
    command = guard.run(["pytest"], tmp_path, "tests")
    assert not command["passed"] and command["exit_code"] == 124
    log = (tmp_path / "tests.txt").read_text()
    assert "started" in log and "300" in log
    secrets = guard.secret_scan(tmp_path)
    assert not secrets["passed"] and secrets["exit_code"] == 124


def test_review_base_resolves_commit_and_parent_using_git_input():
    import subprocess

    import pytest

    spec = importlib.util.spec_from_file_location("guard_runner", ROOT / "scripts/check_guardrails.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    for ref in ("HEAD", "HEAD^"):
        sha = subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
        assert runner.resolve_commit(ref) == runner.resolve_commit(sha) == sha
    for ref in ("", "HEAD\nHEAD", "refs/heads/missing-review-reference"):
        with pytest.raises(ValueError):
            runner.resolve_commit(ref)
