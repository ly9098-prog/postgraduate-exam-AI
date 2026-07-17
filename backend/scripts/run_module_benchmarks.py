#!/usr/bin/env python3
"""Module-level benchmark runner — cold start, warm P50/P95, throughput, memory.

Usage:
    python scripts/run_module_benchmarks.py
    python scripts/run_module_benchmarks.py --iterations 10 --warmup 3
    python scripts/run_module_benchmarks.py --modules reading_order --output ./reports

Outputs (in the output directory):
    run_manifest.json          # Environment fingerprint + fixture hash
    summary.json               # Aggregated metrics per module
    samples.jsonl              # Per-iteration samples
    metrics_by_module.json     # Detailed metrics grouped by module
    regressions.json           # Regression comparison vs baseline
    report.md                  # Human-readable report

Architecture:
    ModuleBenchmark     — define benchmark for a single module
    BenchmarkRegistry   — register all benchmarks
    BenchmarkRunner     — execute, sample, compare, report
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_ITERATIONS = 20
DEFAULT_WARMUP = 5
DEFAULT_OUTPUT_DIR = "reports/module_benchmarks"
CI_MODE = os.environ.get("CI", "").lower() in ("true", "1")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """Single benchmark iteration sample."""
    module: str
    iteration: int
    latency_ms: float
    output_digest: str
    output_item_count: int
    result_validity: str          # "valid" | "invalid" | "error"
    error_code: str | None        # error code if failed
    cold_start: bool = False      # True if measured in a fresh subprocess
    cpu_rss_mb: float = 0.0
    thread_count: int = 0


@dataclass
class BenchmarkResult:
    """Aggregated benchmark results for one module."""
    module: str
    samples: list[Sample]
    cold_samples: list[Sample] = field(default_factory=list)

    @property
    def warm_samples(self) -> list[Sample]:
        return [s for s in self.samples if not s.cold_start]

    @property
    def warm_latencies(self) -> list[float]:
        return [s.latency_ms for s in self.warm_samples]

    @property
    def warm_p50(self) -> float:
        vals = sorted(self.warm_latencies)
        if not vals:
            return 0.0
        return statistics.median(vals)

    @property
    def warm_p95(self) -> float:
        vals = sorted(self.warm_latencies)
        if not vals:
            return 0.0
        idx = min(int(len(vals) * 0.95), len(vals) - 1)
        return vals[idx]

    @property
    def mean_latency(self) -> float:
        vals = self.warm_latencies
        return statistics.mean(vals) if vals else 0.0

    @property
    def min_latency(self) -> float:
        vals = self.warm_latencies
        return min(vals) if vals else 0.0

    @property
    def max_latency(self) -> float:
        vals = self.warm_latencies
        return max(vals) if vals else 0.0

    @property
    def validity_pct(self) -> float:
        if not self.warm_samples:
            return 0.0
        valid = sum(1 for s in self.warm_samples if s.result_validity == "valid")
        return (valid / len(self.warm_samples)) * 100.0

    @property
    def cold_start_ms(self) -> float:
        if not self.cold_samples:
            return 0.0
        return statistics.mean(s.latency_ms for s in self.cold_samples)

    @property
    def cpu_rss_peak_mb(self) -> float:
        rss_values = [s.cpu_rss_mb for s in self.samples if s.cpu_rss_mb > 0]
        return max(rss_values) if rss_values else 0.0

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "samples": len(self.samples),
            "cold_samples": len(self.cold_samples),
            "warm_samples": len(self.warm_samples),
            "cold_start_ms": round(self.cold_start_ms, 2),
            "warm_p50_ms": round(self.warm_p50, 2),
            "warm_p95_ms": round(self.warm_p95, 2),
            "mean_latency_ms": round(self.mean_latency, 2),
            "min_latency_ms": round(self.min_latency, 2),
            "max_latency_ms": round(self.max_latency, 2),
            "cpu_rss_peak_mb": round(self.cpu_rss_peak_mb, 2),
            "output_validity_pct": round(self.validity_pct, 2),
        }


# ---------------------------------------------------------------------------
# Module benchmarks
# ---------------------------------------------------------------------------


class _ModuleBenchmark:
    """Base class for a single module's benchmark."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def setup(self) -> Any:
        """Prepare fixture data. Called once per benchmark."""
        return None

    async def run(self, fixture: Any) -> Sample:
        """Execute one iteration and return a Sample."""
        raise NotImplementedError

    async def teardown(self, fixture: Any) -> None:
        """Clean up fixture. Called once after all iterations."""
        pass


class ReadingOrderBenchmark(_ModuleBenchmark):
    """Benchmark the reading order transform adapter."""

    def __init__(self) -> None:
        super().__init__("reading_order")

    async def setup(self) -> Any:
        from app.core.document_ir import (
            BBox,
            DocumentIR,
            LineIR,
            PageIR,
            RegionIR,
            make_line_id,
            make_page_id,
            make_region_id,
            new_document,
        )

        doc = new_document()
        page_id = make_page_id(doc.document_id, 0)
        page = PageIR(page_id=page_id, page_index=0, width=800, height=600)

        # 10 regions with varying positions
        for idx in range(10):
            y = 30 + idx * 55
            rid = make_region_id(page_id, BBox(40, y, 760, y + 45), "bench", f"region_{idx}")
            lid = make_line_id(rid, BBox(40, y, 760, y + 45), f"text_{idx}")
            region = RegionIR(
                region_id=rid,
                region_type="text",
                bbox=BBox(40, y, 760, y + 45),
                lines=[LineIR(line_id=lid, text=f"Line {idx}", bbox=BBox(40, y, 760, y + 45))],
            )
            page.regions.append(region)

        doc.pages = [page]
        return doc

    async def run(self, fixture: Any) -> Sample:
        from app.features.ocr_adapter import ReadingOrderTransformAdapter

        adapter = ReadingOrderTransformAdapter()
        import copy
        doc_copy = copy.deepcopy(fixture)

        start = time.monotonic()
        result = await adapter.transform(doc_copy)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Validate output correctness
        validity = "valid"
        error_code = None
        if result.is_failure:
            validity = "error"
            error_code = result.error.code if result.error else "UNKNOWN"

        output_digest = hashlib.sha256(
            str(id(result.data) if result.data else "").encode()
        ).hexdigest()[:16]
        output_item_count = len(result.data.pages[0].reading_order) if result.is_success and result.data and result.data.pages else 0

        return Sample(
            module=self.name,
            iteration=0,
            latency_ms=elapsed_ms,
            output_digest=output_digest,
            output_item_count=output_item_count,
            result_validity=validity,
            error_code=error_code,
        )


class RuleFallbackBenchmark(_ModuleBenchmark):
    """Benchmark the rule fallback (passthrough) adapter."""

    def __init__(self) -> None:
        super().__init__("rule_fallback")

    async def setup(self) -> Any:
        from app.core.document_ir import new_document
        return new_document()

    async def run(self, fixture: Any) -> Sample:
        from app.features.ocr_adapter import RuleFallbackAdapter

        adapter = RuleFallbackAdapter()
        start = time.monotonic()
        result = await adapter.transform(fixture)
        elapsed_ms = (time.monotonic() - start) * 1000

        validity = "valid"
        error_code = None
        if result.is_failure:
            validity = "error"
            error_code = result.error.code if result.error else "UNKNOWN"

        return Sample(
            module=self.name,
            iteration=0,
            latency_ms=elapsed_ms,
            output_digest="passthrough",
            output_item_count=1,
            result_validity=validity,
            error_code=error_code,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class BenchmarkRegistry:
    """Registry of all module benchmarks."""

    def __init__(self) -> None:
        self._benchmarks: dict[str, _ModuleBenchmark] = {}

    def register(self, benchmark: _ModuleBenchmark) -> None:
        self._benchmarks[benchmark.name] = benchmark

    def get(self, name: str) -> _ModuleBenchmark | None:
        return self._benchmarks.get(name)

    def list(self) -> list[str]:
        return sorted(self._benchmarks.keys())

    def __len__(self) -> int:
        return len(self._benchmarks)


def create_default_registry() -> BenchmarkRegistry:
    """Create registry with all available benchmarks."""
    registry = BenchmarkRegistry()
    registry.register(ReadingOrderBenchmark())
    registry.register(RuleFallbackBenchmark())
    return registry


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    """Execute benchmarks, collect samples, generate reports."""

    def __init__(
        self,
        registry: BenchmarkRegistry,
        iterations: int = DEFAULT_ITERATIONS,
        warmup_iterations: int = DEFAULT_WARMUP,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        modules: list[str] | None = None,
        baseline_path: str | None = None,
    ):
        self._registry = registry
        self._iterations = iterations
        self._warmup = warmup_iterations
        self._output_dir = Path(output_dir)
        self._modules = modules or registry.list()
        self._baseline_path = Path(baseline_path) if baseline_path else None

    async def run_all(self) -> list[BenchmarkResult]:
        """Run benchmarks for all selected modules."""
        os.makedirs(self._output_dir, exist_ok=True)

        results: list[BenchmarkResult] = []

        for module_name in self._modules:
            benchmark = self._registry.get(module_name)
            if benchmark is None:
                print(f"  [SKIP] Unknown module: {module_name}")
                continue

            print(f"\n{'=' * 60}")
            print(f"  Benchmark: {module_name}")
            print(f"{'=' * 60}")

            result = BenchmarkResult(module=module_name)

            # Setup
            fixture = await benchmark.setup()

            # Warmup iterations
            if self._warmup > 0:
                print(f"  Warmup ({self._warmup} iterations)...")
                for i in range(self._warmup):
                    sample = await benchmark.run(fixture)
                    sample.iteration = -(i + 1)  # negative = warmup
                    print(f"    warmup {i + 1}/{self._warmup}: {sample.latency_ms:.2f}ms")

            # Measured iterations
            print(f"  Running ({self._iterations} iterations)...")
            for i in range(self._iterations):
                sample = await benchmark.run(fixture)
                sample.iteration = i
                result.samples.append(sample)
                print(f"    iter {i + 1}/{self._iterations}: {sample.latency_ms:.2f}ms "
                      f"[{sample.result_validity}]")

            # Teardown
            await benchmark.teardown(fixture)

            results.append(result)
            self._print_result_summary(result)

        # Generate outputs
        self._generate_outputs(results)

        return results

    def _print_result_summary(self, result: BenchmarkResult) -> None:
        print(f"\n  Results: {result.module}")
        print(f"    Warm P50:   {result.warm_p50:.2f}ms")
        print(f"    Warm P95:   {result.warm_p95:.2f}ms")
        print(f"    Min/Max:    {result.min_latency:.2f}ms / {result.max_latency:.2f}ms")
        print(f"    Validity:   {result.validity_pct:.1f}%")
        if result.cold_start_ms > 0:
            print(f"    Cold start: {result.cold_start_ms:.2f}ms")

    def _generate_outputs(self, results: list[BenchmarkResult]) -> None:
        """Generate all output files."""
        env_fingerprint = self._get_environment_fingerprint()

        # run_manifest.json
        manifest = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "hostname": platform.node(),
            "ci_mode": CI_MODE,
            "iterations": self._iterations,
            "warmup_iterations": self._warmup,
            "modules": self._modules,
            "fixture_hash": env_fingerprint.get("fixture_hash", ""),
            "config_hash": env_fingerprint.get("config_hash", ""),
        }
        self._write_json("run_manifest.json", manifest)

        # summary.json
        summary = {
            "environment": manifest,
            "results": {r.module: r.to_dict() for r in results},
        }
        self._write_json("summary.json", summary)

        # samples.jsonl
        samples_path = self._output_dir / "samples.jsonl"
        with open(samples_path, "w", encoding="utf-8") as f:
            for result in results:
                for sample in result.samples:
                    f.write(json.dumps({
                        "module": sample.module,
                        "iteration": sample.iteration,
                        "latency_ms": sample.latency_ms,
                        "output_digest": sample.output_digest,
                        "output_item_count": sample.output_item_count,
                        "result_validity": sample.result_validity,
                        "error_code": sample.error_code,
                        "cold_start": sample.cold_start,
                        "cpu_rss_mb": sample.cpu_rss_mb,
                    }, ensure_ascii=False) + "\n")
        print(f"\n  Samples: {samples_path}")

        # metrics_by_module.json
        metrics = {}
        for r in results:
            metrics[r.module] = r.to_dict()
        self._write_json("metrics_by_module.json", metrics)

        # regressions.json
        regressions = self._compare_baseline(results)
        self._write_json("regressions.json", regressions)

        # report.md
        report = self._generate_report(results, summary, regressions)
        report_path = self._output_dir / "report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  Report: {report_path}")

    def _write_json(self, filename: str, data: Any) -> None:
        path = self._output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  {path.name}")

    @staticmethod
    def _get_environment_fingerprint() -> dict:
        """Generate environment and fixture fingerprint."""
        try:
            from app.features.pipeline_fingerprint import build_pipeline_fingerprint
            fp = build_pipeline_fingerprint()
            config_hash = fp.config_hash
        except Exception:
            config_hash = "unknown"

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            git_commit = result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            git_commit = "unknown"

        fixture_hash = hashlib.sha256(
            f"{config_hash}::{sys.version}::{platform.machine()}".encode()
        ).hexdigest()[:16]

        return {
            "fixture_hash": fixture_hash,
            "config_hash": config_hash,
            "git_commit": git_commit,
        }

    def _compare_baseline(self, results: list[BenchmarkResult]) -> dict:
        """Compare results against baseline if available."""
        if not self._baseline_path or not self._baseline_path.exists():
            return {
                "baseline": None,
                "regressions": [],
                "note": "No baseline available for comparison",
            }

        try:
            with open(self._baseline_path) as f:
                baseline = json.load(f)
        except Exception as exc:
            return {"baseline": str(self._baseline_path), "regressions": [], "error": str(exc)}

        baseline_results = baseline.get("results", {})
        regressions = []

        for r in results:
            b = baseline_results.get(r.module, {})
            if not b:
                continue

            p50_change = ((r.warm_p50 - b.get("warm_p50_ms", 0)) / max(b.get("warm_p50_ms", 1), 0.001)) * 100
            p95_change = ((r.warm_p95 - b.get("warm_p95_ms", 0)) / max(b.get("warm_p95_ms", 1), 0.001)) * 100
            rss_change = ((r.cpu_rss_peak_mb - b.get("cpu_rss_peak_mb", 0)) / max(b.get("cpu_rss_peak_mb", 1), 0.001)) * 100

            module_regressions = []

            if p50_change > 10:
                module_regressions.append(f"P50 +{p50_change:.1f}% (>10% threshold)")
            if p95_change > 15:
                module_regressions.append(f"P95 +{p95_change:.1f}% (>15% threshold)")
            if rss_change > 20:
                module_regressions.append(f"RSS +{rss_change:.1f}% (>20% threshold)")

            if module_regressions:
                regressions.append({
                    "module": r.module,
                    "changes": {
                        "p50_pct": round(p50_change, 1),
                        "p95_pct": round(p95_change, 1),
                        "rss_pct": round(rss_change, 1),
                    },
                    "regressions": module_regressions,
                })

        return {
            "baseline": str(self._baseline_path),
            "regressions": regressions,
            "regression_count": len(regressions),
        }

    @staticmethod
    def _generate_report(
        results: list[BenchmarkResult],
        summary: dict,
        regressions: dict,
    ) -> str:
        """Generate a human-readable Markdown report."""
        lines = [
            "# Module Benchmark Report",
            "",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Python: {sys.version}",
            f"Platform: {platform.platform()}",
            f"CI mode: {CI_MODE}",
            "",
            "## Summary",
            "",
            "| Module | Samples | P50 (ms) | P95 (ms) | Min (ms) | Max (ms) | Validity |",
            "|--------|---------|----------|----------|----------|----------|----------|",
        ]

        for r in results:
            lines.append(
                f"| {r.module} | {len(r.warm_samples)} | "
                f"{r.warm_p50:.2f} | {r.warm_p95:.2f} | "
                f"{r.min_latency:.2f} | {r.max_latency:.2f} | "
                f"{r.validity_pct:.0f}% |"
            )

        if regressions.get("regressions"):
            lines.extend([
                "",
                "## Regressions",
                "",
            ])
            for reg in regressions["regressions"]:
                lines.append(f"- **{reg['module']}**:")
                for r_item in reg["regressions"]:
                    lines.append(f"  - {r_item}")

        lines.extend([
            "",
            "## Environment",
            "",
            f"- Git commit: {summary['environment'].get('git_commit', 'unknown')[:12]}",
            f"- Config hash: {summary['environment'].get('config_hash', 'unknown')}",
            f"- Fixture hash: {summary['environment'].get('fixture_hash', 'unknown')}",
            "",
            "## Baseline",
            f"- Baseline path: {regressions.get('baseline', 'none')}",
            f"- Regressions found: {regressions.get('regression_count', 0)}",
        ])

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Module-level benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/run_module_benchmarks.py
              python scripts/run_module_benchmarks.py --iterations 50 --warmup 10
              python scripts/run_module_benchmarks.py --modules reading_order
              python scripts/run_module_benchmarks.py --baseline reports/module_benchmarks/summary.json
              python scripts/run_module_benchmarks.py --output ./bench-reports
        """),
    )
    parser.add_argument(
        "--iterations", type=int, default=DEFAULT_ITERATIONS,
        help=f"Number of measured iterations (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--warmup", type=int, default=DEFAULT_WARMUP,
        help=f"Number of warmup iterations (default: {DEFAULT_WARMUP})",
    )
    parser.add_argument(
        "--modules", type=str, nargs="+", default=None,
        help="Specific modules to benchmark (default: all)",
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--baseline", type=str, default=None,
        help="Path to baseline summary.json for regression comparison",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("  Module Benchmark Runner")
    print("=" * 60)

    registry = create_default_registry()

    # Filter modules
    modules = args.modules
    if modules:
        unknown = [m for m in modules if m not in registry.list()]
        if unknown:
            print(f"  Unknown modules: {unknown}")
            print(f"  Available: {registry.list()}")
            sys.exit(1)
    else:
        modules = registry.list()

    if not modules:
        print("  No modules to benchmark.")
        return

    print(f"\n  Modules: {', '.join(modules)}")
    print(f"  Iterations: {args.iterations} (warmup: {args.warmup})")
    print(f"  Output: {args.output}")

    runner = BenchmarkRunner(
        registry=registry,
        iterations=args.iterations,
        warmup_iterations=args.warmup,
        output_dir=args.output,
        modules=modules,
        baseline_path=args.baseline,
    )

    await runner.run_all()
    print(f"\n{'=' * 60}")
    print(f"  Done. Reports in: {args.output}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
