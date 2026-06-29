"""Prompt 模板管理。每个场景一个函数，返回 messages list。"""

import json

SYSTEM_PROMPTS = {
    "error_analysis": (
        "你是一个考研解题技巧专家，擅长总结数学二、408计算机、英语的快速解题方法。"
        "请给出简洁实用的解题思路和答题技巧，避免冗长分析。\n"
        "对于涉及公式计算的题目，在 knowledge_weakness 中列出核心公式并简要说明使用场景。\n"
        "输出要求：error_analysis 用 1-3 句描述解题切入点和关键步骤，最多 100 字；"
        "knowledge_weakness 列出核心知识点/公式及使用场景，最多 100 字；"
        "suggestion 总结快速解题方法和常见考法，最多 100 字。\n"
        "请用中文回答，以 JSON 格式输出：\n"
        '{"error_analysis": "解题思路（切入点、关键步骤）", '
        '"knowledge_weakness": "核心考点与公式（含使用场景）", '
        '"suggestion": "快速解题方法（答题技巧、常见考法）"}'
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
        "学科使用 subject_id（整数），从给定科目列表中选择。\n"
        "题型取值：choice / fill / subjective。\n"
        "难度 1-5（1 最易，5 最难）。\n"
        "数学公式输出规则（必须遵守）：\n"
        "- 所有数学内容必须使用 LaTeX 格式，行内公式用 $...$，块级公式用 $$...$$\n"
        "- 禁止使用 Unicode 数学符号（如 ² ∑ √），改用 LaTeX 命令（^2 \\sum \\sqrt{}）\n"
        "- 示例：错误 'x²+y²=z²'，正确 '$x^2+y^2=z^2$'\n"
        "请用中文回答，严格 JSON 格式输出：\n"
        '{"subject_id": 3, '
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
        "学科使用 subject_id（整数）。题型：choice / fill / subjective。\n"
        "数学公式输出规则（必须遵守）：\n"
        "- 所有数学内容必须使用 LaTeX 格式，行内公式用 $...$，块级公式用 $$...$$\n"
        "- 禁止使用 Unicode 数学符号（如 ² ∑ √ π），改用 LaTeX（^2 \\sum \\sqrt{} \\pi）\n"
        "- 示例：错误 '求f(x)=x²的导数'，正确 '求 $f(x)=x^2$ 的导数'\n"
        "- 示例：错误 '∫₀¹x dx'，正确 '$\\int_0^1 x\\,dx$'\n"
        "请严格使用 JSON 格式输出，结构如下：\n"
        '{"questions": [{'
        '"subject_id": 3, '
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
        "1. 提取题干：去除题号前缀（如\"01.\"\"1)\"）、题型标签（如\"单选题\"\"选择\"），"
        "仅删除行首行尾多余空白，保留所有结构换行\n"
        "2. 结构化选项：若原文有 A. B. C. D. 等选项，整理为 {\"A\": \"...\", \"B\": \"...\"}\n"
        "3. 标准化答案：单选大写单字母（如 \"A\"），多选逗号分隔大写（如 \"A,C\"），"
        "判断映射为 T/F，填空/主观保留原文本\n"
        "4. 识别题型：single_choice / multiple_choice / true_false / fill_blank / subjective\n"
        "5. 提取解析：若有解析内容，去除\"解析：\"等标签前缀\n"
        "6. 若某字段确实无法确定，填空字符串而不要编造\n"
        "7. 修复 OCR 罗马数字混淆：选项文本中若数字 1 出现在罗马数字上下文"
        "（如选项 \"1、II\" 明显应为 \"I、II\"），将 1 修正为 I；\n"
        "   同时检查题干和选项中的罗马数字序列（I/II/III/IV/V）是否连续递增，"
        "若发现重复或缺失项则按上下文修正\n"
        "8. 保留列举项的换行结构：题干中 I/II/III/IV、①②③、(1)(2)(3) 等"
        "枚举序列各条目之间必须保留换行符，每个枚举项独立一行，不要合并为连续文本\n"
        "9. 保护代码块：原文中的 ``` 代码围栏是结构标记，必须原样保留；"
        "围栏内的所有缩进、换行、空格不得修改，代码语句不要合并为单行；"
        "不要在围栏外新增围栏（代码块边界由预处理管线决定）；"
        "围栏内 C/Java 代码中 printf(\"\\n\") 等字符串字面量中的 \\n 是转义序列，"
        "不应被解释为文本换行符，保留原始写法\n"
        "数学公式输出规则：所有数学内容用 LaTeX（行内 $...$，块级 $$...$$），"
        "禁止使用 Unicode 数学符号。\n"
        "\n"
        "【重要 — 硬性约束】\n"
        "10. 你只能修复 OCR 造成的明显错字、断行、选项错位和格式问题。\n"
        "    不得重新解题。\n"
        "    不得根据题意推理答案。\n"
        "    不得擅自修改答案字段。\n"
        "    如果原文没有明确答案，请保持答案为空，并设置 \"answer_uncertain\": true。\n"
        "    不得改写数学公式、LaTeX、积分、极限、矩阵、分式、上下标。\n"
        "    对于不确定的公式，不要猜测，保留原文。\n"
        "    不得改写 C 语言/伪代码/SQL 的逻辑。\n"
        "    不得修改代码中的关键符号：->、==、!=、<=、>=、&&、||、*、&、[]、{}、()、++、--。\n"
        "    如果代码或公式无法确认，请保留原文，并添加风险标记。\n"
        "11. 如果 AI 输出中某些字段（尤其是公式或代码）存在不确定性，"
        "请在输出 JSON 中的 risk_flags 数组中添加对应标记：\n"
        "    \"formula_uncertain\" — 数学公式部分无法确认\n"
        "    \"code_uncertain\" — 代码部分无法确认\n"
        "    \"answer_uncertain\" — 答案不确定\n"
        "12. 禁止在 answer 字段中填入 AI 推理产生的答案。\n"
        "    仅当原文中明确标注了答案时才填入。\n"
        "    如果没有明确答案，answer 输出空字符串。\n"
        "13. 禁止修改 options 字段（A/B/C/D 选项）。\n"
        "    选项结构在预处理管线中已被冻结，你没有权限修改。\n"
        "    即使你认为选项文本有错或缺失，也必须原样保留。\n"
        "    仅允许修改：stem（题干）、analysis（解析）、formatting（格式）。\n"
        "请严格使用 JSON 格式输出：\n"
        '{"question_type": "single_choice", '
        '"stem": "题干（数学公式用 $...$）", '
        '"options": {"A": "选项A", "B": "选项B"}, '
        '"answer": "A", '
        '"analysis": "解析", '
        '"confidence": 0.85, '
        '"risk_flags": [], '
        '"repair_actions": ["stem_cleaned", "options_structured"]}\n'
        "repair_actions 可选值：stem_cleaned / options_structured / answer_normalized / "
        "type_detected / analysis_extracted"
    ),
    "text_structure": (
        "你是题目文本结构化助手。输入是从用户复制粘贴的题目原文，"
        "你的唯一职责是识别原文中的结构区域（题干 / 选项 / 答案 / 解析），"
        "并将其整理为标准 JSON。\n\n"
        "严格禁止：\n"
        "- 禁止生成、推测或补全任何答案\n"
        "- 禁止生成、补写或扩展任何解析\n"
        "- 禁止补全缺失的选项\n"
        "- 禁止根据知识判断题目正确性\n"
        "- 禁止修改题目语义\n"
        "- 禁止创造、改写、翻译原文中不存在的任何内容\n"
        "- 禁止合并多道题，禁止拆分单道题\n\n"
        "允许的操作：\n"
        "- 修复换行错误：把被错误断开的句子拼接为完整句\n"
        "- 修复选项拆分错误：让 A/B/C/D 选项各自独立\n"
        "- 识别多空题结构：标记题干中的多个空 ① ② / ( ) / ___ 与对应答案区域\n"
        "- 识别非标准答案标签（如 Ans:、Key:、参考答案、答：）并标准化为 answer 字段\n"
        "- 去除题号前缀、Markdown 标记、HTML 标签、空白污染\n\n"
        "缺失字段处理：\n"
        "- 找不到答案 → answer 输出 null\n"
        "- 找不到解析 → analysis 输出 null\n"
        "- 找不到选项 → options 输出空数组 []，绝不补全\n"
        "- 任何字段不确定 → 输出 null，绝不编造\n\n"
        "题型识别（question_type）取值：\n"
        "single_choice / multiple_choice / true_false / fill_blank / "
        "multi_blank_choice / subjective\n"
        "无法判断时输出 null。\n\n"
        "数学公式：保持原文 LaTeX/Unicode 形式，不要主动转换或重写。\n\n"
        "输出要求：必须严格 JSON，不允许任何自由文本、Markdown 代码块包裹或解释。\n"
        "JSON 结构：\n"
        "{\n"
        '  "stem": "题干原文（可修复换行）",\n'
        '  "question_type": "single_choice | multiple_choice | true_false | '
        'fill_blank | multi_blank_choice | subjective | null",\n'
        '  "options": [{"key": "A", "text": "选项A原文"}, ...],\n'
        '  "answer": "原文答案 | null",\n'
        '  "analysis": "原文解析 | null"\n'
        "}\n"
        "options 中 key 必须是 A/B/C/D 等大写字母；找不到选项时返回空数组。"
    ),
    "ocr_correction": (
        "你是 OCR 文本纠错助手。输入是 OCR 识别的考研题目文本片段。\n"
        "你的任务是修复 OCR 识别错误，保持原文含义不变。\n\n"
        "修复规则：\n"
        "1. 修复换行错乱：被错误断开的句子重新拼接为完整句\n"
        "2. 修复选项错位：确保 A/B/C/D 选项各占独立行\n"
        "3. 修复题号缺失：如果上下文明确有题号但缺失，补上（如 1. 2. 等）\n"
        "4. 修复 OCR 错字：选项标号中 8→B、6→G、0→D、l→1、O→0 等\n"
        "5. 修复标点错乱：中英文标点混用、缺失等\n"
        "6. 修复计算机专业术语 OCR 错误：\n"
        "   方武→方式、进稈→进程、协汉→协议、线稈→线程、死铐→死锁\n"
        "   数据枸构→数据结构、操作糸统→操作系统、编释器→编译器\n"
        "   堆找→堆栈、链哀→链表、二叉村→二叉树、递归→递归\n"
        "   冲突检侧→冲突检测、调度箅法→调度算法、虚拟内仔→虚拟内存\n"
        "   网绔→网络、路甶器→路由器、传输曾→传输层、TCP/IP协汉→TCP/IP协议\n"
        "   中斷→中断、缓冲→缓冲、寄仔器→寄存器、磁盐→磁盘\n"
        "7. 修复数学术语 OCR 错误：\n"
        "   导敖→导数、积兮→积分、极眼→极限、矩陣→矩阵\n"
        "   连统→连续、可异→可导、收敛→收敛、级敖→级数\n"
        "   微兮→微分、偏异数→偏导数、线性伐数→线性代数\n"
        "   行列或→行列式、特征俌→特征值、向里→向量\n"
        "   函敖→函数、方稈→方程、不等或→不等式、概率→概率\n"
        "8. 保持专业缩写完整：TCP/UDP/HTTP/DNS/ARP/ICMP/IP/OS 等不要拆分或修改\n"
        "9. 保护代码块：原文中的 ``` 代码围栏是结构标记，必须原样保留；"
        "围栏内的所有缩进、换行、空格不得修改；"
        "不要在围栏外新增围栏（代码块边界由预处理管线决定）；"
        "围栏内 printf(\"\\n\") 等字符串字面量的 \\n 是转义序列，不要解释为换行\n\n"
        "禁止规则：\n"
        "- 禁止添加原文中不存在的内容（不要补充答案、解析等）\n"
        "- 禁止修改题目实质含义\n"
        "- 禁止重新排版或添加格式标记\n"
        "- 如果文本质量已经很好，原样返回即可\n"
        "- 禁止删除原文中的任何行：保留题干、选项、答案行等所有内容，只修复字符错误\n"
        "- 特别重要：如果原文包含题号（如\"06.\"或\"1.\"）和题干文本，必须在输出中完整保留\n"
        "- 不允许只输出选项而不保留题干\n"
        "- 禁止删除或修改 ``` 代码围栏及其内部内容\n\n"
        "输出格式：直接返回纠错后的完整纯文本，不要包含任何 JSON、代码块或其他标记。"
    ),
    "roman_repair_decision": (
        "你是考研题库中的罗马数字序列修复决策助手。\n"
        "你的任务不是自由生成修复文本，而是从候选方案中选择最合理的修复动作。\n\n"
        "规则：\n"
        "1. 仅从提供的候选方案(candidates)中选择，禁止自行创造新方案\n"
        "2. 若所有候选方案都不合理，选择 keep_as_is（候选列表中最后一项）\n"
        "3. 基于上下文语义判断：罗马数字是序列枚举还是独立引用\n"
        "4. 考虑选项间的对应关系：若选项 A 引用了罗马数字序列，其他选项可能也有类似结构\n"
        "5. 对于 OCR 数字混淆(1 vs I)：判断上下文是阿拉伯数字语境还是罗马数字语境\n"
        "6. 递增序列是最常见模式：I→II→III→IV→V 比跳号更可能\n\n"
        "输出严格 JSON 格式，不要包含任何解释或 Markdown 代码块：\n"
        '{"decisions": [{"anomaly_index": 0, "chosen_candidate_index": 0, '
        '"confidence": 0.9, "rationale": "选择理由（一句话）"}]}'
    ),
    "complete_question": (
        "你是考研题目补全助手。根据已有的题干和上下文，补全缺失字段。"
        "你的输出仅是辅助提示，必须经过人工审核后才能采用。"
        "如果你不确定，请将对应字段留空字符串而不要编造。\n"
        "数学公式输出规则：所有数学内容用 LaTeX（行内 $...$，块级 $$...$$），"
        "禁止使用 Unicode 数学符号。\n"
        "请用中文回答，严格 JSON 格式输出。\n\n"
        "学科（subject_id）说明：\n"
        "你必须从给定的科目列表中选择一个 subject_id（整数），不要输出自由文本 subject。\n"
        "如果无法判断科目，将 subject_id 设为 null。\n\n"
        "有效题型（question_type）值：\n"
        "- single_choice（单选题）\n"
        "- multiple_choice（多选题）\n"
        "- true_false（判断题）\n"
        "- fill_blank（填空题）\n"
        "- multi_blank_choice（多空选择题）\n"
        "- subjective（主观题/简答题）\n\n"
        "推断规则：\n"
        "- 优先根据题干内容推断最具体的子学科，无法确定时使用大类\n"
        "- 数学题干出现极限/导数/积分/微分 → math2-calculus\n"
        "- 数学题干出现矩阵/向量/特征值/行列式/线性 → math2-linalg\n"
        "- 408 题干出现链表/树/图/排序/查找/算法 → exam408-ds\n"
        "- 408 题干出现进程/线程/死锁/内存/文件系统 → exam408-os\n"
        "- 408 题干出现 CPU/指令/流水线/Cache/总线 → exam408-co\n"
        "- 408 题干出现 TCP/IP/HTTP/DNS/路由/子网 → exam408-cn\n\n"
        "输出 JSON 格式：\n"
        '{"subject_id": 3, '
        '"question_type": "single_choice", '
        '"answer": "A", '
        '"analysis": "解析（若不确定可留空）", '
        '"knowledge_points": ["知识点1"], '
        '"difficulty": 3, '
        '"answer_uncertain": false, '
        '"confidence": 0.6, '
        '"reason": "推理依据"}'
    ),
    "code_structure_reconstruct": (
        "你是代码结构修复引擎。你的唯一任务是将 OCR 识别后的代码恢复为"
        "具有正确缩进、换行和基本结构完整性的可读代码。\n"
        "你只能恢复结构，不能理解题目含义，不能改写逻辑。\n\n"
        "【输入】\n"
        "包含代码的题目题干文本。\n\n"
        "【输出要求】\n"
        "输出严格 JSON 格式：\n"
        '{"stem": "修复后的完整题干（代码部分经过结构修复）",\n'
        '"code_fixed": true/false,\n'
        '"fix_actions": ["修复动作1", "修复动作2"],\n'
        '"confidence": 0.0-1.0}\n\n'
        "【必须修复的结构问题】\n"
        "1. {} 花括号闭合：补全缺失的闭合花括号\n"
        "2. 缩进层级：基于 {} 和控制流语句恢复 4 空格缩进\n"
        "3. 断行修复：将 OCR 导致断裂的语句合并为完整语句\n"
        "   - if/for/while 前后需要合理换行\n"
        "   - 语句后的 { 保持在同一行或换行均可\n"
        "4. OCR 符号错误修复（仅限代码内的语法层符号）：\n"
        "   - `= =` → `==`\n"
        "   - `! =` → `!=`\n"
        "   - `- >` → `->`\n"
        "   - `+ +` → `++`\n"
        "   - `< =` → `<=`\n"
        "   - `> =` → `>=`\n"
        "5. 代码区域识别：题干中的非代码文本（题目描述、选项等）保留原样\n\n"
        "【严格禁止】\n"
        "- 不得修改代码逻辑\n"
        "- 不得改变量名\n"
        "- 不得补充不存在的语句\n"
        "- 不得改变代码的语义含义\n"
        "- 不得修改选项（A. B. C. D. 部分）\n"
        "- 不得修改答案\n"
        "- 不得删除任何原始代码行\n"
        "- 只能修复结构，不能改变内容"
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
                "请给出该题的解题技巧，包括解题思路、核心考点和快速方法。"
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


def build_batch_repair_prompt(candidates: list[tuple[int, dict, str]]) -> list:
    """构建批量题目修复 prompt。

    Args:
        candidates: [(index, question_dict, raw_text), ...]

    Returns:
        messages list，单次 LLM 调用修复多题。
    """
    parts: list[str] = []
    for idx, (i, q, raw_text) in enumerate(candidates, 1):
        existing = (
            f"【规则解析题干】{q.get('stem', '')}\n"
            f"【规则解析选项】{q.get('options', [])}\n"
            f"【规则解析答案】{q.get('answer', '')}\n"
            f"【规则解析题型】{q.get('question_type', '')}\n"
            f"【规则解析解析】{q.get('analysis', '')}\n"
            f"【已知错误】{q.get('errors', [])}\n"
        )
        parts.append(
            f"【题目{idx}】\n"
            f"【原始文本】\n{raw_text}\n\n"
            f"{existing}"
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPTS["question_repair"]},
        {
            "role": "user",
            "content": (
                "\n---\n".join(parts)
                + f"\n请修复以上 {len(candidates)} 道题目，按顺序输出 JSON 数组：\n"
                '[{"question_type": "...", "stem": "...", ...}, '
                '{"question_type": "...", "stem": "...", ...}]'
            ),
        },
    ]


def build_batch_complete_question(qi: dict, target_fields: list[str], strategy: str, system_prompt: str | None = None, subject_list: list[dict] | None = None) -> list:
    """对一条 question_imports 记录批量补全指定字段。

    strategy: fill_empty | force_overwrite
    target_fields: 需补全的字段列表
    system_prompt: 来自 DB admin_ai_configs 的自定义 prompt，为 None 时使用默认值。
    subject_list: 可用科目列表，注入到 user message 供 AI 选择 subject_id。
    """
    stem = (qi.get("parsed_content") or {}).get("text") or qi.get("raw_text") or ""
    options = qi.get("parsed_options") or {}
    answer = qi.get("parsed_answer") or ""
    analysis = qi.get("parsed_analysis") or ""
    subject = qi.get("subject") or ""
    question_type = qi.get("question_type") or ""

    field_descriptions = {
        "answer": "题目答案",
        "analysis": "题目解析",
        "knowledge_points": "知识点列表",
        "difficulty": "难度等级(1-5)",
        "subject": "学科分类",
        "question_type": "题型",
        "stem": "题干文本（修复OCR错误/补全缺失内容）",
        "options": "选项（规范格式/补全缺失选项）",
        "tips": "解题技巧",
        "tags": "题目标签",
    }
    field_names = ", ".join(field_descriptions.get(f, f) for f in target_fields)
    instruction = (
        "请仅补全以下字段中内容为空的部分，已有内容保持不变。"
        if strategy == "fill_empty"
        else "请重新生成以下字段的内容，覆盖原有值。"
    )
    subject_list_text = ""
    if subject_list:
        subject_list_text = "\n【可用科目列表】" + json.dumps(subject_list, ensure_ascii=False) + "\n"
    return [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPTS["complete_question"]},
        {
            "role": "user",
            "content": (
                f"{subject_list_text}"
                f"【已有题干】{stem}\n"
                f"【已有选项】{options}\n"
                f"【已有答案】{answer}\n"
                f"【已有解析】{analysis}\n"
                f"【已有学科】{subject}\n"
                f"【已有题型】{question_type}\n"
                f"【需补全字段】{field_names}\n"
                f"【策略】{instruction}\n"
                "输出 JSON 包含上述所有需补全字段。若答案不确定，"
                "请将 answer_uncertain 设为 true。"
            ),
        },
    ]


def build_complete_question(qi: dict, missing_fields: list[str], system_prompt: str | None = None, subject_list: list[dict] | None = None) -> list:
    stem = (qi.get("parsed_content") or {}).get("text") or qi.get("raw_text") or ""
    options = qi.get("parsed_options") or {}
    answer = qi.get("parsed_answer") or ""
    analysis = qi.get("parsed_analysis") or ""
    subject = qi.get("subject") or ""
    subject_list_text = ""
    if subject_list:
        subject_list_text = "\n【可用科目列表】" + json.dumps(subject_list, ensure_ascii=False) + "\n"
    return [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPTS["complete_question"]},
        {
            "role": "user",
            "content": (
                f"{subject_list_text}"
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


def build_text_structure(block_text: str, rule_hint: dict | None = None) -> list:
    """构建文本结构化 prompt — 仅做格式整理，不补全。"""
    hint_lines = ""
    if rule_hint:
        hint_lines = (
            "\n【规则解析参考结果（仅供识别区域，不要据此补全任何字段）】\n"
            f"- 已识别题干长度: {len(rule_hint.get('stem') or '')}\n"
            f"- 已识别选项数: {len(rule_hint.get('options') or [])}\n"
            f"- 已识别答案是否为空: {not rule_hint.get('answer')}\n"
            f"- 已识别解析是否为空: {not rule_hint.get('analysis')}\n"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["text_structure"]},
        {
            "role": "user",
            "content": (
                "请仅做格式结构化，不要生成、补全或修改任何内容。"
                "输出严格 JSON。\n"
                f"{hint_lines}"
                "【原文】\n"
                f"{block_text}"
            ),
        },
    ]


def build_ocr_correction(block_text: str, system_prompt: str | None = None) -> list:
    """构建 OCR 文本纠错 prompt。

    system_prompt: 来自 DB admin_ai_configs 的自定义 prompt，为 None 时使用默认值。
    """
    return [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPTS["ocr_correction"]},
        {
            "role": "user",
            "content": (
                "请纠错以下 OCR 识别文本：\n\n"
                f"{block_text}"
            ),
        },
    ]


def build_roman_decision_prompt(
    question: dict,
    anomalies: list[dict],
) -> list:
    """构建受约束的罗马数字修复决策 prompt。

    将结构化异常数据 + 候选修复方案呈现给 AI，
    AI 仅需从候选中选择最合理的方案，而非自由生成文本。

    Args:
        question: 题目 dict（包含 stem, options）
        anomalies: 结构化异常列表（来自 roman_schema.build_roman_anomaly）

    Returns:
        messages list
    """
    import json

    anomaly_blocks: list[str] = []
    for i, anom in enumerate(anomalies):
        block = (
            f"【异常 {i + 1}】\n"
            f"  位置: {anom.get('source', '')}\n"
            f"  发现序列: {', '.join(anom.get('found_tokens', []))}"
            f" (值: {anom.get('found_values', [])})\n"
            f"  异常类型: {anom.get('issue_type', '')}\n"
        )
        snippet = anom.get("text_snippet", "")
        if snippet:
            block += f"  文本上下文:\n    {snippet[:200]}\n"

        candidates = anom.get("candidates", [])
        if candidates:
            block += "  候选修复方案:\n"
            for j, cand in enumerate(candidates):
                cand_str = json.dumps(cand, ensure_ascii=False)
                block += f"    [{j}] {cand_str}\n"

        anomaly_blocks.append(block)

    stem_text = question.get("stem", "")
    if len(stem_text) > 500:
        stem_text = stem_text[:500] + "…"

    options_text = ""
    for opt in question.get("options", []):
        if isinstance(opt, dict):
            opt_text = opt.get("text", "")
            if len(opt_text) > 150:
                opt_text = opt_text[:150] + "…"
            options_text += f"{opt.get('key', '')}. {opt_text}\n"

    return [
        {"role": "system", "content": SYSTEM_PROMPTS["roman_repair_decision"]},
        {
            "role": "user",
            "content": (
                f"【题目题干】{stem_text}\n"
                f"【题目选项】\n{options_text}\n"
                + "\n---\n".join(anomaly_blocks)
                + "\n\n请对每个异常选择一个候选修复方案，输出 JSON。"
            ),
        },
    ]


def build_code_structure_reconstruct(stem: str) -> list:
    """构建代码结构重建 prompt。

    Args:
        stem: 待修复的题干文本（包含代码）。

    Returns:
        messages list。
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPTS["code_structure_reconstruct"]},
        {
            "role": "user",
            "content": (
                "请修复以下文本中的代码结构问题，输出标准 JSON：\n\n"
                f"{stem}"
            ),
        },
    ]
