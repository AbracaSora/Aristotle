"""Run the course quality scan from the repository root (Python 3.12, Pylint and Radon)."""

from collections import Counter
from importlib.metadata import version
from pathlib import Path
from statistics import mean

from pylint.lint import Run
from pylint.reporters import CollectingReporter
from radon.complexity import add_inner_blocks, cc_visit
from radon.visitors import Function


def main():
    roots = [Path("code/backend/aristotle_backend"), Path("code/core_engine/aristotle_core")]
    files = sorted(path for root in roots for path in root.rglob("*.py"))
    reporter = CollectingReporter()
    scan = Run(
        [
            "--persistent=no",
            "--disable=all",
            "--enable=E,F,duplicate-code,too-many-branches,too-many-locals,too-many-statements,too-many-nested-blocks",
            "--min-similarity-lines=4",
            *map(str, files),
        ],
        reporter=reporter,
        exit=False,
    )
    stats = scan.linter.stats
    functions = []
    for path in files:
        blocks = add_inner_blocks(cc_visit(path.read_text(encoding="utf-8")))
        functions.extend(
            (block.complexity, str(path), block.lineno, block.fullname)
            for block in blocks
            if isinstance(block, Function)
        )
    functions.sort(key=lambda row: (-row[0], row[1], row[2]))
    scores = [score for score, *_ in functions]
    print(f"Aristotle 408 | Pylint {version('pylint')} + Radon {version('radon')}")
    print(f"Scope: {' + '.join(map(str, roots))} ({len(files)} Python files)")
    print(f"Bug candidates (Pylint E/F): {stats.error + stats.fatal}")
    print(f"Code smells (enabled Pylint R rules): {stats.refactor}")
    print(f"Duplicate lines (Pylint): {stats.nb_duplicated_lines} ({stats.percent_duplicated_lines:.2f}%)")
    print(
        f"Functions: {len(scores)} | CC mean: {mean(scores):.2f} | max: {max(scores)} | CC > 20: "
        f"{sum(score > 20 for score in scores)}"
    )
    print("\nHighest cyclomatic complexity (Radon)")
    for score, path, line, name in functions[:10]:
        print(f"{score:>3}  {Path(path).name}:{line}  {name}")
    print("\nPylint findings by rule")
    for rule, count in sorted(Counter(msg.symbol for msg in reporter.messages).items()):
        print(f"{count:>3}  {rule}")
    print("\nAll Pylint findings")
    for msg in sorted(reporter.messages, key=lambda msg: (msg.path, msg.line, msg.msg_id, msg.msg)):
        print(f"{msg.path}:{msg.line}: {msg.msg_id} {msg.msg}")


if __name__ == "__main__":
    main()
