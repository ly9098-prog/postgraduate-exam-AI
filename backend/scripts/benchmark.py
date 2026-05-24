"""简单 API 压测脚本。

用法:
    python scripts/benchmark.py [--url http://localhost:8000] [--concurrency 10] [--requests 100]
"""

import asyncio
import time
from argparse import ArgumentParser
from dataclasses import dataclass, field

import httpx

# 需要有效的 JWT token 才能测试需认证的端点
# 可通过先调用 /api/v1/auth/login 获取
HEALTH_ENDPOINT = "/health"
PUBLIC_ENDPOINTS = [
    "/health",
]
AUTH_ENDPOINTS = [
    "/api/v1/stats/overview",
    "/api/v1/practice/stats",
    "/api/v1/review/stats",
]


@dataclass
class Stats:
    total: int = 0
    success: int = 0
    fail: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return sorted(self.latencies)[len(self.latencies) // 2] if self.latencies else 0

    @property
    def p95(self) -> float:
        return sorted(self.latencies)[int(len(self.latencies) * 0.95)] if self.latencies else 0

    @property
    def p99(self) -> float:
        return sorted(self.latencies)[int(len(self.latencies) * 0.99)] if self.latencies else 0

    @property
    def avg(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0

    @property
    def rps(self) -> float:
        if not self.latencies:
            return 0
        total_time = max(self.latencies) - min(self.latencies)
        return self.total / total_time if total_time > 0 else 0

    def report(self, name: str):
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print(f"{'=' * 60}")
        print(f"  Total:    {self.total}")
        print(f"  Success:  {self.success}")
        print(f"  Fail:     {self.fail}")
        print(f"  Avg:      {self.avg * 1000:.1f}ms")
        print(f"  P50:      {self.p50 * 1000:.1f}ms")
        print(f"  P95:      {self.p95 * 1000:.1f}ms")
        print(f"  P99:      {self.p99 * 1000:.1f}ms")


async def make_request(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=30)
        elapsed = time.perf_counter() - start
        return resp.status_code < 500, elapsed
    except Exception:
        elapsed = time.perf_counter() - start
        return False, elapsed


async def run_benchmark(
    base_url: str,
    endpoints: list[str],
    concurrency: int,
    total_requests: int,
    headers: dict | None = None,
) -> Stats:
    stats = Stats(total=total_requests)

    async with httpx.AsyncClient(
        base_url=base_url,
        limits=httpx.Limits(max_connections=concurrency + 10),
    ) as client:
        sem = asyncio.Semaphore(concurrency)

        async def worker(endpoint: str):
            async with sem:
                success, latency = await make_request(client, endpoint, headers)
                stats.latencies.append(latency)
                if success:
                    stats.success += 1
                else:
                    stats.fail += 1

        tasks = []
        for i in range(total_requests):
            endpoint = endpoints[i % len(endpoints)]
            tasks.append(worker(endpoint))

        print(f"  发送 {total_requests} 个请求，并发 {concurrency}...")
        batch_start = time.perf_counter()
        await asyncio.gather(*tasks)
        batch_elapsed = time.perf_counter() - batch_start
        print(f"  完成，耗时 {batch_elapsed:.1f}s，QPS: {total_requests / batch_elapsed:.1f}")

    return stats


async def main():
    parser = ArgumentParser(description="2240AI API 压测")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--requests", type=int, default=100, help="总请求数")
    parser.add_argument("--token", default="", help="JWT token（用于需认证的端点）")
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    print(f"目标: {args.url}")
    print(f"并发: {args.concurrency}, 请求数: {args.requests}")

    # 1. Health check
    health_stats = await run_benchmark(
        args.url, [HEALTH_ENDPOINT], args.concurrency, args.requests, headers
    )
    health_stats.report("GET /health")

    # 2. Authenticated endpoints (if token provided)
    if args.token:
        stats_stats = await run_benchmark(
            args.url,
            AUTH_ENDPOINTS,
            args.concurrency,
            args.requests,
            headers,
        )
        stats_stats.report("Auth Endpoints (stats)")
    else:
        print("\nⓘ  跳过需认证的端点（未提供 --token）。")
        print("   使用方式: python scripts/benchmark.py --token <your_jwt>")


if __name__ == "__main__":
    asyncio.run(main())
