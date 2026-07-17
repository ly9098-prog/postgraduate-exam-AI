#!/usr/bin/env python3
"""Quality Gate Shadow 分析报告。

输入 pipeline artifact 或 diagnostics JSON，输出：

    summary.json
    disagreements.jsonl
    metrics_by_gate.json
    metrics_by_source.json
    metrics_by_reason.json
    report.md

用法:

    python scripts/analyze_quality_gate_shadow.py \\
        --input artifacts/pipeline_diagnostics.json \\
        --output-dir ./shadow_report/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def load_input(path: str) -> list[dict]:
    """Load shadow records from input file.

    Supports:
      - A single diagnostics JSON with ``quality_gate_shadow_records`` key
      - A JSONL file of shadow records
      - A JSON array of shadow records
    """
    content = Path(path).read_text(encoding="utf-8")

    # Try JSONL first
    records: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    if len(records) > 1:
        return records

    # Single JSON
    data = json.loads(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("quality_gate_shadow_records", [data])

    return records


def analyze(records: list[dict]) -> dict[str, Any]:
    """Analyze shadow records and produce a full report dict."""
    total = len(records)

    # Counters
    existing_accept = sum(1 for r in records if r.get("existing_decision") == "accept")
    existing_reject = sum(1 for r in records if r.get("existing_decision") == "reject")

    would_accept = sum(1 for r in records if r.get("would_accept") is True)
    would_reject = sum(1 for r in records if r.get("would_accept") is False)

    disagreements = [
        r for r in records
        if r.get("existing_decision") == "accept" and r.get("would_accept") is False
    ]
    suspicious_accepts = [
        r for r in records
        if r.get("existing_decision") == "reject" and r.get("would_accept") is True
    ]

    # Per-gate metrics
    by_gate: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_gate[r.get("gate_name", "unknown")].append(r)

    gate_metrics: dict[str, dict] = {}
    for gate_name, gate_records in sorted(by_gate.items()):
        g_total = len(gate_records)
        g_reject = sum(1 for r in gate_records if r.get("would_accept") is False)
        g_disagree = sum(
            1 for r in gate_records
            if r.get("existing_decision") == "accept" and r.get("would_accept") is False
        )
        avg_delta = sum(r.get("delta", 0) for r in gate_records) / max(g_total, 1)
        top_risks = Counter(
            flag for r in gate_records for flag in (r.get("risk_flags") or [])
        ).most_common(5)
        top_reasons = Counter(
            rc for r in gate_records for rc in (r.get("reason_codes") or [])
        ).most_common(5)

        gate_metrics[gate_name] = {
            "total": g_total,
            "would_reject": g_reject,
            "reject_rate": round(g_reject / max(g_total, 1), 4),
            "disagreements": g_disagree,
            "disagreement_rate": round(g_disagree / max(g_total, 1), 4),
            "avg_delta": round(avg_delta, 4),
            "top_risk_flags": top_risks,
            "top_reason_codes": top_reasons,
        }

    # Per-source metrics
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        source = r.get("doc_ir_source", r.get("candidate_source", "unknown"))
        by_source[source].append(r)

    source_metrics: dict[str, dict] = {}
    for source, src_records in sorted(by_source.items()):
        s_total = len(src_records)
        s_reject = sum(1 for r in src_records if r.get("would_accept") is False)
        s_disagree = sum(
            1 for r in src_records
            if r.get("existing_decision") == "accept" and r.get("would_accept") is False
        )
        source_metrics[source] = {
            "total": s_total,
            "would_reject": s_reject,
            "reject_rate": round(s_reject / max(s_total, 1), 4),
            "disagreements": s_disagree,
            "disagreement_rate": round(s_disagree / max(s_total, 1), 4),
        }

    # Per-reason metrics
    reason_counts: Counter = Counter()
    for r in records:
        for rc in (r.get("reason_codes") or []):
            reason_counts[rc] += 1
    reason_metrics = dict(reason_counts.most_common(20))

    # Flag distribution
    flag_counts: Counter = Counter()
    for r in records:
        for flag in (r.get("risk_flags") or []):
            flag_counts[flag] += 1

    # Score distribution
    score_before_list = [r.get("score_before", 0) for r in records if r.get("score_before") is not None]
    score_after_list = [r.get("score_after", 0) for r in records if r.get("score_after") is not None]
    delta_list = [r.get("delta", 0) for r in records if r.get("delta") is not None]

    avg_score_before = sum(score_before_list) / max(len(score_before_list), 1)
    avg_score_after = sum(score_after_list) / max(len(score_after_list), 1)
    avg_delta = sum(delta_list) / max(len(delta_list), 1)

    return {
        "analysis_timestamp": datetime.now().isoformat(),
        "record_count": total,
        "summary": {
            "existing_accept": existing_accept,
            "existing_reject": existing_reject,
            "would_accept": would_accept,
            "would_reject": would_reject,
            "disagreements": len(disagreements),
            "suspicious_accepts": len(suspicious_accepts),
            "disagreement_rate": round(len(disagreements) / max(total, 1), 4),
            "avg_score_before": round(avg_score_before, 4),
            "avg_score_after": round(avg_score_after, 4),
            "avg_delta": round(avg_delta, 4),
        },
        "gates": gate_metrics,
        "sources": source_metrics,
        "reasons": reason_metrics,
        "risk_flags": dict(flag_counts.most_common(20)),
        "disagreements": disagreements[:100],
        "suspicious_accepts": suspicious_accepts[:50],
    }


def build_markdown_report(report: dict) -> str:
    """Build a human-readable Markdown report from analysis results."""
    s = report["summary"]
    lines = [
        f"# Quality Gate Shadow 分析报告",
        f"",
        f"- **分析时间**: {report['analysis_timestamp']}",
        f"- **评估记录数**: {report['record_count']}",
        f"",
        f"## 总览",
        f"",
        f"| 指标 | 值 |",
        f"|---|---|",
        f"| 现有 Accept | {s['existing_accept']} |",
        f"| 现有 Reject | {s['existing_reject']} |",
        f"| Would Accept | {s['would_accept']} |",
        f"| Would Reject | {s['would_reject']} |",
        f"| Disagreements | {s['disagreements']} |",
        f"| Disagreement Rate | {s['disagreement_rate']:.2%} |",
        f"| 可疑 Accepts | {s['suspicious_accepts']} |",
        f"| 平均 Score Before | {s['avg_score_before']:.4f} |",
        f"| 平均 Score After | {s['avg_score_after']:.4f} |",
        f"| 平均 Delta | {s['avg_delta']:.4f} |",
        f"",
    ]

    # Per-gate breakdown
    lines.extend([
        f"## 按 Gate 统计",
        f"",
        f"| Gate | Total | Would Reject | Reject Rate | Disagreements | Disagreement Rate | Avg Delta |",
        f"|---|---|---|---|---|---|---|",
    ])
    for gname, gm in sorted(report.get("gates", {}).items()):
        lines.append(
            f"| {gname} | {gm['total']} | {gm['would_reject']} | "
            f"{gm['reject_rate']:.1%} | {gm['disagreements']} | "
            f"{gm['disagreement_rate']:.1%} | {gm['avg_delta']:.4f} |"
        )
    lines.append("")

    # Per-source breakdown
    lines.extend([
        f"## 按候选来源统计",
        f"",
        f"| Source | Total | Would Reject | Reject Rate | Disagreements | Disagreement Rate |",
        f"|---|---|---|---|---|---|",
    ])
    for src, sm in sorted(report.get("sources", {}).items()):
        lines.append(
            f"| {src} | {sm['total']} | {sm['would_reject']} | "
            f"{sm['reject_rate']:.1%} | {sm['disagreements']} | "
            f"{sm['disagreement_rate']:.1%} |"
        )
    lines.append("")

    # Common risk flags
    lines.extend([
        f"## 最常见的 Risk Flags",
        f"",
        f"| Flag | Count |",
        f"|---|---|",
    ])
    for flag, count in list(report.get("risk_flags", {}).items())[:10]:
        lines.append(f"| {flag} | {count} |")
    lines.append("")

    # Common reason codes
    lines.extend([
        f"## 最常见的 Reason Codes",
        f"",
        f"| Reason | Count |",
        f"|---|---|",
    ])
    for reason, count in list(report.get("reasons", {}).items())[:10]:
        lines.append(f"| {reason} | {count} |")
    lines.append("")

    # High-risk disagreements
    dis = report.get("disagreements", [])
    if dis:
        lines.extend([
            f"## 高风险 Disagreements（现有 Accept、Gate 拒绝）",
            f"",
            f"前 {min(len(dis), 20)} 条：",
            f"",
        ])
        for d in dis[:20]:
            lines.append(
                f"- **{d.get('gate_name', '?')}**: "
                f"score_before={d.get('score_before', 0):.3f} → "
                f"score_after={d.get('score_after', 0):.3f} "
                f"delta={d.get('delta', 0):.3f} "
                f"flags={d.get('risk_flags', [])} "
                f"reasons={d.get('reason_codes', [])}"
            )
        lines.append("")

    # Suspicious accepts
    sa = report.get("suspicious_accepts", [])
    if sa:
        lines.extend([
            f"## 可疑 Accepts（现有 Reject、Gate 接受）",
            f"",
        ])
        for d in sa[:10]:
            lines.append(
                f"- **{d.get('gate_name', '?')}**: "
                f"score_before={d.get('score_before', 0):.3f} → "
                f"score_after={d.get('score_after', 0):.3f}"
            )
        lines.append("")

    lines.append(
        "---\n"
        "*分析由 Quality Gate Shadow Report 自动生成。*\n"
        "*Enforce 的前置条件至少为 100+ Bench cases + 100~300 真实 shadow 决策 + 人工复核 disagreement。*"
    )

    return "\n".join(lines)


def save_report(output_dir: str, report: dict) -> dict[str, str]:
    """Save all report files to the output directory."""
    os.makedirs(output_dir, exist_ok=True)

    paths: dict[str, str] = {}

    # summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary = {
        "analysis_timestamp": report["analysis_timestamp"],
        "record_count": report["record_count"],
        "summary": report["summary"],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    paths["summary"] = summary_path

    # disagreements.jsonl
    dis_path = os.path.join(output_dir, "disagreements.jsonl")
    with open(dis_path, "w", encoding="utf-8") as f:
        for d in report.get("disagreements", []):
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    paths["disagreements"] = dis_path

    # metrics_by_gate.json
    gate_path = os.path.join(output_dir, "metrics_by_gate.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump(report.get("gates", {}), f, ensure_ascii=False, indent=2)
    paths["gates"] = gate_path

    # metrics_by_source.json
    src_path = os.path.join(output_dir, "metrics_by_source.json")
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump(report.get("sources", {}), f, ensure_ascii=False, indent=2)
    paths["sources"] = src_path

    # metrics_by_reason.json
    reason_path = os.path.join(output_dir, "metrics_by_reason.json")
    with open(reason_path, "w", encoding="utf-8") as f:
        json.dump(report.get("reasons", {}), f, ensure_ascii=False, indent=2)
    paths["reasons"] = reason_path

    # report.md
    md = build_markdown_report(report)
    md_path = os.path.join(output_dir, "report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    paths["report"] = md_path

    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Quality Gate Shadow 分析报告")
    parser.add_argument(
        "--input", required=True,
        help="输入文件：pipeline diagnostics JSON 或 shadow records JSONL",
    )
    parser.add_argument(
        "--output-dir", default="./shadow_report/",
        help="输出目录（默认 ./shadow_report/）",
    )
    parser.add_argument(
        "--max-records", type=int, default=0,
        help="最大分析记录数（0 = 不限）",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    records = load_input(args.input)
    if not records:
        print("Warning: no shadow records found in input", file=sys.stderr)
        return 0

    if args.max_records > 0 and len(records) > args.max_records:
        records = records[:args.max_records]

    report = analyze(records)
    paths = save_report(args.output_dir, report)

    print(f"\n分析完成: {len(records)} 条记录")
    print(f"  Summary:          {paths.get('summary', 'N/A')}")
    print(f"  Report (MD):      {paths.get('report', 'N/A')}")
    print(f"  Disagreements:    {paths.get('disagreements', 'N/A')}")
    print(f"  Metrics by Gate:  {paths.get('gates', 'N/A')}")
    print(f"  Metrics by Source:{paths.get('sources', 'N/A')}")
    print(f"  Metrics by Reason:{paths.get('reasons', 'N/A')}")

    s = report["summary"]
    print(f"\n  总评估: {report['record_count']}")
    print(f"  现有 Accept: {s['existing_accept']}   Would Accept: {s['would_accept']}")
    print(f"  现有 Reject: {s['existing_reject']}   Would Reject: {s['would_reject']}")
    print(f"  Disagreements: {s['disagreements']}  ({s['disagreement_rate']:.1%})")
    print(f"  可疑 Accepts: {s['suspicious_accepts']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
