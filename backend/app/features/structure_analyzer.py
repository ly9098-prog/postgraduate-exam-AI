"""文档结构分析器 — 纯规则实现。

分析文档的宏观结构：识别题目/答案/解析区域，判断题目-答案组织模式。
不做逐题切分、不做答案匹配、不调用 AI。
"""

import re


# 题号模式
_QUESTION_PATTERN_LIST = [
    r"^\s*\d+\s*[.、)）]",          # 1. / 1、/ 1) / 1）
    r"^\s*\(\d+\)",                  # (1)
    r"^\s*【\d+】",                  # 【1】
    r"^第\s*\d+\s*题",              # 第1题
    r"^第\s*[一二三四五六七八九十]+\s*题",  # 第一题
]

QUESTION_PATTERNS = [re.compile(pat) for pat in _QUESTION_PATTERN_LIST]

# 答案区域关键词
ANSWER_KEYWORDS = [
    "答案", "参考答案", "正确答案", "标准答案",
    "answer", "Answer", "ANSWER",
    "KEY", "Key",
]

# 解析区域关键词
ANALYSIS_KEYWORDS = [
    "解析", "解答", "讲解", "分析", "详解",
    "explanation", "Explanation",
    "【解析】", "【解答】", "【分析】",
]


def _count_patterns(text: str, patterns: list[re.Pattern]) -> int:
    """统计文本中匹配到的模式总次数。"""
    count = 0
    for line in text.split("\n"):
        for pat in patterns:
            if pat.search(line):
                count += 1
                break
    return count


def _count_keywords(text: str, keywords: list[str]) -> int:
    """统计文本中关键词出现的次数。"""
    count = 0
    for kw in keywords:
        count += text.count(kw)
    return count


def _block_type(text: str) -> str:
    """判断单个 block 的类型。

    Returns:
        "question" — 仅有题号模式，无答案/解析关键词
        "answer"   — 有答案关键词（可同时有题号模式）
        "explanation" — 有解析关键词（可同时有其他模式）
        "mixed"    — 同时有题号和答案/解析
        "none"     — 无匹配
    """
    q_count = _count_patterns(text, QUESTION_PATTERNS)
    a_count = _count_keywords(text, ANSWER_KEYWORDS)
    e_count = _count_keywords(text, ANALYSIS_KEYWORDS)

    has_answer_like = a_count > 0 or e_count > 0

    if q_count > 0 and has_answer_like:
        return "mixed"
    if has_answer_like and q_count == 0:
        return "answer" if a_count > 0 else "explanation"
    if q_count > 0:
        return "question"
    return "none"


def analyze_structure(
    normalized_blocks: list[dict],
    file_metadata: dict | None = None,
) -> dict:
    """分析文档结构，返回结构分析结果。"""
    total_blocks = len(normalized_blocks)

    if total_blocks == 0:
        return {
            "mode": "UNKNOWN",
            "question_pages": [],
            "answer_pages": [],
            "explanation_pages": [],
            "confidence": 0.0,
            "details": {
                "total_blocks": 0,
                "matched_patterns": {
                    "question_header": 0,
                    "answer_keyword": 0,
                    "analysis_keyword": 0,
                },
            },
        }

    raw_types: list[tuple[int, str, bool, bool, bool]] = []
    total_q_matches = 0
    total_a_matches = 0
    total_e_matches = 0

    for block in normalized_blocks:
        text = block.get("normalized_text", "")
        block_idx = block.get("block_index", 0)

        q_count = _count_patterns(text, QUESTION_PATTERNS)
        a_count = _count_keywords(text, ANSWER_KEYWORDS)
        e_count = _count_keywords(text, ANALYSIS_KEYWORDS)

        total_q_matches += q_count
        total_a_matches += a_count
        total_e_matches += e_count

        bt = _block_type(text)
        raw_types.append((
            block_idx, bt, q_count > 0, a_count > 0, e_count > 0,
        ))

    # 上下文感知：答案/解析区域之后的"题号"更可能是答案列表编号
    first_answer_like = None
    for idx, bt, _, _, _ in raw_types:
        if bt in ("answer", "mixed"):
            first_answer_like = idx
            break

    block_types: list[tuple[int, str]] = []
    for idx, bt, has_q, has_a, has_e in raw_types:
        if first_answer_like is not None and idx > first_answer_like and bt == "question":
            # 答案区域之后的题号 → 降级为混合块
            bt = "mixed"
        block_types.append((idx, bt))

    # 收集各类型 block 索引
    question_blocks = [idx for idx, bt in block_types if bt in ("question", "mixed")]
    pure_question_blocks = [idx for idx, bt in block_types if bt == "question"]
    a_pages = sorted(set(
        idx for idx, bt in block_types if bt in ("answer", "mixed")
    ))
    e_pages = sorted(set(
        idx for idx, bt, _, _, has_e in raw_types if has_e
    ))

    q_pages = sorted(set(question_blocks))

    mode, confidence = _detect_mode(
        block_types, pure_question_blocks, a_pages,
        total_q_matches, total_a_matches, total_blocks,
    )

    return {
        "mode": mode,
        "question_pages": q_pages,
        "answer_pages": a_pages,
        "explanation_pages": e_pages,
        "confidence": confidence,
        "details": {
            "total_blocks": total_blocks,
            "matched_patterns": {
                "question_header": total_q_matches,
                "answer_keyword": total_a_matches,
                "analysis_keyword": total_e_matches,
            },
        },
    }


def _detect_mode(
    block_types: list[tuple[int, str]],
    pure_question_blocks: list[int],
    a_pages: list[int],
    total_q_matches: int,
    total_a_matches: int,
    total_blocks: int,
) -> tuple[str, float]:
    """根据题目和答案区域的分布关系判断模式。"""
    if not a_pages:
        if total_q_matches > 0:
            return ("UNKNOWN", 0.4)
        return ("UNKNOWN", 0.0)

    first_answer = min(a_pages)

    # 所有含题号模式的 block（包括 mixed）
    all_q_blocks = [idx for idx, bt in block_types if bt in ("question", "mixed")]

    if not all_q_blocks:
        return ("UNKNOWN", 0.3)

    # SEPARATED: 纯题目块全部严格在答案块之前（答案列表编号不计为题目）
    if pure_question_blocks:
        last_pure_q = max(pure_question_blocks)
        if last_pure_q < first_answer:
            gap = first_answer - last_pure_q
            conf = min(0.95, 0.6 + gap / max(total_blocks, 1) * 0.2
                       + min(total_q_matches, 10) * 0.02)
            return ("SEPARATED", round(conf, 2))

    q_before_answer = [q for q in all_q_blocks if q < first_answer]
    q_at_or_after_answer = [q for q in all_q_blocks if q >= first_answer]

    # 无题号在答案区之前 → 所有题号和答案混合在一起（INLINE）
    if not q_before_answer:
        if total_q_matches >= 1 and total_a_matches >= 1:
            conf = min(0.9, 0.45 + total_q_matches * 0.05)
            return ("INLINE", round(conf, 2))
        return ("UNKNOWN", 0.3)

    # INLINE: 题号出现在答案块中或题目答案交替
    if q_at_or_after_answer:
        answer_blocks = [idx for idx, bt in block_types if bt in ("answer", "mixed")]
        mixed_blocks = [idx for idx, bt in block_types if bt == "mixed"]
        inline_ratio = len(mixed_blocks) / max(len(answer_blocks), 1)

        if inline_ratio >= 0.5:
            conf = min(0.95, 0.5 + inline_ratio * 0.3 + total_q_matches * 0.01)
            return ("INLINE", round(conf, 2))

        conf = min(0.9, 0.5 + min(total_q_matches, 20) * 0.02)
        return ("INLINE", round(conf, 2))

    if total_q_matches > 0 and total_a_matches > 0:
        return ("UNKNOWN", 0.35)

    return ("UNKNOWN", 0.1)
