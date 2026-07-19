#!/usr/bin/env python3
"""Run Profile Test Matrix — Execute test suites for each deployment profile.

Usage:
  PYTHONPATH=. python scripts/run_profile_test_matrix.py [--profile local_import|cloud_api]

Output:
  reports/sprint4c/ci_profile_matrix.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Tests that should pass regardless of profile
COMMON_TESTS = [
    "tests/test_target_architecture_feature_matrix.py",
    "tests/test_control_plane_facade.py",
    "tests/test_deployment_profile.py",
    "tests/test_runtime_capabilities.py",
    "tests/test_profile_frozen_on_resume.py",
    "tests/test_ocr_gateway.py",
    "tests/test_ocr_gateway_shadow.py",
    "tests/test_unified_safety_evaluator.py",
    "tests/test_unified_safety_shadow_equivalence.py",
    "tests/test_document_validator.py",
    "tests/test_document_ir_ssot_boundaries.py",
    "tests/test_coordinator_boundaries.py",
    "tests/test_asset_outbox.py",
]

# Tests that verify cloud_api profile constraints
CLOUD_API_TESTS = [
    # Profile isolation
    "tests/test_cloud_profile_no_paddle_import.py",
    "tests/test_cloud_profile_no_cuda_initialization.py",
    "tests/test_cloud_ocr_no_local_fallback.py",
    "tests/test_cloud_profile_registry.py",
    # Profile integration
    "tests/test_ocr_gateway_profile_routes.py",
    "tests/test_page_stream_profile_config.py",
    "tests/test_orchestrator_profile_integration.py",
    "tests/test_invalid_profile_flag_combinations.py",
    "tests/test_profile_capability_enforcement.py",
    # Resource guard
    "tests/test_cloud_resource_guard.py",
    "tests/test_ocr_adapter_lazy_loading.py",
]

# Tests that verify local_import profile capabilities
LOCAL_IMPORT_TESTS = [
    "tests/test_local_profile_registry.py",
    "tests/test_page_stream.py",
    "tests/test_page_stream_memory.py",
    "tests/test_page_stream_resume.py",
]

# Sprint 4C coordinator pipeline tests
SPRINT_4C_TESTS = [
    "tests/test_pipeline_coordinator_shadow.py",
    "tests/test_pipeline_coordinator_production_entry.py",
    "tests/test_pipeline_coordinator_single_execution.py",
    "tests/test_public_admin_pipeline_equivalence.py",
    "tests/test_coordinator_rollback.py",
    "tests/test_rollback_resume_idempotency.py",
    "tests/test_document_ir_no_production_write_violations.py",
    "tests/test_no_new_legacy_call_sites.py",
    "tests/test_cloud_gateway_e2e.py",
    "tests/test_cloud_gateway_no_local_import_after_failure.py",
    "tests/test_existing_sync_after_coordinator_switch.py",
    "tests/test_database_sync_compatibility.py",
    "tests/test_no_duplicate_database_sync.py",
]

# Database sync boundary tests
SYNC_TESTS = [
    "tests/test_database_sync_compatibility.py",
    "tests/test_no_duplicate_database_sync.py",
    "tests/test_existing_sync_after_coordinator_switch.py",
    "tests/test_no_new_sync_endpoint.py",
    "tests/test_no_new_sync_worker.py",
]


def run_tests(test_files: list[str], profile: str, label: str) -> dict:
    """Run a set of tests with the given profile and return results."""
    env = os.environ.copy()
    env["DEPLOYMENT_PROFILE"] = profile
    env["PYTHONPATH"] = "."

    # Build command
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"] + test_files

    print(f"\n{'='*60}")
    print(f"[{label}] Running {len(test_files)} tests with {profile}...")
    print(f"{'='*60}")

    start = datetime.now()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.abspath(__file__)) + "/..")
    duration = (datetime.now() - start).total_seconds()

    passed = "passed" in result.stdout.lower() and "failed" not in result.stdout.lower()
    failed_count = 0
    passed_count = 0

    # Parse output for counts
    for line in result.stdout.split("\n"):
        if "passed" in line and "failed" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p == "passed":
                    passed_count = int(parts[i-1]) if i > 0 else 0
                elif p == "failed":
                    failed_count = int(parts[i-1]) if i > 0 else 0

    return {
        "label": label,
        "profile": profile,
        "test_count": len(test_files),
        "passed": result.returncode == 0,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "duration_s": round(duration, 2),
        "stdout": result.stdout[-500:],
        "stderr": result.stderr[-500:],
        "returncode": result.returncode,
    }


def main():
    parser = argparse.ArgumentParser(description="Run Profile Test Matrix")
    parser.add_argument("--profile", choices=["local_import", "cloud_api", "all"], default="all")
    parser.add_argument("--skip-4c", action="store_true", help="Skip Sprint 4C tests")
    args = parser.parse_args()

    results = []

    profiles = ["local_import", "cloud_api"] if args.profile == "all" else [args.profile]

    for profile in profiles:
        # Run common tests
        results.append(run_tests(COMMON_TESTS, profile, "common"))

        # Run profile-specific tests
        profile_tests = []
        if profile == "cloud_api":
            profile_tests = CLOUD_API_TESTS
        else:
            profile_tests = LOCAL_IMPORT_TESTS
        results.append(run_tests(profile_tests, profile, profile))

        # Run sync tests
        results.append(run_tests(SYNC_TESTS, profile, "sync"))

    # Run Sprint 4C tests once (profile-independent)
    if not args.skip_4c:
        results.append(run_tests(SPRINT_4C_TESTS, "local_import", "sprint4c"))

    # Generate summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "overall": "passed" if all(r["passed"] for r in results) else "failed",
        "total_passed": sum(r["passed_count"] for r in results),
        "total_failed": sum(r["failed_count"] for r in results),
        "duration_s": sum(r["duration_s"] for r in results),
    }

    out_path = os.path.join(REPORTS_DIR, "ci_profile_matrix.json")
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}")

    print(f"\n{'='*60}")
    print("PROFILE TEST MATRIX RESULTS")
    print(f"{'='*60}")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['label']} ({r['profile']}): {r['passed_count']} passed, {r['failed_count']} failed in {r['duration_s']}s")
    print(f"\nOverall: {summary['overall']}")
    print(f"Total: {summary['total_passed']} passed, {summary['total_failed']} failed")

    return summary


if __name__ == "__main__":
    main()
