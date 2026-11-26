"""Reproducible backend scans; findings are data, tool failures are errors.

Use uv run python scripts/scan_quality.py --output .local/quality-current.
No production credentials, models or database are accessed by this command.
"""

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["code/backend/aristotle_backend", "code/core_engine/aristotle_core"]


def run_scan(command, output, name, *, json_stdout=True):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=300)
    (output / f"{name}.stderr.txt").write_text(result.stderr)
    allowed = {"pylint": set(range(32)), "complexity": {0}, "bandit": {0, 1}, "duplication": {0, 1}}
    if result.returncode not in allowed[name]:
        raise RuntimeError(f"{name} failed to execute (exit {result.returncode}); see stderr report")
    if json_stdout:
        # Invalid JSON indicates a broken tool invocation, never a clean scan.
        json.loads(result.stdout)
        (output / f"{name}.json").write_text(result.stdout)
    else:
        (output / f"{name}.stdout.txt").write_text(result.stdout)
    return {"command": command, "exit_code": result.returncode}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/quality-current"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands = {
        "pylint": [sys.executable, "-m", "pylint", *SOURCES, "--output-format=json", "--reports=y"],
        "complexity": [sys.executable, "-m", "radon", "cc", "-j", *SOURCES],
        "bandit": [sys.executable, "-m", "bandit", "--quiet", "-r", *SOURCES, "-f", "json"],
    }
    outcomes = {name: run_scan(command, output, name) for name, command in commands.items()}
    jscpd = ROOT / "tools/quality/node_modules/.bin/jscpd"
    outcomes["duplication"] = run_scan(
        [
            str(jscpd),
            *SOURCES,
            "--format",
            "python",
            "--min-lines",
            "6",
            "--min-tokens",
            "50",
            "--reporters",
            "json",
            "--output",
            str(output),
        ],
        output,
        "duplication",
        json_stdout=False,
    )
    json.loads((output / "jscpd-report.json").read_text())
    manifest = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": SOURCES,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "versions": {
            name: importlib.metadata.version(name) for name in ("pylint", "radon", "bandit", "coverage")
        },
        "jscpd": json.loads((ROOT / "tools/quality/package-lock.json").read_text())["packages"][
            "node_modules/jscpd"
        ]["version"],
        "commands": outcomes,
        "sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in SOURCES
            for path in sorted((ROOT / folder).rglob("*.py"))
        },
    }
    (output / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    findings = json.loads((output / "pylint.json").read_text())
    errors = [item for item in findings if item["type"] in ("fatal", "error")]
    print(f"Scans saved to {output}; Pylint error/fatal diagnostics: {len(errors)}")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
