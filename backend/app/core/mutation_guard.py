"""运行时变异防护 — 在 pipeline 各 stage 边界强制执行 Region 不可变约束。

核心功能：
1. assert_no_mutation() — 对比 Region 的哈希，检测内容变化
2. guard() — 包装 stage 函数，自动校验 code 区域未被修改
3. allow_code_mutation() — 上下文管理器，临时放行（用于 debug / migration）
"""

from __future__ import annotations

import contextlib
from typing import Any, Callable, Iterator

from app.core.immutable_regions import Region, TextRegions


class MutationError(RuntimeError):
    """当 code 区域内容被修改时抛出。"""
    pass


def assert_no_mutation(before: Region, after: Region) -> None:
    """断言两个 Region 的内容一致（哈希匹配）。

    Raises:
        MutationError: 如果 code 区域哈希不匹配。
    """
    if not before.is_code:
        return
    if before.hash == after.hash:
        return

    raise MutationError(
        f"Code region mutation detected:\n"
        f"  region_id={before.id}\n"
        f"  before={before.content[:120]!r}\n"
        f"  after= {after.content[:120]!r}"
    )


def verify_all_code_regions(regions: list[Region] | tuple[Region, ...] | TextRegions) -> list[str]:
    """验证所有 code 区域的完整性，返回被篡改的 region id 列表。

    Args:
        regions: 可迭代的 Region 对象列表或 TextRegions 实例。

    Returns:
        被篡改的 code 区域 id 列表（空列表表示全部安全）。
    """
    if isinstance(regions, TextRegions):
        regions = regions.regions

    corrupted: list[str] = []
    for r in regions:
        if r.is_code and not r.verify_integrity():
            corrupted.append(r.id)
    return corrupted


def guard(
    stage_fn: Callable[..., Any],
    input_text: str | TextRegions,
    *,
    trace_id: str = "",
    stage_name: str = "unknown",
) -> str | TextRegions:
    """包装 stage 函数，自动校验 code 区域未被修改。

    工作流程：
    1. 如果是 str 输入 → 转为 TextRegions（记录 code 区域哈希基线）
    2. 执行 stage_fn
    3. 如果输出是 TextRegions → 校验所有 code 区域哈希未变
    4. 返回输出

    注意：str 输入必须已含 ``` 围栏。guard 使用 from_fenced_text()
    解析而非 from_text()，避免在已围栏文本上重复运行代码检测。

    Args:
        stage_fn: 接收 str 或 TextRegions 并返回相同类型的函数。
        input_text: 输入文本（须已含 ``` 围栏）或已分区的 TextRegions。
        trace_id: （保留参数，不再使用）。
        stage_name: 阶段名称（用于错误信息）。

    Returns:
        stage_fn 的输出（str 或 TextRegions，与输入类型一致）。

    Raises:
        MutationError: 如果有 code 区域被修改。
    """
    is_text_regions = isinstance(input_text, TextRegions)

    if is_text_regions:
        before = input_text
    else:
        # 使用 from_fenced_text 而非 from_text，避免在已围栏的文本上
        # 重复运行 wrap_code_fences（DAG 的 P2 输入必定已围栏）
        before = TextRegions.from_fenced_text(input_text)

    # 记录 code 区域基线
    code_baseline = {r.id: r.hash for r in before if r.is_code}

    # 执行 stage
    output = stage_fn(input_text)

    # 按输出类型校验
    if isinstance(output, TextRegions):
        _check_code_regions(output.regions, code_baseline, stage_name)
    elif isinstance(output, str):
        # str→str 或 TextRegions→str：重新解析后校验
        after = TextRegions.from_fenced_text(output)
        _check_code_regions(after.regions, code_baseline, stage_name)

    return output


def _check_code_regions(
    regions: tuple[Region, ...] | list[Region],
    baseline: dict[str, str],
    stage_name: str,
) -> None:
    """校验 regions 中的 code 区域哈希与基线一致。"""
    mutated: list[str] = []
    for r in regions:
        if not r.is_code:
            continue
        expected = baseline.get(r.id)
        if expected is None:
            continue  # 新 region，不在基线中
        if r.hash != expected:
            mutated.append(
                f"  region_id={r.id}\n"
                f"    expected_hash={expected}\n"
                f"    actual_hash=  {r.hash}\n"
                f"    content={r.content[:120]!r}"
            )

    if mutated:
        raise MutationError(
            f"Code region mutation detected in stage '{stage_name}':\n"
            + "\n".join(mutated)
        )


@contextlib.contextmanager
def allow_code_mutation() -> Iterator[None]:
    """临时放行 code 区域修改的上下文管理器。

    仅用于 debug / migration 场景，生产代码中不使用。
    """
    yield
