"""408 专项 AI 老师固定动作 Prompt。

前端只能选择 ACTIONS 中的固定动作；禁止传入自由 prompt。
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "408-teacher-v1"

ACTION_DEFINITIONS: dict[str, dict[str, str]] = {
    "explain_correct": {
        "label": "为什么正确选项对？",
        "description": "解释正确选项成立的条件、关键推理和判断依据。",
        "instruction": "围绕正确选项，解释它为什么成立；明确关键条件与推理链。",
    },
    "explain_options": {
        "label": "为什么 A/B/C/D 错？",
        "description": "逐项说明各选项成立或不成立的原因。",
        "instruction": "逐项分析所有选项；对错误项指出具体错在概念、条件、边界或推理哪一步。",
    },
    "core_concept": {
        "label": "这道题真正考什么？",
        "description": "提炼核心考点、命题方式与识别信号。",
        "instruction": "提炼本题真正考查的 408 核心知识、题干识别信号和最短解题路径。",
    },
    "similar_question": {
        "label": "给我一道同类题",
        "description": "生成一道同知识点、相近难度的单选练习。",
        "instruction": "生成一道同知识点、相近难度、表述不同的单选题；必须给出可判定答案和简洁解析。",
    },
    "harder_question": {
        "label": "给我一道更难的题",
        "description": "生成一道同知识点但更强调综合判断的单选题。",
        "instruction": "生成一道同知识点、难度提高一级的单选题；增加条件组合或易混边界，但不得超出给定 408 上下文凭空引入冷门结论。",
    },
    "connect_knowledge": {
        "label": "帮我串联相关知识点",
        "description": "结合知识图谱梳理前置、相关和后续知识。",
        "instruction": "结合提供的知识图谱邻居，说明当前知识点与前置、相关、后续知识的连接；图谱没有证据时不要编造关系。",
    },
    "high_frequency_traps": {
        "label": "总结 408 高频陷阱",
        "description": "总结与本题知识点直接相关的高频易错边界。",
        "instruction": "只总结与当前题目和给定知识点直接相关的 408 高频陷阱、易混边界和检查动作；不要扩成通用备考文章。",
    },
}


def action_items() -> list[dict[str, str]]:
    return [
        {"action": action, "label": meta["label"], "description": meta["description"]}
        for action, meta in ACTION_DEFINITIONS.items()
    ]


def _bounded_json(value: Any, max_chars: int) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = str(value or "")
    return raw[:max_chars]


def build_408_teacher_prompt(*, action: str, context: dict[str, Any]) -> list[dict[str, str]]:
    meta = ACTION_DEFINITIONS[action]
    system = (
        "你是 MemoGrad 的 408 专项 AI 老师，只服务计算机学科专业基础综合（408）学习。"
        "你不是自由聊天机器人；本次只能完成指定固定动作。"
        "必须优先依据题目固定版本、官方题库解析、知识点、用户当前掌握状态、近期同知识点错误、已确认错因和知识图谱关系。"
        "不得引用其他用户数据。没有证据时明确说明证据不足，不要杜撰知识图谱关系、用户弱点或题库事实。"
        "个性化建议要根据 mastery/confidence/近期错因调整：低 mastery 时先补基础，高 mastery 但反复错时强调边界、审题或推理。"
        "输出严格 JSON，不要 markdown，不要额外字段。schema："
        '{"title":"","summary":"","sections":[{"heading":"","points":[""]}],'
        '"knowledge_points":[{"name":"","relation":"","mastery_hint":""}],'
        '"practice_question":null,'
        '"next_action":{"type":"none","label":"","params":{}}}'
        "。similar_question/harder_question 时 practice_question 必须为："
        '{"stem":"","options":{"A":"","B":"","C":"","D":""},"answer":"A",'
        '"analysis":"","difficulty_delta":0或1}；其他动作应为 null。'
        "sections 最多 4 组，每组 points 最多 5 条；语言简洁、面向考研 408 复盘。"
    )
    user = (
        f"固定动作={action}\n动作说明={meta['instruction']}\n"
        "上下文（仅可使用以下事实）：\n"
        + _bounded_json(context, 18000)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
