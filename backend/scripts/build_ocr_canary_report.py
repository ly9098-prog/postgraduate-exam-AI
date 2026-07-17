"""Build human-readable canary report from analysis output.

Usage:
    cd backend
    PYTHONPATH=. python scripts/build_ocr_canary_report.py <analysis_dir>

Output:
    report.md
    report.html (optional)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def load_analysis(analysis_dir: str) -> dict:
    """Load analysis JSON files from directory."""
    base = Path(analysis_dir)
    data: dict = {}

    for fname in [
        "summary.json",
        "control_vs_canary.json",
        "metrics_by_bucket.json",
        "metrics_by_subject.json",
    ]:
        path = base / fname
        if path.exists():
            with open(path) as f:
                data[fname.replace(".json", "")] = json.load(f)

    for fname in ["failures.jsonl", "fallbacks.jsonl", "review_outcomes.jsonl"]:
        path = base / fname
        if path.exists():
            entries = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            data[fname.replace(".jsonl", "")] = entries

    return data


def build_markdown(data: dict) -> str:
    """Build markdown report from analysis data."""
    summary = data.get("summary", {})
    cv = data.get("control_vs_canary", {})

    lines: list[str] = []
    lines.append("# OCR Canary Analysis Report")
    lines.append("")
    lines.append(f"> Generated: {datetime.utcnow().isoformat()}")
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- Total pipelines: {summary.get('total_pipelines', 0)}")
    lines.append(f"- Unique documents: {summary.get('total_unique_documents', 0)}")
    lines.append(f"- Total pages: {summary.get('total_pages', 0)}")
    lines.append(f"- Total questions: {summary.get('total_questions', 0)}")
    lines.append("")

    # Group distribution
    lines.append("## Group Distribution")
    lines.append("")
    groups = summary.get("groups", {})
    lines.append(f"- Control A (legacy): {groups.get('control_a', 0)}")
    lines.append(f"- Observation B (dual): {groups.get('observation_b', 0)}")
    lines.append(f"- Canary C (IR canary): {groups.get('canary_c', 0)}")
    lines.append("")

    # Success metrics
    lines.append("## Success Metrics")
    lines.append("")
    lines.append(f"- Success rate: {summary.get('success_rate', 0):.1f}%")
    lines.append(f"- Failure rate: {summary.get('failure_rate', 0):.1f}%")
    lines.append(f"- Fallback rate: {summary.get('fallback_rate', 0):.1f}%")
    lines.append("")

    # Freeze mode distribution
    lines.append("## Freeze Mode Distribution")
    lines.append("")
    for mode, count in summary.get("freeze_modes", {}).items():
        lines.append(f"- {mode}: {count}")
    lines.append("")

    # Quality Gate
    lines.append("## Quality Gate Shadow")
    lines.append("")
    for mode, count in summary.get("quality_gate_modes", {}).items():
        lines.append(f"- {mode}: {count}")
    lines.append("")

    latency_p50 = summary.get("latency_p50_ms", 0)
    latency_p95 = summary.get("latency_p95_ms", 0)
    lines.append(f"- Latency P50: {latency_p50:.1f}ms")
    lines.append(f"- Latency P95: {latency_p95:.1f}ms")
    lines.append("")

    # Dual freeze comparison
    lines.append("## Dual Freeze Comparison")
    lines.append("")
    total = max(summary.get("total_pipelines", 0), 1)
    key_match_rate = (cv.get("option_key_match_rate", 0))
    lines.append(f"- Option key match rate: {key_match_rate:.1f}%")
    lines.append(f"- Binding lost total: {summary.get('binding_lost_total', 0)}")
    lines.append(f"- Differences total: {summary.get('differences_total', 0)}")
    lines.append("")

    # Fallback details
    fallbacks = data.get("fallbacks", [])
    if fallbacks:
        lines.append("## Fallback Details")
        lines.append("")
        for fb in fallbacks[:20]:
            lines.append(f"- Pipeline: {fb.get('pipeline_id', '?')}")
            lines.append(f"  Reasons: {', '.join(fb.get('fallback_reasons', []))}")
        if len(fallbacks) > 20:
            lines.append(f"- ... and {len(fallbacks) - 20} more")
        lines.append("")

    # Failures
    failures = data.get("failures", [])
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures[:20]:
            lines.append(f"- Pipeline: {f.get('pipeline_id', '?')}")
        if len(failures) > 20:
            lines.append(f"- ... and {len(failures) - 20} more")
        lines.append("")

    # Review outcomes
    review_outcomes = data.get("review_outcomes", [])
    if review_outcomes:
        lines.append("## Human Review Outcomes")
        lines.append("")
        accepted = sum(1 for r in review_outcomes if r.get("would_accept", False))
        rejected = len(review_outcomes) - accepted
        lines.append(f"- Total review outcomes: {len(review_outcomes)}")
        lines.append(f"- Accepted: {accepted}")
        lines.append(f"- Rejected: {rejected}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canary report")
    parser.add_argument("analysis_dir", help="Directory with analysis JSON files")
    parser.add_argument("--output", "-o", default="canary_report.md",
                        help="Output markdown file path")
    args = parser.parse_args()

    data = load_analysis(args.analysis_dir)
    report = build_markdown(data)

    with open(args.output, "w") as f:
        f.write(report)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
