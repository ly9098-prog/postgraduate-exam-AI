"""OCR pipeline DAG 定义。

将现有 OCR 标准化管线各阶段封装为 DAG 节点，
通过 DAG scheduler 统一编排执行顺序、区域路由和
mutation_guard 校验。

使用方式：
    from app.features.ocr_pipeline_dag import run_ocr_dag
    result = run_ocr_dag(text, trace_id="...")
"""

from __future__ import annotations

from functools import partial
from typing import Any

from app.core.dag_pipeline import DAGPipeline, IOType, StageNode
from app.features.code_detector import repair_unclosed_fences, wrap_code_fences
from app.features.text_normalizer import (
    _apply_global_arrow_fixes,
    _clean_text_regions,
    preprocess_ocr_noise,
)


def build_ocr_dag(
    enabled_strategies: set[str] | None = None,
    extra_watermark_patterns: list | None = None,
) -> DAGPipeline:
    """构建标准 OCR 标准化 DAG。

    Pipeline 拓扑（线性 DAG）：
        P0 (noise filter) → P1 (code fence) → P1.5 (repair fence)
        → P2 (text cleaning, guarded) → P3 (global fixes)

    Args:
        enabled_strategies: 可选的策略白名单（None = 全部启用）。
        extra_watermark_patterns: 额外水印规则列表。

    Returns:
        可执行的 DAGPipeline 实例。
    """
    return DAGPipeline(
        stages=[
            StageNode(
                name="p0_noise_filter",
                fn=preprocess_ocr_noise,
                description="移除孤立A/B/C/D、修复断裂箭头",
            ),
            StageNode(
                name="p1_code_fence",
                fn=wrap_code_fences,
                description="代码检测+```围栏包裹",
            ),
            StageNode(
                name="p1_5_repair_fence",
                fn=repair_unclosed_fences,
                description="未闭合围栏修复",
            ),
            StageNode(
                name="p2_text_cleaning",
                fn=partial(
                    _clean_text_regions,
                    enabled_strategies=enabled_strategies,
                    extra_watermark_patterns=extra_watermark_patterns,
                ),
                input_type=IOType.STR,
                output_type=IOType.STR,
                guard=True,
                description="区域化清洗(text只读, mutation_guard保护)",
            ),
            StageNode(
                name="p3_global_fixes",
                fn=_apply_global_arrow_fixes,
                description="全局箭头修复+尾部strip",
            ),
        ]
    )


def run_ocr_dag(
    text: str,
    *,
    trace_id: str = "",
    enabled_strategies: set[str] | None = None,
    extra_watermark_patterns: list[Any] | None = None,
) -> str:
    """通过 DAG overlay 执行 OCR 标准化管线。

    与 normalize_ocr_text() 行为等价，额外提供：
    - 每阶段的 mutation_guard 校验
    - 清晰的 stage 边界
    - 可扩展的 DAG 拓扑

    Args:
        text: OCR 原始文本。
        trace_id: 跟踪 ID。
        enabled_strategies: 策略白名单（None = 全部启用）。
        extra_watermark_patterns: 额外水印模式。

    Returns:
        标准化后的文本。
    """
    dag = build_ocr_dag(
        enabled_strategies=enabled_strategies,
        extra_watermark_patterns=extra_watermark_patterns,
    )
    return dag.run(text, trace_id=trace_id)
