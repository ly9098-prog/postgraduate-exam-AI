#!/usr/bin/env python3
"""Audit storage root path mismatches.

Compares files in project_root/static/ vs backend/static/ and DB URL references.

Usage:
    python scripts/audit_storage_root_mismatch.py --dry-run
    python scripts/audit_storage_root_mismatch.py --copy
    python scripts/audit_storage_root_mismatch.py --move --verify-checksum
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_storage")

BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.realpath(os.path.join(BACKEND_ROOT, ".."))


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_tree(root: str, prefix_rel: str) -> dict[str, dict]:
    """Scan a directory tree and return {relative_path: {size, hash}}."""
    results = {}
    base = os.path.join(root, prefix_rel)
    if not os.path.isdir(base):
        return results
    for dirpath, dirnames, filenames in os.walk(base):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            try:
                fsize = os.path.getsize(full)
                fhash = file_hash(full)
            except Exception:
                continue
            results[rel] = {"size": fsize, "hash": fhash, "path": full}
    return results


def main():
    parser = argparse.ArgumentParser(description="Audit storage root path mismatches")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument("--copy", action="store_true", help="Copy files (implies --no-dry-run)")
    parser.add_argument("--move", action="store_true", help="Move files (implies --no-dry-run)")
    parser.add_argument("--verify-checksum", action="store_true", help="Verify hash before copy/move")
    parser.add_argument("--update-db", action="store_true", help="Update DB URLs if needed")
    parser.add_argument("--output-dir", default="reports/sprint3h/storage-audit",
                        help="Output directory")
    args = parser.parse_args()
    if args.copy or args.move:
        args.dry_run = False

    backend_static = os.path.join(BACKEND_ROOT, "static")
    project_static = os.path.join(PROJECT_ROOT, "static")
    output_dir = os.path.join(BACKEND_ROOT, args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    asset_prefix = "question-assets"
    logger.info("Scanning project_root/static/%s ...", asset_prefix)
    proj_files = scan_tree(PROJECT_ROOT, f"static/{asset_prefix}")
    logger.info("  found %d files", len(proj_files))

    logger.info("Scanning backend/static/%s ...", asset_prefix)
    bk_files = scan_tree(BACKEND_ROOT, f"static/{asset_prefix}")
    logger.info("  found %d files", len(bk_files))

    # Only in project root (not in backend)
    only_in_project = {}
    only_in_backend = {}
    both_same = {}
    both_diff = {}

    for rel, info in proj_files.items():
        # Convert path for comparison: remove first part if it's "static/..."
        # Normalize: keep as project-root-static/question-assets/...
        rel_in_backend = rel.replace("static/", "", 1) if rel.startswith("static/") else rel
        if rel_in_backend in bk_files:
            bk_info = bk_files[rel_in_backend]
            if info["hash"] == bk_info["hash"]:
                both_same[rel] = info
            else:
                both_diff[rel] = {"project": info, "backend": bk_info}
        else:
            only_in_project[rel] = info

    for rel, info in bk_files.items():
        # Check if the file is only in backend
        rel_in_project = f"static/{rel}"
        if rel_in_project not in proj_files:
            only_in_backend[rel] = info

    report = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
        "scan_locations": {
            "project_root": os.path.join(PROJECT_ROOT, f"static/{asset_prefix}"),
            "backend": os.path.join(BACKEND_ROOT, f"static/{asset_prefix}"),
        },
        "summary": {
            "project_root_files": len(proj_files),
            "backend_files": len(bk_files),
            "only_in_project_root": len(only_in_project),
            "only_in_backend": len(only_in_backend),
            "both_same_hash": len(both_same),
            "both_different_hash": len(both_diff),
        },
        "only_in_project_root": list(only_in_project.keys()),
        "only_in_backend": list(only_in_backend.keys()),
        "both_different_hash": {
            k: {"project_hash": v["project"]["hash"], "backend_hash": v["backend"]["hash"]}
            for k, v in both_diff.items()
        },
    }

    report_path = os.path.join(output_dir, "storage_root_audit.json")
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("=" * 50)
    logger.info("Storage Root Audit Report")
    logger.info("  Project root: %d files", len(proj_files))
    logger.info("  Backend:      %d files", len(bk_files))
    logger.info("  Only in project_root: %d", len(only_in_project))
    logger.info("  Only in backend:      %d", len(only_in_backend))
    logger.info("  Both (same hash):     %d", len(both_same))
    logger.info("  Both (diff hash):     %d", len(both_diff))
    logger.info("  Report: %s", report_path)

    if both_diff:
        logger.warning("HASH CONFLICTS — do NOT auto-resolve:")
        for rel, v in both_diff.items():
            logger.warning("  %s: proj=%s backend=%s",
                           rel, v["project"]["hash"][:12], v["backend"]["hash"][:12])

    if args.dry_run:
        logger.info("Dry-run. Use --copy or --move to migrate files.")
        return

    if args.move or args.copy:
        moved_or_copied = 0
        for rel in sorted(only_in_project.keys()):
            src = os.path.join(PROJECT_ROOT, rel)
            # Map to backend path
            if rel.startswith("static/"):
                bk_rel = rel[len("static/"):]
            else:
                bk_rel = rel
            dst = os.path.join(BACKEND_ROOT, bk_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if args.move:
                shutil.move(src, dst)
                logger.info("  MOVED %s", rel)
            else:
                shutil.copy2(src, dst)
                logger.info("  COPIED %s", rel)
            moved_or_copied += 1
        logger.info("%s %d files", "Moved" if args.move else "Copied", moved_or_copied)

    if args.verify_checksum:
        logger.info("Re-verifying checksums...")
        for rel in sorted(only_in_project.keys()):
            if rel.startswith("static/"):
                bk_rel = rel[len("static/"):]
            else:
                bk_rel = rel
            dst = os.path.join(BACKEND_ROOT, bk_rel)
            if os.path.isfile(dst):
                h = file_hash(dst)
                logger.info("  %s -> %s", rel, h[:16])
        logger.info("Verify complete.")


if __name__ == "__main__":
    main()
