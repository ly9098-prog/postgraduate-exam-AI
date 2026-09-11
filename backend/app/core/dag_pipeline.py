"""DAG 调度器 — 轻量 overlay。

不替代现有 pipeline，只在外层编排执行顺序、区域路由和变异校验。

核心概念：
- StageNode: 一个 pipeline stage 的定义（函数、I/O 类型、是否启用 guard）
- DAGPipeline: 按定义顺序执行 stages，自动处理类型转换和 mutation_guard
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from app.core.immutable_regions import TextRegions
from app.core.mutation_guard import guard as apply_guard

logger = logging.getLogger(__name__)


class IOType(Enum):
    """Stage 的输入/输出数据类型。"""

    STR = auto()
    TEXT_REGIONS = auto()


@dataclass(frozen=True)
class StageNode:
    """DAG 节点 — 一个 pipeline stage 的定义。

    Attributes:
        name: 阶段标识（用于日志和错误信息）。
        fn: 执行函数。接受 str 或 TextRegions，返回 str 或 TextRegions。
        input_type: 期望的输入数据类型。
        output_type: 声明的输出数据类型。
        guard: 是否在此节点启用 mutation_guard（校验 code 区域不变）。
        description: 可选的阶段描述（用于日志和可观测性）。
    """

    name: str
    fn: Callable[..., Any]
    input_type: IOType = IOType.STR
    output_type: IOType = IOType.STR
    guard: bool = False
    description: str = ""


class DAGPipeline:
    """DAG overlay pipeline 调度器。

    职责：
    - 按定义顺序执行 stages（拓扑序，目前线性 DAG）
    - 自动处理 str ↔ TextRegions 转换
    - 可选的 mutation_guard 强制执行
    """

    def __init__(self, stages: list[StageNode]):
        assert stages, "DAGPipeline 至少需要一个 stage"
        self._stages = list(stages)

    @property
    def stages(self) -> list[StageNode]:
        return list(self._stages)

    def run(self, text: str, *, trace_id: str = "") -> str:
        """执行 DAG pipeline。

        Args:
            text: 输入文本。
            trace_id: 可选的跟踪 ID。

        Returns:
            pipeline 处理后的输出文本。
        """
        data: str | TextRegions = text

        for stage in self._stages:
            # 类型转换：str ↔ TextRegions
            data = self._convert_input(data, stage)

            # 执行
            logger.debug(
                "[DAG] stage=%s desc=%s input=%s",
                stage.name,
                stage.description or "-",
                type(data).__name__,
            )
            if stage.guard:
                data = apply_guard(
                    stage.fn, data, trace_id=trace_id, stage_name=stage.name
                )
            else:
                data = stage.fn(data)
            logger.debug(
                "[DAG] stage=%s done output=%s", stage.name, type(data).__name__
            )

            # 确保输出类型匹配声明
            data = self._ensure_output_type(data, stage)

        # 最终确保返回 str
        if isinstance(data, TextRegions):
            data = data.to_text()
        return data

    @staticmethod
    def _convert_input(data: str | TextRegions, stage: StageNode) -> str | TextRegions:
        """在 stage 执行前转换输入类型。"""
        if stage.input_type == IOType.TEXT_REGIONS and isinstance(data, str):
            return TextRegions.from_fenced_text(data)
        if stage.input_type == IOType.STR and isinstance(data, TextRegions):
            return data.to_text()
        return data

    @staticmethod
    def _ensure_output_type(
        data: str | TextRegions, stage: StageNode
    ) -> str | TextRegions:
        """在 stage 执行后确保输出类型匹配声明。"""
        if stage.output_type == IOType.TEXT_REGIONS and isinstance(data, str):
            return TextRegions.from_fenced_text(data)
        if stage.output_type == IOType.STR and isinstance(data, TextRegions):
            return data.to_text()
        return data
