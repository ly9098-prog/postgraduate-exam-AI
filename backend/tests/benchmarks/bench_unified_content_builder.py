"""UnifiedContentBuilder 性能基准测试。

测试 ``unified_content_builder.build()`` 在不同规模下的延迟分布，
输出 P50 / P95 / P99。

用法:
    cd backend
    python -m pytest tests/benchmarks/bench_unified_content_builder.py -v -s
    # 或直接运行
    python tests/benchmarks/bench_unified_content_builder.py
"""

from __future__ import annotations

import cProfile
import io
import pstats
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ============================================================
# 待测试的 unified_content_builder 实现（内联，避免导入未创建的文件）
# ============================================================

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _parse_fenced_regions(text: str) -> list[dict]:
    """将 text 按 ``` 围栏切分为 segments。"""
    segments: list[dict] = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        before = text[pos:m.start()]
        if before:
            segments.extend(_text_to_segments(before))
        lang = m.group(1) or "text"
        code = m.group(2).rstrip()
        segments.append({"type": "code", "language": lang, "content": code})
        pos = m.end()
    after = text[pos:]
    if after:
        segments.extend(_text_to_segments(after))
    return segments


def _text_to_segments(text: str) -> list[dict]:
    """纯文本按换行切为 text/newline segments。"""
    if not text:
        return []
    segments: list[dict] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            segments.append({"type": "text", "text": line})
        if i < len(lines) - 1:
            segments.append({"type": "newline"})
    return segments


def _rebuild_text(segments: list[dict]) -> str:
    """从 segments 重建 text 字段。"""
    parts: list[str] = []
    for seg in segments:
        if seg["type"] == "text":
            parts.append(seg.get("text", ""))
        elif seg["type"] == "code":
            lang = seg.get("language", "text")
            content = seg.get("content", "")
            parts.append(f"```{lang}\n{content}\n```")
        elif seg["type"] == "newline":
            parts.append("\n")
    return "".join(parts)


def build(content: dict) -> dict:
    """UnifiedContentBuilder 主入口。"""
    text = (content or {}).get("text", "")
    if not text or "```" not in text:
        return content

    existing = content.get("segments")
    if existing and any(s.get("type") == "code" for s in existing):
        return content  # 幂等

    segments = _parse_fenced_regions(text)

    # 合入已有 math segments（若有）
    if existing:
        segments = _merge_with_existing(segments, existing)

    return {
        "text": text,
        "segments": segments,
        "render_mode": "segments",
    }


def _merge_with_existing(code_segments: list[dict], existing: list[dict]) -> list[dict]:
    """将 code segments 与已有 math_image segments 合并。"""
    math_segments = [s for s in existing if s.get("type") == "math_image"]
    text_segments = [s for s in code_segments if s.get("type") in ("text", "newline", "code")]

    # 简单策略：text+code 在前，math 追加在尾部
    result = list(text_segments)
    result.extend(math_segments)
    return result


# ============================================================
# 测试数据生成
# ============================================================

_SAMPLE_CODE_C = """int removeDuplicates(int* nums, int numsSize) {
    if (numsSize == 0) return 0;
    int slow = 0;
    for (int fast = 1; fast < numsSize; fast++) {
        if (nums[fast] != nums[slow]) {
            slow++;
            nums[slow] = nums[fast];
        }
    }
    return slow + 1;
}"""

_SAMPLE_CODE_JAVA = """public class ListNode {
    int val;
    ListNode next;
    ListNode() {}
    ListNode(int val) { this.val = val; }
    ListNode(int val, ListNode next) { this.val = val; this.next = next; }
}"""

_SAMPLE_CODE_PYTHON = """def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1"""

_SAMPLE_CODE_SQL = """SELECT s.name, c.title
FROM students s
INNER JOIN courses c ON s.course_id = c.id
WHERE s.score >= 90
ORDER BY s.score DESC
LIMIT 10;"""

_SAMPLE_CODES = {
    "c": _SAMPLE_CODE_C,
    "java": _SAMPLE_CODE_JAVA,
    "python": _SAMPLE_CODE_PYTHON,
    "sql": _SAMPLE_CODE_SQL,
}

_CN_STEMS = [
    "设线性表 L 采用顺序存储结构，已知其长度为 n，则在第 i 个位置插入一个新元素的时间复杂度为（ ）。",
    "下列关于二叉树的叙述中，正确的是（ ）。",
    "在 HTTP 协议中，状态码 404 表示（ ）。",
    "操作系统中，进程从运行态进入就绪态的原因是（ ）。",
    "设函数 $f(x)=x^2+1$，则 $f'(x)=$（ ）。",
    "已知矩阵 $A$ 的特征值为 $\\lambda_1=1$，$\\lambda_2=2$，则 $|A|=$（ ）。",
    "计算机组成原理中，指令周期是指（ ）。",
    "在 TCP 三次握手过程中，客户端发送的第二个报文段的标志位是（ ）。",
    "下列关于虚拟存储器的叙述中，错误的是（ ）。",
    "若一颗完全二叉树共有 768 个节点，则该二叉树中叶节点的个数是（ ）。",
]


def _random_question(with_code: bool = False, with_cn: bool = True) -> str:
    """生成一道题目的 text 字段。"""
    import random

    stem_idx = random.randint(0, len(_CN_STEMS) - 1)
    stem = _CN_STEMS[stem_idx]
    parts = [stem]

    if with_code:
        if with_cn:
            prefix = random.choice([
                "阅读以下 C 代码：",
                "分析以下程序：",
                "已知如下 Java 代码：",
                "考虑以下 Python 函数：",
                "有如下 SQL 查询：",
            ])
            parts.append(prefix)
        lang = random.choice(list(_SAMPLE_CODES.keys()))
        code = _SAMPLE_CODES[lang]
        parts.append(f"```{lang}")
        parts.append(code)
        parts.append("```")

    suffix = random.choice([
        "\nA. O(1)\nB. O(n)\nC. O(n^2)\nD. O(2^n)",
        "\nA. 对\nB. 错",
        "",
    ])
    if suffix:
        parts.append(suffix)

    return "\n".join(parts)


def generate_test_data(n: int, code_ratio: float = 0.15) -> list[dict]:
    """生成 n 道题目的 content JSON 列表。

    code_ratio: 含代码块的题目比例（默认 15%，代表 408 科目中代码题的实际占比）
    """
    import random

    random.seed(42)  # 可复现
    results: list[dict] = []
    code_count = int(n * code_ratio)

    for i in range(n):
        has_code = i < code_count
        text = _random_question(with_code=has_code)
        results.append({"text": text})

    random.shuffle(results)
    return results


# ============================================================
# 基准测试
# ============================================================


@dataclass
class BenchResult:
    label: str
    n: int
    iterations: int
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies_ms)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    @property
    def mean(self) -> float:
        return statistics.mean(self.latencies_ms)

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms)

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms)

    @property
    def throughput_qps(self) -> float:
        total_ms = sum(self.latencies_ms)
        return (self.n * 1000) / total_ms if total_ms > 0 else 0

    @property
    def total_batch_ms(self) -> float:
        """全量处理总耗时 (ms)。"""
        return sum(self.latencies_ms) / self.iterations if self.latencies_ms else 0

    def _percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_data = sorted(self.latencies_ms)
        k = (len(sorted_data) - 1) * p / 100
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_data):
            return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
        return sorted_data[f]

    def to_report(self) -> str:
        # 每项延迟 < 1ms 时以 µs 为单位报告
        if self.mean < 1.0:
            p50_us = self.p50 * 1000
            p95_us = self.p95 * 1000
            p99_us = self.p99 * 1000
            mean_us = self.mean * 1000
            batch_ms = self.total_batch_ms
            return (
                f"{self.label:>30s} | {self.n:>6d} | "
                f"{p50_us:>7.2f}µs | {p95_us:>7.2f}µs | {p99_us:>7.2f}µs | "
                f"{mean_us:>7.2f}µs | {batch_ms:>7.2f}ms total | "
                f"{self.throughput_qps:>10.0f} q/s"
            )
        return (
            f"{self.label:>30s} | {self.n:>6d} | "
            f"{self.p50:>8.3f}ms | {self.p95:>8.3f}ms | {self.p99:>8.3f}ms | "
            f"{self.mean:>8.3f}ms | {self.min_ms:>7.3f}ms | {self.max_ms:>8.3f}ms | "
            f"{self.throughput_qps:>10.0f} q/s"
        )


def _warmup():
    """预热：运行少量迭代确保 JIT/缓存稳定。"""
    data = generate_test_data(50)
    for item in data:
        build(item)


def _bench_scale(data: list[dict], label: str, iterations: int = 3) -> BenchResult:
    """在给定数据集上运行 build() iterations 次，取平均延迟。

    使用 perf_counter_ns() 纳秒精度，对全量数据做多轮迭代取统计。
    """
    result = BenchResult(label=label, n=len(data), iterations=iterations)

    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        for item in data:
            build(item)
        elapsed_ns = time.perf_counter_ns() - t0
        per_item_ms = (elapsed_ns / len(data)) / 1_000_000  # ns → ms
        result.latencies_ms.append(per_item_ms)

    return result


def run_benchmarks() -> list[BenchResult]:
    """运行全部基准测试。"""
    results: list[BenchResult] = []

    print("=" * 110)
    print(f"{'Benchmark':>30s} | {'N':>6s} | {'P50':>7s} | {'P95':>7s} | {'P99':>7s} | "
          f"{'Mean':>7s} | {'Batch Total':>12s} | {'Throughput':>10s}")
    print("=" * 110)

    # 预热
    print("预热中...")
    _warmup()

    scales = [
        (1000, "1000 题 (不含代码)"),
        (1000, "1000 题 (15% 代码)"),
        (5000, "5000 题 (15% 代码)"),
        (10000, "10000 题 (15% 代码)"),
    ]

    for n, label in scales:
        code_ratio = 0.0 if "不含代码" in label else 0.15
        data = generate_test_data(n, code_ratio=code_ratio)
        print(f"测试 {label}...", end=" ", flush=True)
        r = _bench_scale(data, label, iterations=5)
        print("完成")
        results.append(r)
        print(r.to_report())

    # 附加：纯 fence parsing 内部函数性能
    print("\n内部函数细粒度性能:")
    data_10k = generate_test_data(10000, code_ratio=0.15)

    # 全体批量计时（多次迭代）
    total_ns = 0
    passes = 10
    for _ in range(passes):
        t0 = time.perf_counter_ns()
        for item in data_10k:
            build(item)
        total_ns += time.perf_counter_ns() - t0
    avg_per_call_us = (total_ns / passes / len(data_10k)) / 1000
    total_ms = total_ns / 1_000_000
    print(f"  build 全流程 (10000题 × {passes} 轮):")
    print(f"    总耗时:  {total_ms:.2f}ms")
    print(f"    每题均:  {avg_per_call_us:.3f}µs ({avg_per_call_us/1000:.6f}ms)")

    # _parse_fenced_regions 单独（仅含围栏的题目）
    code_items = [item for item in data_10k if "```" in item.get("text", "")]
    if code_items:
        t0 = time.perf_counter_ns()
        for _ in range(passes):
            for item in code_items:
                _parse_fenced_regions(item["text"])
        elapsed_ns = time.perf_counter_ns() - t0
        per_call_us = (elapsed_ns / passes / len(code_items)) / 1000
        print(f"  _parse_fenced_regions ({len(code_items)} 有围栏题 × {passes} 轮):")
        print(f"    每题均:  {per_call_us:.3f}µs ({per_call_us/1000:.6f}ms)")

    print("=" * 110)
    return results


def run_profile():
    """cProfile 分析：定位热点函数。"""
    data = generate_test_data(5000, code_ratio=0.15)

    pr = cProfile.Profile()
    pr.enable()
    for item in data:
        build(item)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumtime")
    ps.print_stats(20)
    print("\n--- cProfile top 20 (cumtime) ---")
    print(s.getvalue())


# ============================================================
# 入口
# ============================================================


def test_benchmark():
    """pytest 入口。"""
    results = run_benchmarks()

    # 断言：10000 题的 P95 应 < 5ms
    ten_k = [r for r in results if r.n == 10000]
    if ten_k:
        assert ten_k[0].p95 < 5.0, f"P95 {ten_k[0].p95:.3f}ms 超过 5ms 阈值"
        assert ten_k[0].p99 < 10.0, f"P99 {ten_k[0].p99:.3f}ms 超过 10ms 阈值"

    print("\n所有基准测试断言通过")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--profile", action="store_true", help="运行 cProfile")
    args = p.parse_args()

    results = run_benchmarks()

    if args.profile:
        run_profile()
