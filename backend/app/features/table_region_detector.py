"""表格区域检测：从文本块中检测表格结构并转为 Markdown。

不做复杂表格 OCR 引擎，只做"表格风险检测 + Markdown 保真"的最小版本。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── 表头关键词 ──

_TABLE_HEADER_KEYWORDS = re.compile(
    r"进程|到达时间|服务时间|优先级|页号|块号|页框|"
    r"Cache|标记|有效位|修改位|访问位|"
    r"路由|下一跳|目标网络|掩码|"
    r"编码|哈夫曼|频率|权值|"
    r"学号|姓名|成绩|科目|分数|"
    r"年份|项目|数值|总计|合计|"
    r"输入|输出|状态|结果"
)

# ── 多列信号 ──

_MULTI_COLUMN_TOKEN_SEP = re.compile(r"[ \t]{2,}|  +")
_NUMBER_PATTERN = re.compile(r"^\d+(\.\d+)?$")


def detect_table_candidate(text: str) -> dict:
    """检测单段文本是否为表格候选。

    Returns:
        {"is_table": bool, "signals": list[str], "confidence": float,
         "markdown": str | None}
    """
    signals: list[str] = []
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return {"is_table": False, "signals": [], "confidence": 0.0, "markdown": None}

    # Signal 1: 表头关键词
    header_matches = _TABLE_HEADER_KEYWORDS.findall(text)
    if header_matches:
        signals.append(f"header_keywords={len(header_matches)}")

    # Signal 2: 多行中有相似列数（空格分隔的 token 数相近）
    token_counts: list[int] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        tokens = _MULTI_COLUMN_TOKEN_SEP.split(stripped)
        if len(tokens) >= 2:
            token_counts.append(len(tokens))

    if len(token_counts) >= 2:
        # 检查是否有稳定的列数（至少 2 行相同 token 数）
        from collections import Counter
        count_dist = Counter(token_counts)
        most_common_count, most_common_freq = count_dist.most_common(1)[0]
        if most_common_freq >= 2 and most_common_count >= 2:
            signals.append(f"multi_column({most_common_count} cols x {most_common_freq} rows)")
            # 如果 token 数稳定且 ≥3 行，置信度更高
            if most_common_freq >= 3 and most_common_count >= 3:
                signals.append("stable_table_structure")

    # Signal 3: 行内包含数字 token（表格常见）
    number_lines = 0
    for line in lines:
        tokens = line.strip().split()
        numbers = sum(1 for t in tokens if _NUMBER_PATTERN.match(t))
        if numbers >= 2:
            number_lines += 1
    if number_lines >= 2:
        signals.append(f"number_columns({number_lines} lines)")

    confidence = _compute_confidence(signals, len(lines), token_counts)
    is_table = len(signals) > 0

    markdown = _try_build_markdown(lines, token_counts) if is_table and confidence >= 0.3 else None

    return {
        "is_table": is_table,
        "signals": signals,
        "confidence": round(confidence, 2),
        "markdown": markdown,
    }


def _compute_confidence(signals: list[str], line_count: int, token_counts: list[int]) -> float:
    """根据信号强度计算置信度。"""
    score = 0.0

    if any("stable_table_structure" in s for s in signals):
        score += 0.4
    elif any(s.startswith("multi_column") for s in signals):
        score += 0.25

    if any(s.startswith("header_keywords") for s in signals):
        score += 0.2
    if any(s.startswith("number_columns") for s in signals):
        score += 0.15

    # 行数越多越不像表格（可能是列表）
    if line_count >= 2:
        score += 0.1
    if line_count > 10:
        score -= 0.1

    # 检查 token 数一致性
    if len(token_counts) >= 2:
        unique = len(set(token_counts))
        if unique == 1 and len(token_counts) >= 3:
            score += 0.15
        elif unique <= 2 and len(token_counts) >= 3:
            score += 0.1

    return max(0.0, min(1.0, score))


def _try_build_markdown(lines: list[str], token_counts: list[int]) -> str | None:
    """尝试将文本行转为 Markdown 表格。

    仅在列数明确、结构稳定时生成。对松散结构返回 None。
    """
    if not lines or not token_counts:
        return None

    # 找最常用的 token 数
    from collections import Counter
    count_dist = Counter(token_counts)
    target_count, target_freq = count_dist.most_common(1)[0]
    if target_freq < 2 or target_count < 2:
        return None

    # 过滤出符合 target_count 列的行
    table_lines: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        tokens = _MULTI_COLUMN_TOKEN_SEP.split(stripped)
        if len(tokens) == target_count:
            table_lines.append(tokens)

    if len(table_lines) < 2:
        return None

    # 构建 Markdown 表：首行为表头，第二行为分隔线
    header = table_lines[0]
    separator = ["---"] * target_count
    md_lines = ["| " + " | ".join(header) + " |"]
    md_lines.append("| " + " | ".join(separator) + " |")
    for row in table_lines[1:]:
        md_lines.append("| " + " | ".join(row) + " |")

    return "\n".join(md_lines)


def detect_tables_in_blocks(blocks: list[dict]) -> list[dict]:
    """在 OCR 文本块中检测表格区域。

    Args:
        blocks: pipeline 中的 normalized_blocks / 文本块列表

    Returns:
        [{"page": int, "bbox": list | None, "text": str,
          "markdown": str | None, "confidence": float,
          "requires_review": bool}, ...]
    """
    tables: list[dict] = []
    for block in blocks:
        text = str(block.get("normalized_text") or block.get("text") or "").strip()
        if not text or len(text) < 40:
            continue

        result = detect_table_candidate(text)
        if not result["is_table"]:
            continue

        tables.append({
            "page": block.get("page", 1),
            "bbox": block.get("bbox") or None,
            "text": text[:500],
            "markdown": result["markdown"],
            "confidence": result["confidence"],
            "requires_review": result["confidence"] < 0.5 or not result["markdown"],
        })

    return tables
