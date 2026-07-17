"""Export canary failures to bench candidate cases.

Usage:
    cd backend
    PYTHONPATH=. python scripts/export_canary_failures_to_bench.py <analysis_dir> <output_dir>

Generates bench candidate directories with meta.json and review checklist.
Does NOT automatically add to bench — requires human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def export_failures(
    analysis_dir: str,
    output_dir: str,
) -> int:
    """Export canary failures as bench candidates.

    Returns the number of candidate cases generated.
    Does NOT add to bench — only creates candidate directories.
    """
    analysis_path = Path(analysis_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Load fallbacks and review outcomes
    fallbacks = _load_jsonl(analysis_path / "fallbacks.jsonl")
    review_outcomes = _load_jsonl(analysis_path / "review_outcomes.jsonl")

    seen_hashes: set[str] = set()
    exported_count = 0

    # Export from fallbacks
    for fb in fallbacks:
        pipeline_id = fb.get("pipeline_id", "unknown")
        input_hash = hashlib.sha256(pipeline_id.encode()).hexdigest()[:16]

        if input_hash in seen_hashes:
            continue
        seen_hashes.add(input_hash)

        candidate_dir = out_path / f"candidate_{input_hash}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "source_pipeline_id": pipeline_id,
            "input_hash": input_hash,
            "source": "canary_fallback",
            "fallback_reasons": fb.get("fallback_reasons", []),
            "exported_at": datetime.utcnow().isoformat(),
            "redacted": False,
            "requires_review": True,
        }
        with open(candidate_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        _write_checklist(candidate_dir, pipeline_id)
        exported_count += 1

    # Export from review outcomes (rejected only)
    for ro in review_outcomes:
        if ro.get("would_accept", True):
            continue

        pipeline_id = ro.get("pipeline_id", pipeline_id)
        input_hash = hashlib.sha256(pipeline_id.encode()).hexdigest()[:16]

        if input_hash in seen_hashes:
            continue
        seen_hashes.add(input_hash)

        candidate_dir = out_path / f"candidate_{input_hash}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "source_pipeline_id": pipeline_id,
            "input_hash": input_hash,
            "source": "canary_review_rejection",
            "issue_types": ro.get("risk_flags", []),
            "exported_at": datetime.utcnow().isoformat(),
            "redacted": False,
            "requires_review": True,
        }
        with open(candidate_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        _write_checklist(candidate_dir, pipeline_id)
        exported_count += 1

    return exported_count


def _load_jsonl(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _write_checklist(candidate_dir: Path, pipeline_id: str) -> None:
    """Write review and redaction checklist."""
    checklist = {
        "redaction_checklist": {
            "personal_info_removed": False,
            "sensitive_content_removed": False,
            "original_refs_removed": False,
        },
        "review_checklist": {
            "ground_truth_verified": False,
            "expected_output_validated": False,
            "scenario_bucket_assigned": False,
            "human_verified": False,
        },
        "source_pipeline_id": pipeline_id,
    }
    with open(candidate_dir / "review_checklist.json", "w") as f:
        json.dump(checklist, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export canary failures to bench candidates")
    parser.add_argument("analysis_dir", help="Directory with canary analysis JSON files")
    parser.add_argument("--output-dir", "-o", default="./bench_candidates",
                        help="Output directory for bench candidates")
    args = parser.parse_args()

    count = export_failures(args.analysis_dir, args.output_dir)
    print(f"Exported {count} candidate case(s) to {args.output_dir}/")
    print("NOTE: These are candidates only. Review and redact before adding to bench.")


if __name__ == "__main__":
    main()
