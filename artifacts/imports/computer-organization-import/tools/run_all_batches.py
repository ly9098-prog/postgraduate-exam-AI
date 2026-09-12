#!/usr/bin/env python3
"""Run pipeline+evidence+audit for all remaining batches sequentially.

Batches: 36-60, 61-85, ... up to 528 (last batch by actual pages).
Logs each batch's audit summary to logs/bulk_batches.log.

Usage:
    .venv/bin/python /abs/run_all_batches.py
"""
import os
import subprocess
import sys
import time

BASE = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import"
VENV = "/home/lmh/projects/postgraduate-ai/backend/.venv/bin/python"
TOTAL = 528
BATCH = 25
START = 161


def main():
    log_path = f"{BASE}/logs/bulk_batches.log"
    start = START
    results = []
    while start <= TOTAL:
        end = min(start + BATCH - 1, TOTAL)
        t0 = time.time()
        print(f"[bulk] processing {start}-{end} ...", flush=True)
        r = subprocess.run(
            [VENV, f"{BASE}/tools/process_batch.py", "--start", str(start), "--end", str(end)],
            capture_output=True, text=True, cwd="/home/lmh/projects/postgraduate-ai/backend", timeout=5400,
        )
        elapsed = time.time() - t0
        summary = r.stdout.split("=== DETAIL ===")[0] if r.stdout else ""
        results.append((start, end, r.returncode, elapsed))
        with open(log_path, "a") as f:
            f.write(f"\n===== BATCH {start}-{end} (rc={r.returncode}, {elapsed:.0f}s) =====\n")
            f.write(summary)
            if r.returncode != 0:
                f.write("STDERR: " + r.stderr[-1500:] + "\n")
        print(f"[bulk] {start}-{end} done rc={r.returncode} in {elapsed:.0f}s", flush=True)
        start = end + 1
    print("\n[bulk] ALL BATCHES DONE")
    for s, e, rc, el in results:
        print(f"  {s}-{e}: rc={rc} {el:.0f}s")


if __name__ == "__main__":
    main()
