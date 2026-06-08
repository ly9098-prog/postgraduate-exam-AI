"""AI 降级方案。API 不可用时返回预设内容，不阻塞用户操作。"""

FALLBACK_ANALYSIS = {
    "error_analysis": "暂无解题技巧，请检查网络连接或稍后重试。建议先查看题目解析。",
    "suggestion": "建议回顾相关章节知识点，做更多同类题目巩固。",
    "knowledge_weakness": "暂无数据",
}

FALLBACK_ADVICE = {
    "overall_assessment": "当前无法生成 AI 学习建议，请稍后重试。",
    "priority_areas": [],
    "daily_suggestion": "建议继续按计划复习，重点复习做错的题目。",
    "weekly_plan": "保持每天做题 + 复习错题的节奏。",
}


def get_fallback_analysis() -> dict:
    return {**FALLBACK_ANALYSIS}


def get_fallback_advice() -> dict:
    return {**FALLBACK_ADVICE}


def get_fallback_summary() -> dict:
    return {
        "knowledge_point": "未知",
        "core_concept": "暂时无法生成知识点总结",
        "key_formulas": [],
        "common_pitfalls": [],
        "exam_tips": "请稍后重试",
    }


def get_fallback_enrich() -> dict:
    return {
        "subject": None,
        "chapter": None,
        "knowledge_points": [],
        "difficulty": None,
        "question_type": None,
        "question_category": None,
        "confidence": 0.0,
        "reason": "AI 服务不可用，请人工填写",
    }


def get_fallback_generation(count: int = 0) -> dict:
    return {"questions": [], "note": f"AI 服务不可用，未生成题目（请求 {count} 道）"}


def get_fallback_explain() -> dict:
    return {
        "explanation": "AI 服务暂时不可用。建议查看题目自带解析，或稍后重试。",
        "solution_steps": [],
        "key_knowledge_points": [],
        "common_mistakes": [],
    }


def get_fallback_report() -> dict:
    return {
        "weak_points": [],
        "strong_points": [],
        "learning_suggestions": [
            "AI 服务暂时不可用，建议根据各知识点正确率自行分析薄弱环节。",
            "重点复习正确率低于 60% 的知识点。",
            "每天保持一定量的练习，巩固已掌握的知识点。",
        ],
    }


def get_fallback_mistake_analysis() -> dict:
    return {
        "error_type": "unknown",
        "error_type_label": "无法分析（AI 不可用）",
        "analysis": "AI 服务暂时不可用，无法分析错误原因。建议查看题目解析。",
        "suggestion": "回顾相关知识点，做同类型题目巩固。",
    }


def get_fallback_complete(missing_fields: list[str]) -> dict:
    return {
        "subject": None,
        "question_type": None,
        "answer": "",
        "analysis": "",
        "knowledge_points": [],
        "difficulty": None,
        "answer_uncertain": True,
        "confidence": 0.0,
        "reason": f"AI 服务不可用，无法补全字段：{missing_fields}",
    }
