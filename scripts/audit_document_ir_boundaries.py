#!/usr/bin/env python3
"""Audit DocumentIR boundary — track legacy pattern usage outside adapters."""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend" / "app"

LEGACY_PATTERNS = ["normalized_blocks", "rec_texts", "dt_polys", "layoutParsingResults"]

ADAPTER_ALLOWLIST = {
    "app/features/ocr_adapter.py",
    "app/features/ocr_vl/paddleocr_vl_adapter.py",
    "app/core/document_ir.py",
}

MIGRATION_CHECKLIST = [
    "app/services/question_snapshot_service.py",
    "app/features/visual_boundary_detector.py",
    "app/features/layout_reconstruction.py",
    "app/features/page_classifier.py",
    "app/features/structure_analyzer.py",
    "app/features/answer_matcher.py",
    "app/features/question_splitter.py",
    "app/features/pipeline_orchestrator.py",
    "app/features/text_normalizer.py",
    "app/features/table_region_detector.py",
    "app/features/pipeline_stages/layout_stage.py",
    "app/features/pipeline_stages/structure_freeze_stage.py",
    "app/features/pipeline_stages/match_stage.py",
]


def audit() -> dict[str, list[dict]]:
    per_file: dict[str, list[dict]] = {}
    total = 0

    for py_file in sorted(BACKEND.rglob("*.py")):
        rel = str(py_file.relative_to(BACKEND.parent))
        if "/test_" in rel or "__pycache__" in rel:
            continue

        source = py_file.read_text()
        file_matches: list[dict] = []
        for pat in LEGACY_PATTERNS:
            if pat in source:
                lines = source.split("\n")
                for i, line in enumerate(lines, 1):
                    if pat in line:
                        file_matches.append({
                            "line": i,
                            "pattern": pat,
                            "snippet": line.strip()[:120],
                        })
        if file_matches:
            per_file[rel] = file_matches
            total += len(file_matches)

    return per_file, total


def main():
    per_file, total = audit()

    print(f"{'='*60}")
    print(f"DocumentIR Boundary Audit")
    print(f"{'='*60}")
    print(f"Total legacy references (outside adapter): {total}")

    # Show migration checklist files
    checklist_count = 0
    print(f"\n--- Migration checklist files ({len(MIGRATION_CHECKLIST)} files) ---")
    for rel in MIGRATION_CHECKLIST:
        matches = per_file.get(rel, [])
        if matches:
            print(f"\n  {rel} ({len(matches)} refs):")
            for m in matches:
                print(f"    L{m['line']:>5d}  [{m['pattern']}]  {m['snippet'][:100]}")
            checklist_count += len(matches)
        else:
            print(f"\n  {rel}: ✅ CLEAN")

    print(f"\n--- Summary ---")
    print(f"  Migration checklist total: {checklist_count} references across {sum(1 for r in MIGRATION_CHECKLIST if per_file.get(r, []))} files")
    print(f"  Total in all production code: {total} references across {len(per_file)} files")

    # List non-checklist files with violations (new regression)
    non_checklist = {k: v for k, v in per_file.items() if k not in MIGRATION_CHECKLIST and k not in ADAPTER_ALLOWLIST}
    if non_checklist:
        print(f"\n--- Unexpected violations (outside migration list) ---")
        for rel, matches in sorted(non_checklist.items()):
            print(f"  {rel} ({len(matches)} refs)")

    return 0 if not non_checklist else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
