"""Run strict project checks; emit nonzero for findings, missing evidence or tool errors."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/quality"))


def execute(command):
    try:
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=300)
    except subprocess.TimeoutExpired as exc:
        # subprocess supplies partial output as bytes even in text mode.
        stdout = (exc.stdout or b"").decode(errors="replace")
        stderr = (exc.stderr or b"").decode(errors="replace")
        return subprocess.CompletedProcess(
            command, 124, stdout, f"{stderr}\nTimed out after {exc.timeout}s\n"
        )
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, "", f"Tool could not start: {exc}\n")


def run(command, output, name):
    result = execute(command)
    (output / (name + ".txt")).write_text(result.stdout + result.stderr)
    return {"command": command, "exit_code": result.returncode, "passed": result.returncode == 0}


def structure(files, limits):
    from structure_metrics import inspect_source

    measurements, findings = [], []
    for path, source in files.items():
        measured, found = inspect_source(path, source, limits)
        measurements.extend(measured)
        findings.extend(found)
    return {"measurements": measurements, "findings": findings, "passed": not findings}


def diff_size(files, base, sources):
    from review_bundle import changed_lines

    count = 0
    existing = (
        subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "-z", base, "--", *sources], cwd=ROOT)
        .decode()
        .split("\0")
    )
    paths = set(files) | {p for p in existing if p.endswith(".py")}
    for path in paths:
        before = subprocess.run(
            ["git", "show", base + ":" + path], cwd=ROOT, capture_output=True, text=True, check=False
        )
        count += changed_lines(before.stdout.encode(), files.get(path, "").encode())
    return count


def run_commands(output, full):
    commands = {
        "compile": [sys.executable, "-m", "compileall", "-q", "code/backend", "code/core_engine"],
        "ruff": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "code/backend",
            "code/core_engine",
            "tests",
            "scripts",
            "tools/quality",
        ],
        "format": [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "code/backend",
            "code/core_engine",
            "tests",
            "scripts",
            "tools/quality",
        ],
        "types": [
            sys.executable,
            "-m",
            "mypy",
            "--check-untyped-defs",
            "code/backend/aristotle_backend",
            "code/core_engine/aristotle_core",
        ],
        "scans": [sys.executable, "scripts/scan_quality.py", "--output", str(output / "scans")],
    }
    if full:
        commands["tests"] = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--cov=code/backend/aristotle_backend",
            "--cov=code/core_engine/aristotle_core",
            "--cov-branch",
            "--cov-report=json:" + str(output / "coverage.json"),
            "--cov-report=term",
        ]
        commands["dependencies"] = [
            sys.executable,
            "-m",
            "pip_audit",
            "--cache-dir",
            ".local/pip-audit-cache",
            "--local",
            "--skip-editable",
            "-f",
            "json",
            "-o",
            str(output / "dependencies.json"),
        ]
    return {name: run(command, output, name) for name, command in commands.items()}


def secret_scan(output):
    from secret_review import review_findings

    executable = str(Path(sys.executable).parent / "detect-secrets")
    command = [
        executable,
        "scan",
        "--all-files",
        "--exclude-files",
        "node_modules|__pycache__|quality_evidence",
        "code/backend",
        "code/core_engine",
        "scripts",
        "tests",
        ".github",
        "quality",
        "tools/quality",
    ]
    result = execute(command)
    data = json.loads(result.stdout) if result.returncode == 0 else {"results": {"tool_error": []}}
    (output / "secrets.json").write_text(json.dumps(data, indent=2) + "\n")
    review_path = ROOT / "docs/software/quality_evidence/secret_reviews.json"
    reviews = json.loads(review_path.read_text())["reviews"] if review_path.is_file() else []
    verdict = review_findings(data["results"], reviews) if result.returncode == 0 else {"passed": False}
    return {
        "exit_code": result.returncode,
        "findings": sum(len(rows) for rows in data["results"].values()),
        **verdict,
        "passed": result.returncode == 0 and verdict["passed"],
    }


def issue_markers(files):
    import re

    return [
        {"file": path, "line": number}
        for path, source in files.items()
        for number, line in enumerate(source.splitlines(), 1)
        if re.search(r"\b(?:TODO|FIXME)\b", line) and not re.search(r"(?:#\d+|SM-\d+|ISSUE-\d+)", line)
    ]


def security_findings(output):
    report = output / "scans/bandit.json"
    if not report.is_file():
        return {"passed": False, "status": "not_run"}
    findings = json.loads(report.read_text())["results"]
    blocking = [item for item in findings if item["issue_severity"] in ("HIGH", "MEDIUM")]
    return {"passed": not blocking, "blocking": blocking, "total_findings": len(findings)}


def evaluate(config, files, output, commands, base):
    from coverage_gate import inspect_coverage
    from import_graph import inspect_imports
    from review_bundle import review_size

    metrics = structure(files, config["limits"])
    imports = inspect_imports(files)
    coverage = inspect_coverage(
        ROOT,
        files,
        output / ("coverage.json" if commands.get("tests", {}).get("passed") else "not-run.json"),
        config["core_coverage"],
        base,
    )
    duplicate_path = output / "scans/jscpd-report.json"
    clones = (
        json.loads(duplicate_path.read_text())["statistics"]["total"]["clones"]
        if commands["scans"]["passed"] and duplicate_path.is_file()
        else None
    )
    size = diff_size(files, base, config["sources"])
    review = review_size(ROOT, size, config, base)
    markers, secrets = issue_markers(files), secret_scan(output)
    security = (
        security_findings(output)
        if commands["scans"]["passed"]
        else {"passed": False, "status": "scan_failed"}
    )
    return {
        "structure": metrics,
        "security": security,
        "untracked_todos": markers,
        "secrets": secrets,
        "imports": imports,
        "coverage": coverage,
        "commands": commands,
        "duplicate_blocks": clones,
        "diff_lines": size,
        "review": review,
        "passed": security["passed"]
        and not markers
        and secrets["passed"]
        and metrics["passed"]
        and not imports["cycles"]
        and not imports["dynamic_imports"]
        and coverage["passed"]
        and clones == 0
        and review["passed"]
        and all(value["passed"] for value in commands.values()),
    }


def resolve_commit(revision):
    """Resolve one commit expression via Git's batch input protocol."""
    if not revision or any(char in revision for char in ("\r", "\n", "\0")):
        raise ValueError("基线必须是单行 Git 提交引用")
    output = subprocess.check_output(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        input=revision + "^{commit}\n",
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    match = re.fullmatch(r"([0-9a-f]{40}|[0-9a-f]{64}) commit\n", output)
    if not match:
        raise ValueError("找不到指定的基线提交")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/guardrails")
    parser.add_argument("--base", default=os.environ.get("ARISTOTLE_REVIEW_BASE") or "HEAD")
    args = parser.parse_args()
    base = resolve_commit(args.base)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "quality/guardrails.json").read_text())
    files = {
        str(path.relative_to(ROOT)): path.read_text()
        for folder in config["sources"]
        for path in sorted((ROOT / folder).rglob("*.py"))
    }
    commands = run_commands(output, args.full)
    report = evaluate(config, files, output, commands, base)
    (output / "guardrails.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "structure_findings": len(report["structure"]["findings"]),
                "cycles": report["imports"]["cycles"],
                "diff_lines": report["diff_lines"],
                "coverage": report["coverage"].get("status"),
                "report": str(output / "guardrails.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
