#!/usr/bin/env python3
"""A/B 对照实验 — 对比 baseline（无 layout routing）与 new（layout-aware）pipeline。

用法:
    python scripts/run_ab_experiment.py --pdf <path> [--subject <subject>]

输出:
    - 打印两种 pipeline 的 routing_metrics 和 split_quality 对比
    - 汇总对比表格

约束:
    - 不修改 DAG 结构
    - 纯观测对比
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



# ── 对比维度 ───────────────────────────────────────────────────
COMPARISON_DIMENSIONS = [
    "question_count",
    "option_missing_rate",
    "split_quality_score",
    "option_recovery_rate",
    "order_accuracy",
    "avg_split_confidence",
]


def format_comparison(
    baseline: dict[str, Any],
    experiment: dict[str, Any],
) -> str:
    """Format A/B comparison as a readable table."""
    lines = [
        "=" * 72,
        "  A/B 实验: baseline（无 routing） vs experiment（layout-aware）",
        "=" * 72,
        "",
        f"{'指标':<30} {'Baseline':<20} {'Experiment':<20} {'Δ':<10}",
        "-" * 72,
    ]

    b_rm = baseline.get("routing_metrics") or {}
    e_rm = experiment.get("routing_metrics") or {}
    b_sq = baseline.get("split_quality") or {}
    e_sq = experiment.get("split_quality") or {}

    for dim in COMPARISON_DIMENSIONS:
        b_val = _get_metric(b_rm, b_sq, dim)
        e_val = _get_metric(e_rm, e_sq, dim)

        if b_val is None and e_val is None:
            continue

        delta = ""
        if isinstance(b_val, (int, float)) and isinstance(e_val, (int, float)):
            d = e_val - b_val
            sign = "+" if d > 0 else ""
            delta = f"{sign}{d:.3f}"
            if d > 0:
                delta += " ↑"
            elif d < 0:
                delta += " ↓"

        b_str = f"{b_val:.3f}" if isinstance(b_val, float) else str(b_val or "—")
        e_str = f"{e_val:.3f}" if isinstance(e_val, float) else str(e_val or "—")

        lines.append(f"{dim:<30} {b_str:<20} {e_str:<20} {delta:<10}")

    # Mode distribution
    lines.append("")
    lines.append("── 路由模式分布 ──")
    b_mode = b_rm.get("mode_distribution", {})
    e_mode = e_rm.get("mode_distribution", {})
    all_modes = set(b_mode.keys()) | set(e_mode.keys())
    if all_modes:
        lines.append(f"{'模式':<20} {'Baseline':<20} {'Experiment':<20}")
        lines.append("-" * 60)
        for mode in sorted(all_modes):
            b_str = f"{b_mode.get(mode, {}).get('count', 0)} runs"
            e_str = f"{e_mode.get(mode, {}).get('count', 0)} runs"
            lines.append(f"{mode:<20} {b_str:<20} {e_str:<20}")

    # VL trigger
    lines.append("")
    lines.append(f"VL 触发率: Baseline={b_rm.get('vl_trigger_rate', 0):.1%}  "
                 f"Experiment={e_rm.get('vl_trigger_rate', 0):.1%}")

    if b_rm.get("over_trigger_warning"):
        lines.append(f"  ⚠ Baseline over-trigger: {b_rm['over_trigger_warning']}")
    if e_rm.get("over_trigger_warning"):
        lines.append(f"  ⚠ Experiment over-trigger: {e_rm['over_trigger_warning']}")

    lines.append("=" * 72)
    return "\n".join(lines)


def _get_metric(
    rm: dict[str, Any],
    sq: dict[str, Any],
    dim: str,
) -> float | int | None:
    """Extract a metric value from routing_metrics or split_quality."""
    # Direct lookup
    val = rm.get(dim) or sq.get(dim)
    if val is not None:
        return val
    # option_missing_rate might be inside option_missing_rates dict
    if dim == "option_missing_rate":
        omr = rm.get("option_missing_rates", {})
        if omr:
            first_mode = next(iter(omr.values()))
            return first_mode.get("missing_rate")
    return None


async def run_pipeline_with_mode(
    pdf_path: str,
    subject: str = "math",
    force_standard: bool = False,
) -> dict[str, Any]:
    """Run the import pipeline with optional force-standard mode."""
    from app.features.pipeline_orchestrator import run_import_pipeline

    options = {}
    if force_standard:
        # Override the routing decision to standard mode
        # — read by _run_layout_router via options.strategy.force_split_mode
        options["strategy"] = {
            "force_split_mode": "standard",
        }

    logger.info("Running pipeline (force_standard=%s) on %s ...", force_standard, pdf_path)
    t0 = time.time()
    result = await run_import_pipeline(
        source_type="pdf",
        source_file=Path(pdf_path).name,
        file_path=pdf_path,
        subject=subject,
        options=options,
    )
    elapsed = time.time() - t0
    logger.info("Pipeline done in %.1fs, status=%s", elapsed, result.get("status"))

    return {
        "pipeline_id": result.get("pipeline_id"),
        "status": result.get("status"),
        "quality_report": result.get("quality_report", {}),
        "diagnostics": result.get("diagnostics", {}),
        "routing_metrics": (result.get("quality_report") or {}).get("routing_metrics", {}),
        "split_quality": (result.get("quality_report") or {}).get("split_quality_evaluation", {}),
        "question_count": (result.get("quality_report") or {}).get("total_questions", 0),
    }


async def run_ab_experiment_single(
    pdf_path: str,
    subject: str = "math",
) -> dict[str, Any]:
    """Run A/B on a single PDF document."""
    logger.info("=" * 60)
    logger.info("A/B Experiment on: %s", pdf_path)
    logger.info("=" * 60)

    # Baseline: force standard mode (no layout routing)
    baseline = await run_pipeline_with_mode(pdf_path, subject, force_standard=True)

    # Experiment: enable layout-aware routing
    experiment = await run_pipeline_with_mode(pdf_path, subject, force_standard=False)

    return {"baseline": baseline, "experiment": experiment}


async def main():
    parser = argparse.ArgumentParser(
        description="A/B experiment: baseline vs layout-aware pipeline"
    )
    parser.add_argument("--pdf", type=str, required=True, help="Path to PDF file")
    parser.add_argument("--subject", type=str, default="math",
                        choices=["math", "408", "english"],
                        help="Subject type")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of formatted table")

    args = parser.parse_args()

    pdf_path = args.pdf
    if not Path(pdf_path).exists():
        logger.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    result = await run_ab_experiment_single(pdf_path, args.subject)

    if args.json:
        output = {
            "baseline": result["baseline"],
            "experiment": result["experiment"],
            "comparison": {
                dim: {
                    "baseline": _get_metric(
                        result["baseline"].get("routing_metrics", {}),
                        result["baseline"].get("split_quality", {}),
                        dim,
                    ),
                    "experiment": _get_metric(
                        result["experiment"].get("routing_metrics", {}),
                        result["experiment"].get("split_quality", {}),
                        dim,
                    ),
                }
                for dim in COMPARISON_DIMENSIONS
            },
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_comparison(result["baseline"], result["experiment"]))


if __name__ == "__main__":
    asyncio.run(main())
