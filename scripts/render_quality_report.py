"""Render actual scanner JSON into a shareable HTML report; no simulated scanner UI."""

import argparse
import csv
import difflib
import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/software/quality_evidence"
TARGETS = {
    "publish_curriculum": "curriculum_publication.py",
    "progress_views": "curriculum.py",
    "create_recommendation": "workflow.py",
    "semantic_search": "retrieval.py",
    "request_model": "providers.py",
}


def read(phase, name):
    return json.loads((EVIDENCE / phase / name).read_text())


def metrics(phase):
    lint = read(phase, "pylint.json")
    kinds = Counter(item["type"] for item in lint)
    blocks = [block for items in read(phase, "complexity.json").values() for block in items]
    duplication = read(phase, "jscpd-report.json")["statistics"]["total"]
    coverage = read(phase, "coverage.json")["totals"]
    dependencies = read(phase, "dependencies.json")["dependencies"]
    return {
        "pylint_error_fatal": kinds["error"] + kinds["fatal"],
        "pylint_smell_diagnostics": kinds["warning"] + kinds["refactor"] + kinds["convention"],
        "pylint_types": dict(kinds),
        "max_complexity": max(block["complexity"] for block in blocks),
        "mean_complexity": round(sum(block["complexity"] for block in blocks) / len(blocks), 2),
        "duplication_percent": round(duplication["percentage"], 3),
        "duplicated_lines": duplication["duplicatedLines"],
        "duplicate_blocks": duplication["clones"],
        "coverage_percent": round(coverage["percent_covered"], 2),
        "branch_coverage_percent": round(100 * coverage["covered_branches"] / coverage["num_branches"], 2),
        "bandit_findings": len(read(phase, "bandit.json")["results"]),
        "dependency_vulnerabilities": sum(len(d.get("vulns", [])) for d in dependencies),
        "targets": {block["name"]: block["complexity"] for block in blocks if block["name"] in TARGETS},
    }


def findings_csv():
    fields = ["type", "symbol", "path", "line", "message"]
    with (EVIDENCE / "after/findings.csv").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(read("after", "pylint.json"))


def refactor_diffs():
    import ast

    for name, filename in TARGETS.items():
        path = ROOT / "code/backend/aristotle_backend" / filename
        source = path.read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
        after = "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno]) + "\n"
        before = (EVIDENCE / f"before/{name}.py.txt").read_text()
        (EVIDENCE / f"after/{name}.py.txt").write_text(after)
        diff = difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="before/" + name,
            tofile=f"after/{filename}:{node.lineno}",
        )
        (EVIDENCE / f"{name}.diff").write_text("".join(diff))


def table(rows):
    return (
        "<table>"
        + "".join(
            "<tr>" + "".join("<td>" + html.escape(str(cell)) + "</td>" for cell in row) + "</tr>"
            for row in rows
        )
        + "</table>"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    before, after = metrics("before"), metrics("after")
    (EVIDENCE / "comparison.json").write_text(
        json.dumps({"date": args.date, "before": before, "after": after}, ensure_ascii=False, indent=2) + "\n"
    )
    names = {
        "pylint_error_fatal": "Pylint Error / Fatal 诊断数",
        "pylint_smell_diagnostics": "Pylint 代码异味诊断（C / R / W）",
        "max_complexity": "最大圈复杂度（Radon）",
        "mean_complexity": "Radon 分析块平均圈复杂度",
        "duplication_percent": "代码重复率 %（jscpd）",
        "duplicated_lines": "重复代码行数",
        "coverage_percent": "含分支的综合覆盖率 %",
        "branch_coverage_percent": "分支覆盖率 %",
        "bandit_findings": "Bandit 待判读安全告警",
        "dependency_vulnerabilities": "依赖已知漏洞数（审计当时）",
    }
    versions = read("after", "source_manifest.json")["versions"]
    parts = []
    for phase, data in (("before", before), ("after", after)):
        title = "重构前基线" if phase == "before" else "重构后复扫"
        rows = [[label, data[key]] for key, label in names.items()]
        parts.append(
            f'<section id="{phase}"><div class="eyebrow">ARISTOTLE · BACKEND QUALITY</div><h1>{title}</h1><p>{args.date} · master 工作区 · 基础提交 c0d8539</p>'
            + table(rows)
            + '<p class="note">真实扫描结果汇总，非 SonarQube 页面。Error 诊断不等于确认的业务 Bug；剩余告警必须结合代码评审。工具输出见同目录 JSON。</p>'
            + f'<p class="footer">Pylint {versions["pylint"]} · Radon {versions["radon"]} · Bandit {versions["bandit"]} · jscpd 5.4.3</p></section>'
        )
    rows = [["重点函数", "重构前 CC", "重构后 CC"]] + [
        [name, before["targets"][name], after["targets"][name]] for name in TARGETS
    ]
    parts.append(
        '<section id="comparison"><div class="eyebrow">TEST → REFACTOR → RESCAN</div><h1>五项重点重构</h1>'
        + table(rows)
        + '<p class="note">新逻辑拆入具名辅助函数，完整后置扫描仍覆盖全部后端代码。入口 CC 下降不代表所有辅助函数均达标。</p>'
        + '<p class="note">配额、禁用开关、配置生效和 PDF 功能修复另列回归证据；并非把行为变化冒充纯重构。</p>'
        + '<p class="note">重复代码仍为 28 行：重复率下降主要来自分母增长。Pylint 仍有风格/结构告警，本次不宣称达到全部严格质量门槛。</p>'
        + '<p class="footer">范围：code/backend/aristotle_backend + code/core_engine/aristotle_core</p></section>'
    )
    style = 'body{margin:0;background:#e9eef3;color:#172b3a;font:18px -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}section{box-sizing:border-box;width:1100px;padding:42px 52px;margin:24px;background:white;border-top:8px solid #19716b}h1{font-size:36px;margin:14px 0}p{line-height:1.7;color:#526270}table{border-collapse:collapse;width:100%;margin:24px 0}td{padding:12px 16px;border-bottom:1px solid #dce3e9}td:not(:first-child){text-align:right;font-variant-numeric:tabular-nums;font-weight:600}tr:nth-child(odd){background:#f4f8f9}.eyebrow{letter-spacing:3px;color:#19716b;font-weight:700}.note{font-size:16px}.footer{font-size:14px;color:#647587}'
    (EVIDENCE / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Aristotle 代码质量扫描报告</title><style>'
        + style
        + "</style><body>"
        + "".join(parts)
        + "</body></html>"
    )
    findings_csv()
    refactor_diffs()
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
