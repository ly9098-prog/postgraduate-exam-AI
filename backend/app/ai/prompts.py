"""Prompt 模板管理。每个场景一个函数，返回 messages list。"""

SYSTEM_PROMPTS = {
    "error_analysis": (
        "你是一个考研辅导老师，擅长分析数学二、408计算机、英语的错题。"
        "请分析学生的错误原因，给出针对性的学习建议。\n"
        "请用中文回答，以 JSON 格式输出：\n"
        '{"error_analysis": "错误原因分析", '
        '"knowledge_weakness": "涉及的知识点盲区", '
        '"suggestion": "具体学习建议", '
        '"similar_problem_hint": "类似题目解题思路"}'
    ),
    "study_advice": (
        "你是一个考研学习规划师。根据学生的错题统计数据，"
        "给出有针对性的学习计划和复习建议。\n"
        "请用中文回答，以 JSON 格式输出：\n"
        '{"overall_assessment": "总体评估", '
        '"priority_areas": ["优先复习的知识点1", "知识点2"], '
        '"daily_suggestion": "今日学习建议", '
        '"weekly_plan": "本周复习计划"}'
    ),
    "summary": (
        "你是一个考研知识点总结专家。请根据提供的知识点列表，"
        "给出系统性的知识总结，包括概念、公式、常见题型和易错点。\n"
        "请用中文回答，以 JSON 格式输出：\n"
        '{"knowledge_point": "知识点名称", '
        '"core_concept": "核心概念", '
        '"key_formulas": ["公式1", "公式2"], '
        '"common_pitfalls": ["易错点1", "易错点2"], '
        '"exam_tips": "解题技巧"}'
    ),
    "enrich_question": (
        "你是考研题库整理助手。根据题目内容，分析其学科、章节、知识点、难度和题型。"
        "所有结果都将进入人工审核流程，请只输出客观判断。\n"
        "学科取值：math2 / exam408 / english。\n"
        "题型取值：choice / fill / subjective。\n"
        "难度 1-5（1 最易，5 最难）。\n"
        "数学公式输出规则（必须遵守）：\n"
        "- 所有数学内容必须使用 LaTeX 格式，行内公式用 $...$，块级公式用 $$...$$\n"
        "- 禁止使用 Unicode 数学符号（如 ² ∑ √），改用 LaTeX 命令（^2 \\sum \\sqrt{}）\n"
        "- 示例：错误 'x²+y²=z²'，正确 '$x^2+y^2=z^2$'\n"
        "请用中文回答，严格 JSON 格式输出：\n"
        '{"subject": "math2", '
        '"chapter": "高等数学/一元函数微分学", '
        '"knowledge_points": ["导数定义", "求导公式"], '
        '"difficulty": 3, '
        '"question_type": "choice", '
        '"question_category": "计算题", '
        '"confidence": 0.85, '
        '"reason": "依据题干涉及导数定义和基础求导公式判断"}'
    ),
    "generate_questions": (
        "你是考研出题专家。根据指定的学科、知识点、难度和数量生成练习题。"
        "生成的题目仅作为草稿，必须进入人工审核后才能入库。\n"
        "学科：math2 / exam408 / english。题型：choice / fill / subjective。\n"
        "数学公式输出规则（必须遵守）：\n"
        "- 所有数学内容必须使用 LaTeX 格式，行内公式用 $...$，块级公式用 $$...$$\n"
        "- 禁止使用 Unicode 数学符号（如 ² ∑ √ π），改用 LaTeX（^2 \\sum \\sqrt{} \\pi）\n"
        "- 示例：错误 '求f(x)=x²的导数'，正确 '求 $f(x)=x^2$ 的导数'\n"
        "- 示例：错误 '∫₀¹x dx'，正确 '$\\int_0^1 x\\,dx$'\n"
        "请严格使用 JSON 格式输出，结构如下：\n"
        '{"questions": [{'
        '"subject": "math2", '
        '"question_type": "choice", '
        '"stem": "题干内容（数学公式用 $...$）", '
        '"options": {"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}, '
        '"answer": "A", '
        '"analysis": "解析（数学公式用 $...$）", '
        '"knowledge_points": ["知识点1"], '
        '"difficulty": 3'
        "}]}\n"
        "若题型不是 choice，options 可为空对象 {}。"
    ),
    "question_repair": (
        "你是考研题库修复助手。根据 OCR 或规则解析的原始题目文本，"
        "将其修复为标准化的题目结构。\n"
        "规则：\n"
        "1. 提取题干：去除题号前缀、题型标签、多余空白\n"
        "2. 结构化选项：若原文有 A. B. C. D. 等选项，整理为 {\"A\": \"...\", \"B\": \"...\"}\n"
        "3. 标准化答案：单选大写单字母（如 \"A\"），多选逗号分隔大写（如 \"A,C\"），"
        "判断映射为 T/F，填空/主观保留原文本\n"
        "4. 识别题型：single_choice / multiple_choice / true_false / fill_blank / subjective\n"
        "5. 提取解析：若有解析内容，去除\"解析：\"等标签前缀\n"
        "6. 若某字段确实无法确定，填空字符串而不要编造\n"
        "数学公式输出规则：所有数学内容用 LaTeX（行内 $...$，块级 $$...$$），"
        "禁止使用 Unicode 数学符号。\n"
        "请严格使用 JSON 格式输出：\n"
        '{"question_type": "single_choice", '
        '"stem": "题干（数学公式用 $...$）", '
        '"options": {"A": "选项A", "B": "选项B"}, '
        '"answer": "A", '
        '"analysis": "解析", '
        '"confidence": 0.85, '
        '"repair_actions": ["stem_cleaned", "options_structured"]}\n'
        "repair_actions 可选值：stem_cleaned / options_structured / answer_normalized / "
        "type_detected / analysis_extracted / answer_filled"
    ),
    "complete_question": (
        "你是考研题目补全助手。根据已有的题干和上下文，补全缺失字段。"
        "你的输出仅是辅助提示，必须经过人工审核后才能采用。"
        "如果你不确定，请将对应字段留空字符串而不要编造。\n"
        "数学公式输出规则：所有数学内容用 LaTeX（行内 $...$，块级 $$...$$），"
        "禁止使用 Unicode 数学符号。\n"
        "请用中文回答，严格 JSON 格式输出：\n"
        '{"subject": "math2", '
        '"question_type": "choice", '
        '"answer": "A", '
        '"analysis": "解析（若不确定可留空）", '
        '"knowledge_points": ["知识点1"], '
        '"difficulty": 3, '
        '"answer_uncertain": false, '
        '"confidence": 0.6, '
        '"reason": "推理依据"}'
    ),
}


def build_error_analysis(question: dict, user_answer: str, correct_answer: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["error_analysis"]},
        {
            "role": "user",
            "content": (
                f"【题目】{question.get('content', {}).get('text', '')}\n"
                f"【选项】{question.get('options', {})}\n"
                f"【正确答案】{correct_answer}\n"
                f"【我的答案】{user_answer}\n"
                f"【知识点】{question.get('knowledge_points', [])}\n"
                "请分析我为什么做错，并给出学习建议。"
            ),
        },
    ]


def build_study_advice(
    subject_stats: list[dict],
    weak_points: list[str],
    recent_wrong: list[dict],
) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["study_advice"]},
        {
            "role": "user",
            "content": (
                f"【各科错题统计】{subject_stats}\n"
                f"【薄弱知识点】{weak_points}\n"
                f"【最近错题】{recent_wrong[:5]}\n"
                "请根据以上数据给出学习建议。"
            ),
        },
    ]


def build_summary(knowledge_points: list[str]) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["summary"]},
        {
            "role": "user",
            "content": f"请总结以下知识点：{knowledge_points}",
        },
    ]


def build_enrich_question(qi: dict) -> list:
    """对一条 question_imports 记录补全学科/章节/知识点/难度/题型。"""
    stem = (qi.get("parsed_content") or {}).get("text") or ""
    options = qi.get("parsed_options") or {}
    answer = qi.get("parsed_answer") or ""
    analysis = qi.get("parsed_analysis") or ""
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["enrich_question"]},
        {
            "role": "user",
            "content": (
                f"【题干】{stem}\n"
                f"【选项】{options}\n"
                f"【答案】{answer}\n"
                f"【解析】{analysis}\n"
                "请输出该题的学科、章节、知识点、难度、题型与置信度。"
            ),
        },
    ]


def build_generate_questions(
    subject: str,
    knowledge_points: list[str],
    difficulty: int,
    count: int,
    question_type: str = "choice",
    extra_hint: str | None = None,
) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["generate_questions"]},
        {
            "role": "user",
            "content": (
                f"【学科】{subject}\n"
                f"【知识点】{knowledge_points}\n"
                f"【难度】{difficulty}（1-5）\n"
                f"【题型】{question_type}\n"
                f"【数量】{count}\n"
                f"【附加要求】{extra_hint or '无'}\n"
                "请生成符合要求的练习题，输出 JSON。"
            ),
        },
    ]


def build_repair_question(raw_text: str, existing: dict | None = None) -> list:
    """构建题目修复 prompt。"""
    existing_info = ""
    if existing:
        existing_info = (
            f"【规则解析题干】{existing.get('stem', '')}\n"
            f"【规则解析选项】{existing.get('options', [])}\n"
            f"【规则解析答案】{existing.get('answer', '')}\n"
            f"【规则解析题型】{existing.get('question_type', '')}\n"
            f"【规则解析解析】{existing.get('analysis', '')}\n"
            f"【已知错误】{existing.get('errors', [])}\n"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["question_repair"]},
        {
            "role": "user",
            "content": (
                f"【原始文本】\n{raw_text}\n\n"
                f"{existing_info}"
                "请修复以上题目，输出标准 JSON。"
            ),
        },
    ]


def build_complete_question(qi: dict, missing_fields: list[str]) -> list:
    stem = (qi.get("parsed_content") or {}).get("text") or qi.get("raw_text") or ""
    options = qi.get("parsed_options") or {}
    answer = qi.get("parsed_answer") or ""
    analysis = qi.get("parsed_analysis") or ""
    subject = qi.get("subject") or ""
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["complete_question"]},
        {
            "role": "user",
            "content": (
                f"【已有题干】{stem}\n"
                f"【已有选项】{options}\n"
                f"【已有答案】{answer}\n"
                f"【已有解析】{analysis}\n"
                f"【已有学科】{subject}\n"
                f"【缺失字段】{missing_fields}\n"
                "请仅补全缺失字段，已有字段保持不变。若答案不确定，"
                "请将 answer_uncertain 设为 true。"
            ),
        },
    ]
