"""AI 学习引擎 Prompt 模板。每个场景一个函数，返回 messages list。"""

# ============================================================
# System Prompts
# ============================================================

SYSTEM_EXPLAIN = (
    "你是一个考研辅导老师，擅长数学二、408计算机、英语的题目讲解。"
    "请用中文回答，保持简洁清晰。"
    "请严格使用 JSON 格式输出：\n"
    '{"explanation": "整体讲解", '
    '"solution_steps": ["步骤1", "步骤2", "步骤3"], '
    '"key_knowledge_points": ["知识点1", "知识点2"], '
    '"common_mistakes": ["常见错误1", "常见错误2"]}'
)

SYSTEM_MISTAKE_ANALYSIS = (
    "你是一个考研辅导老师，擅长分析学生的错误原因。"
    "请用中文回答，保持简洁。"
    "请严格使用 JSON 格式输出：\n"
    '{"error_type": "概念理解错误", '
    '"analysis": "具体分析内容", '
    '"suggestion": "改进建议"}'
)

SYSTEM_REPORT = (
    "你是一个考研学习规划师。根据学生的学习数据，"
    "生成个性化的学习报告和建议。"
    "请用中文回答，保持简洁。"
    "请严格使用 JSON 格式输出：\n"
    '{"weak_points": [{"knowledge_point": "知识点名", "accuracy": 0.5, "suggestion": "建议"}], '
    '"strong_points": [{"knowledge_point": "知识点名", "accuracy": 0.9, "suggestion": "建议"}], '
    '"learning_suggestions": ["建议1", "建议2", "建议3"]}'
)


# ============================================================
# Prompt Builders
# ============================================================


def build_explain_prompt(
    stem: str,
    options: dict | None,
    answer: str,
    analysis: str | None,
    knowledge_points: list | None,
    user_answer: str | None = None,
    is_correct: bool | None = None,
    focus: str = "solution",
) -> list:
    """构建题目讲解 prompt。"""

    focus_hints = {
        "solution": "请重点讲解解题思路和步骤。",
        "mistake": "请重点分析可能的错误原因和避坑方法。",
        "knowledge": "请重点梳理涉及的知识点及其应用。",
    }
    focus_hint = focus_hints.get(focus, focus_hints["solution"])

    option_text = ""
    if options:
        option_text = "\n".join(f"  {k}. {v}" for k, v in options.items())

    user_context = ""
    if user_answer is not None:
        user_context += f"\n用户答案：{user_answer}"
    if is_correct is not None:
        user_context += f"\n回答正确：{'是' if is_correct else '否'}"

    return [
        {"role": "system", "content": SYSTEM_EXPLAIN},
        {
            "role": "user",
            "content": (
                f"题目：{stem}\n"
                f"{'选项：' + chr(10) + option_text if option_text else ''}\n"
                f"正确答案：{answer}\n"
                f"{'解析：' + analysis if analysis else ''}"
                f"{user_context}\n"
                f"涉及知识点：{knowledge_points or []}\n"
                f"{focus_hint}"
            ),
        },
    ]


def build_mistake_analysis_prompt(
    stem: str,
    options: dict | None,
    correct_answer: str,
    user_answer: str,
    analysis: str | None = None,
) -> list:
    """构建错因分析 prompt。"""

    option_text = ""
    if options:
        option_text = "\n".join(f"  {k}. {v}" for k, v in options.items())

    return [
        {"role": "system", "content": SYSTEM_MISTAKE_ANALYSIS},
        {
            "role": "user",
            "content": (
                f"题目：{stem}\n"
                f"{'选项：' + chr(10) + option_text if option_text else ''}\n"
                f"正确答案：{correct_answer}\n"
                f"用户答案：{user_answer}\n"
                f"{'解析：' + analysis if analysis else ''}\n"
                "请分析用户为什么做错，给出针对性的改进建议。"
            ),
        },
    ]


def build_report_prompt(
    subject: str,
    days: int,
    total: int,
    accuracy: float,
    knowledge_point_stats: list[dict],
) -> list:
    """构建学习报告 prompt。

    ``knowledge_point_stats`` 支持两种行形态（字段二选一，不能都缺）：
    - 错题诊断口径：mastery_rate / mastered / total_wrong（stats_service）
    - 练习正确率口径：accuracy / correct / total（ai_learning_service）
    """

    kp_text = ""
    for kp in knowledge_point_stats:
        if "mastery_rate" in kp:
            kp_text += f"  - {kp['knowledge_point']}: 错题掌握率 {kp['mastery_rate']:.0%}（已掌握{kp['mastered']}/{kp['total_wrong']}道错题）\n"
        else:
            kp_text += f"  - {kp['knowledge_point']}: 正确率 {kp['accuracy']:.0%}（{kp['correct']}/{kp['total']}）\n"

    return [
        {"role": "system", "content": SYSTEM_REPORT},
        {
            "role": "user",
            "content": (
                f"科目：{subject}\n"
                f"统计周期：最近 {days} 天\n"
                f"总做题数：{total}\n"
                f"总正确率：{accuracy:.0%}\n"
                f"各知识点表现（注意区分掌握进度与做题正确率）：\n{kp_text}\n"
                "请生成学习报告，识别薄弱点和优势点，给出 3-5 条具体学习建议。"
            ),
        },
    ]
