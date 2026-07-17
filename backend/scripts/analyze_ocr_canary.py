"""Canary analysis — generate summary JSON from canary artifacts.

Usage:
    cd backend
    PYTHONPATH=. python scripts/analyze_ocr_canary.py <artifact_dir>

Output:
    summary.json
    control_vs_canary.json
    failures.jsonl
    fallbacks.jsonl
    review_outcomes.jsonl
    metrics_by_bucket.json
    metrics_by_subject.json
    metrics_by_source_type.json
    metrics_by_model.json
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


def analyze_artifact_dir(artifact_dir: str) -> dict[str, Any]:
    """Scan artifact directory and produce canary analysis."""
    base = Path(artifact_dir)
    if not base.is_dir():
        print(f"Error: {artifact_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Collect pipeline artifact directories
    pipeline_dirs = [d for d in base.iterdir() if d.is_dir()]

    results: dict[str, Any] = {
        "analysis_timestamp": datetime.utcnow().isoformat(),
        "artifact_dir": artifact_dir,
        "total_pipelines": len(pipeline_dirs),
        "groups": {"control_a": 0, "observation_b": 0, "canary_c": 0},
        "success_count": 0,
        "failure_count": 0,
        "fallback_count": 0,
        "total_documents": set(),
        "total_pages": 0,
        "total_questions": 0,
        "freeze_modes": defaultdict(int),
        "quality_gate_modes": defaultdict(int),
        "option_key_match_total": 0,
        "option_text_match_total": 0,
        "binding_lost_total": 0,
        "differences_total": 0,
        "latencies_ms": [],
        "failures": [],
        "fallbacks": [],
        "review_outcomes": [],
        "metrics_by_bucket": defaultdict(lambda: {"count": 0, "success": 0, "failure": 0}),
        "metrics_by_subject": defaultdict(lambda: {"count": 0, "success": 0, "failure": 0}),
        "metrics_by_source_type": defaultdict(lambda: {"count": 0, "success": 0, "failure": 0}),
    }

    for pdir in pipeline_dirs:
        _analyze_single_pipeline(pdir, results)

    # Convert sets to counts and defaultdicts to dict
    results["total_unique_documents"] = len(results["total_documents"])
    del results["total_documents"]
    results["metrics_by_bucket"] = dict(results["metrics_by_bucket"])
    results["metrics_by_subject"] = dict(results["metrics_by_subject"])
    results["metrics_by_source_type"] = dict(results["metrics_by_source_type"])
    results["freeze_modes"] = dict(results["freeze_modes"])
    results["quality_gate_modes"] = dict(results["quality_gate_modes"])

    # Compute derived metrics
    total = max(results["total_pipelines"], 1)
    results["success_rate"] = round(results["success_count"] / total * 100, 2)
    results["failure_rate"] = round(results["failure_count"] / total * 100, 2)
    results["fallback_rate"] = round(results["fallback_count"] / total * 100, 2)

    if results["latencies_ms"]:
        latencies = sorted(results["latencies_ms"])
        n = len(latencies)
        results["latency_p50_ms"] = latencies[int(n * 0.5)]
        results["latency_p95_ms"] = latencies[int(n * 0.95)]
    else:
        results["latency_p50_ms"] = 0
        results["latency_p95_ms"] = 0

    return results


def _analyze_single_pipeline(pdir: Path, results: dict) -> None:
    """Analyze artifacts for a single pipeline."""
    pipeline_id = pdir.name
    manifest = _load_json(pdir / "run_manifest.json") or {}

    # Determine group from canary diagnostics
    canary_diag = manifest.get("canary_diagnostics", {})
    group = canary_diag.get("group", "control_a")
    results["groups"][group] = results["groups"].get(group, 0) + 1

    # Count success/failure
    completed = (pdir / ".completed").exists()
    failed = (pdir / ".failed").exists()

    if completed:
        results["success_count"] += 1
    if failed:
        results["failure_count"] += 1

    # Fallback tracking
    if canary_diag.get("canary_fallback"):
        results["fallback_count"] += 1
        results["fallbacks"].append({
            "pipeline_id": pipeline_id,
            "fallback_reasons": canary_diag.get("fallback_reason_codes", []),
        })

    # Freeze mode
    freeze_mode = manifest.get("freeze_mode", "unknown")
    results["freeze_modes"][freeze_mode] += 1

    # Quality gate mode
    qg_mode = manifest.get("quality_gate_mode", "unknown")
    results["quality_gate_modes"][qg_mode] += 1

    # Dual freeze diagnostics
    dual_diag = manifest.get("freeze_dual_diagnostics", {}) or {}
    if dual_diag.get("freeze_mode") == "dual":
        results["option_key_match_total"] += 1 if dual_diag.get("option_key_match") else 0
        results["option_text_match_total"] += 1 if dual_diag.get("option_text_match") else 0
        results["binding_lost_total"] += dual_diag.get("binding_lost_count", 0)
        results["differences_total"] += dual_diag.get("differences_count", 0)

    # Latency
    latency = manifest.get("total_latency_ms", 0) or 0
    if latency > 0:
        results["latencies_ms"].append(latency)

    # Document info
    doc_id = manifest.get("document_id", pipeline_id)
    results["total_documents"].add(doc_id)
    results["total_pages"] += manifest.get("total_pages", 0) or 0
    results["total_questions"] += manifest.get("total_questions", 0) or 0

    # Per-bucket metrics
    bucket = canary_diag.get("bucket_assignment", {}).get("canary_bucket", -1)
    bucket_key = str(bucket)
    results["metrics_by_bucket"][bucket_key]["count"] += 1
    if completed:
        results["metrics_by_bucket"][bucket_key]["success"] += 1
    if failed:
        results["metrics_by_bucket"][bucket_key]["failure"] += 1

    # Per-subject metrics
    subject = manifest.get("subject", "unknown")
    results["metrics_by_subject"][subject]["count"] += 1
    if completed:
        results["metrics_by_subject"][subject]["success"] += 1
    if failed:
        results["metrics_by_subject"][subject]["failure"] += 1

    # Quality gate records
    qg_records = manifest.get("quality_gate_shadow_records", [])
    for record in qg_records:
        results["review_outcomes"].append(record)


def _load_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_outputs(results: dict[str, Any], output_dir: str) -> None:
    """Write analysis results to output files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "summary.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    # Control vs Canary comparison
    control_vs_canary = {
        "control_a_count": results["groups"].get("control_a", 0),
        "observation_b_count": results["groups"].get("observation_b", 0),
        "canary_c_count": results["groups"].get("canary_c", 0),
        "success_rate": results["success_rate"],
        "fallback_rate": results["fallback_rate"],
        "latency_p50_ms": results["latency_p50_ms"],
        "latency_p95_ms": results["latency_p95_ms"],
        "option_key_match_rate": (
            (results["option_key_match_total"] / max(results["total_pipelines"], 1)) * 100
        ),
        "binding_lost_total": results["binding_lost_total"],
    }
    with open(out / "control_vs_canary.json", "w") as f:
        json.dump(control_vs_canary, f, indent=2)

    # Failures
    with open(out / "failures.jsonl", "w") as f:
        for failure in results["failures"]:
            f.write(json.dumps(failure, ensure_ascii=False) + "\n")

    # Fallbacks
    with open(out / "fallbacks.jsonl", "w") as f:
        for fb in results["fallbacks"]:
            f.write(json.dumps(fb, ensure_ascii=False) + "\n")

    # Review outcomes
    with open(out / "review_outcomes.jsonl", "w") as f:
        for ro in results["review_outcomes"]:
            f.write(json.dumps(ro, ensure_ascii=False) + "\n")

    # By bucket
    with open(out / "metrics_by_bucket.json", "w") as f:
        json.dump(results["metrics_by_bucket"], f, indent=2)

    # By subject
    with open(out / "metrics_by_subject.json", "w") as f:
        json.dump(results["metrics_by_subject"], f, indent=2)

    # By source type
    with open(out / "metrics_by_source_type.json", "w") as f:
        json.dump(results["metrics_by_source_type"], f, indent=2)

    print(f"Analysis written to {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze canary artifacts")
    parser.add_argument("artifact_dir", help="Pipeline artifact root directory")
    parser.add_argument("--output-dir", "-o", default="./canary_report",
                        help="Output directory for analysis results")
    args = parser.parse_args()

    results = analyze_artifact_dir(args.artifact_dir)
    write_outputs(results, args.output_dir)


if __name__ == "__main__":
    main()
