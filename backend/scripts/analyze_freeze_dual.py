"""Dual Freeze Analysis — analyze STRUCTURE_FREEZE_MODE=dual results.

Reads pipeline artifact data and produces:
  summary.json            — aggregate metrics
  differences.jsonl       — per-difference records
  metrics_by_bucket.json  — breakdown by document/question/source
  report.md               — human-readable report

Usage:
  python scripts/analyze_freeze_dual.py [--input freeze_dual.json] [--output-dir ./freeze-report]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def load_input(path: str | Path) -> dict:
    """Load freeze dual diagnostics JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def analyze(data: dict) -> dict:
    """Compute aggregate metrics from freeze dual diagnostics."""
    diffs = data.get("differences", [])
    diag = data.get("diagnostics", {})

    result: dict[str, Any] = {
        "analyzed_at": datetime.now().isoformat(),
        "total_documents": data.get("documents_total", 1),
        "questions_total": data.get("questions_total", 0),
        "legacy_option_count": diag.get("legacy_option_count", 0)
            or data.get("legacy_option_count", 0),
        "ir_option_count": diag.get("ir_option_count", 0)
            or data.get("ir_option_count", 0),
        "option_key_match": diag.get("option_key_match", 0)
            or data.get("option_key_match", 0),
        "option_text_match": diag.get("option_text_match", 0)
            or data.get("option_text_match", 0),
        "binding_lost_count": diag.get("binding_lost_count", 0)
            or data.get("binding_lost_count", 0),
        "differences_count": len(diffs),
        "fallback_count": data.get("fallback_count", 0),
        "ir_empty_legacy_nonempty": data.get("ir_empty_legacy_nonempty", 0),
        "legacy_empty_ir_nonempty": data.get("legacy_empty_ir_nonempty", 0),
    }

    # Per-type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for d in diffs:
        type_counts[d.get("type", "unknown")] += 1
    result["differences_by_type"] = dict(type_counts)

    # Per-source breakdown
    source_counts: dict[str, int] = defaultdict(int)
    for d in diffs:
        source = d.get("source", "unknown")
        source_counts[source] += 1
    result["differences_by_source"] = dict(source_counts)

    # Per-option-key breakdown
    key_counts: dict[str, int] = defaultdict(int)
    for d in diffs:
        key = d.get("option_key", "?")
        key_counts[key] += 1
    result["differences_by_key"] = dict(key_counts)

    return result


def build_markdown_report(stats: dict) -> str:
    """Generate a human-readable markdown report."""
    lines: list[str] = [
        "# Dual Freeze Analysis Report",
        "",
        f"Generated: {stats['analyzed_at']}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Documents | {stats['total_documents']} |",
        f"| Questions | {stats['questions_total']} |",
        f"| Legacy options | {stats['legacy_option_count']} |",
        f"| IR options | {stats['ir_option_count']} |",
        f"| Option key match | {stats['option_key_match']:.1%} |",
        f"| Option text match | {stats['option_text_match']:.1%} |",
        f"| Binding lost | {stats['binding_lost_count']} |",
        f"| Differences | {stats['differences_count']} |",
        f"| Fallbacks | {stats['fallback_count']} |",
        "",
    ]

    if stats["differences_by_type"]:
        lines.append("## Differences by Type")
        lines.append("")
        lines.append("| Type | Count |")
        lines.append("|------|-------|")
        for t, c in sorted(stats["differences_by_type"].items()):
            lines.append(f"| {t} | {c} |")
        lines.append("")

    if stats["differences_by_source"]:
        lines.append("## Differences by Source")
        lines.append("")
        lines.append("| Source | Count |")
        lines.append("|--------|-------|")
        for s, c in sorted(stats["differences_by_source"].items()):
            lines.append(f"| {s} | {c} |")
        lines.append("")

    if stats["differences_by_key"]:
        lines.append("## Differences by Option Key")
        lines.append("")
        lines.append("| Key | Count |")
        lines.append("|-----|-------|")
        for k, c in sorted(stats["differences_by_key"].items()):
            lines.append(f"| {k} | {c} |")
        lines.append("")

    # Assessment
    lines.append("## Readiness Assessment")
    lines.append("")

    if stats["option_key_match"] >= 1.0 and stats["option_text_match"] >= 0.95 and stats["binding_lost_count"] == 0:
        lines.append("**STRUCTURE_FREEZE_MODE=dual is recommended for pre-release.**")
        lines.append("")
        lines.append("Criteria met:")
        lines.append("- option_key_match = 100%")
        lines.append(f"- option_text_match >= {stats['option_text_match']:.1%}")
        lines.append("- binding_lost = 0")
    else:
        lines.append("**STRUCTURE_FREEZE_MODE=dual is NOT yet ready for pre-release.**")
        lines.append("")
        lines.append("Gaps:")
        if stats["option_key_match"] < 1.0:
            lines.append(f"- option_key_match = {stats['option_key_match']:.1%} (need 100%)")
        if stats["option_text_match"] < 0.95:
            lines.append(f"- option_text_match = {stats['option_text_match']:.1%} (need >= 95%)")
        if stats["binding_lost_count"] > 0:
            lines.append(f"- binding_lost = {stats['binding_lost_count']} (need 0)")
        lines.append("")

    # Known limitations
    lines.append("## Known Limitations")
    lines.append("")
    lines.append("- Fallback from IR to legacy must be recorded with reason code")
    lines.append("- IR empty + legacy nonempty indicates DocumentIR availability gap")
    lines.append("- Text match comparison may include whitespace/formatting differences")
    lines.append("")

    return "\n".join(lines)


def save_report(
    stats: dict,
    diffs: list[dict],
    output_dir: str | Path,
) -> dict[str, str]:
    """Save analysis outputs to directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}

    with open(out / "summary.json", "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    paths["summary"] = str(out / "summary.json")

    with open(out / "differences.jsonl", "w") as f:
        for d in diffs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    paths["differences"] = str(out / "differences.jsonl")

    with open(out / "metrics_by_bucket.json", "w") as f:
        json.dump({
            "by_type": stats.get("differences_by_type", {}),
            "by_source": stats.get("differences_by_source", {}),
            "by_key": stats.get("differences_by_key", {}),
        }, f, ensure_ascii=False, indent=2)
    paths["metrics_by_bucket"] = str(out / "metrics_by_bucket.json")

    report = build_markdown_report(stats)
    with open(out / "report.md", "w") as f:
        f.write(report)
    paths["report"] = str(out / "report.md")

    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze freeze dual diagnostics")
    parser.add_argument("--input", default="freeze_dual.json",
                        help="Input JSON file with freeze dual diagnostics")
    parser.add_argument("--output-dir", default="./freeze-report",
                        help="Output directory for report files")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}", file=sys.stderr)
        print("Run pipeline with STRUCTURE_FREEZE_MODE=dual and save artifact.", file=sys.stderr)
        return 1

    data = load_input(args.input)
    stats = analyze(data)
    diffs = data.get("differences", [])
    paths = save_report(stats, diffs, args.output_dir)

    print(f"Analysis saved to {args.output_dir}/")
    print(f"  Summary:    {paths['summary']}")
    print(f"  Differenes: {paths['differences']}")
    print(f"  Buckets:    {paths['metrics_by_bucket']}")
    print(f"  Report:     {paths['report']}")
    print()
    print(f"Questions:     {stats['questions_total']}")
    print(f"Legacy opts:   {stats['legacy_option_count']}")
    print(f"IR opts:       {stats['ir_option_count']}")
    print(f"Key match:     {stats['option_key_match']:.1%}")
    print(f"Text match:    {stats['option_text_match']:.1%}")
    print(f"Binding lost:  {stats['binding_lost_count']}")
    print(f"Differences:   {stats['differences_count']}")
    print(f"Fallbacks:     {stats['fallback_count']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
