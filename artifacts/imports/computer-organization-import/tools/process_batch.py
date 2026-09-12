#!/usr/bin/env python3
"""Run pipeline batch, collect OCR evidence, and run audit comparison for a page range.

Sequential steps (share the 8080 OCR server):
  1. run_pipeline_batch.py --start S --end E
  2. collect_ocr_evidence.py --start S --end E
  3. audit_compare.py --start S --end E
  4. append a batch summary line

Usage:
    .venv/bin/python /abs/process_batch.py --start 11 --end 35
"""
import argparse
import os
import subprocess
import sys
import time

BASE = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import"
VENV = "/home/lmh/projects/postgraduate-ai/backend/.venv/bin/python"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--ai-repair", action="store_true")
    args = p.parse_args()

    log = f"{BASE}/logs/batch_{args.start}_{args.end}.log"
    t0 = time.time()

    # Step 1: pipeline
    cmd = [VENV, f"{BASE}/tools/run_pipeline_batch.py", "--start", str(args.start), "--end", str(args.end)]
    if args.ai_repair:
        cmd.append("--ai-repair")
    r1 = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/lmh/projects/postgraduate-ai/backend", timeout=3600)
    with open(log, "w") as f:
        f.write("=== PIPELINE ===\n" + r1.stdout + "\n" + r1.stderr[-2000:] + "\n")

    # Step 2: OCR evidence
    r2 = subprocess.run([VENV, f"{BASE}/tools/collect_ocr_evidence.py", "--start", str(args.start), "--end", str(args.end)],
                        capture_output=True, text=True, cwd="/home/lmh/projects/postgraduate-ai/backend", timeout=3600)
    with open(log, "a") as f:
        f.write("=== EVIDENCE ===\n" + r2.stdout + "\n" + r2.stderr[-1000:] + "\n")

    # Step 3: audit comparison
    r3 = subprocess.run([VENV, f"{BASE}/tools/audit_compare.py", "--start", str(args.start), "--end", str(args.end)],
                        capture_output=True, text=True, cwd="/home/lmh/projects/postgraduate-ai/backend", timeout=600)
    with open(log, "a") as f:
        f.write("=== AUDIT ===\n" + r3.stdout + "\n" + r3.stderr[-1000:] + "\n")

    elapsed = time.time() - t0
    print(f"[batch {args.start}-{args.end}] done in {elapsed:.0f}s")
    # print audit summary
    print(r3.stdout.split("=== DETAIL ===")[0])
    # log errors
    for name, r in (("pipeline", r1), ("evidence", r2), ("audit", r3)):
        if r.returncode != 0:
            print(f"  WARN {name} rc={r.returncode}: {r.stderr[-300:]}")


if __name__ == "__main__":
    main()
