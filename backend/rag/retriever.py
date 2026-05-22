"""
检索器：根据用户 query 匹配最相关的模块（前后端统一）。
返回 top-1~3 个模块，命中规则基于关键词匹配 + 权重得分。

禁止加载全部文件，只返回命中的模块索引信息。
"""

import json
import os
import re

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.json")


def _load_index() -> dict:
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _tokenize(text: str) -> list[str]:
    """分词：英文小写 + 中文单字 + 数字"""
    text = text.lower()
    # 提取英文词+数字组合（如 sm2, api, auth）
    words = re.findall(r"[a-z][a-z0-9]*", text)
    # 提取中文
    chinese_chars = re.findall(r"[一-鿿]+", text)
    return words + chinese_chars


def _keyword_match_score(query_tokens: list[str], keywords: list[str]) -> float:
    """
    计算 query 与关键词列表的匹配得分。
    支持英文子串匹配 + 中文精确匹配。
    """
    score = 0.0
    query_lower = " ".join(query_tokens).lower()

    for kw in keywords:
        kw_lower = kw.lower()

        # 精确词组匹配（权重最高）
        if kw_lower in query_lower:
            score += 3.0
            continue

        # 英文单词：支持子串匹配
        for qt in query_tokens:
            if re.match(r"^[a-z0-9]+$", qt) and len(qt) >= 2:
                if kw_lower.startswith(qt) or qt.startswith(kw_lower):
                    score += 1.5
                    break

        # 中文关键词：双向包含
        for qt in query_tokens:
            if re.match(r"^[一-鿿]+$", qt):
                if kw_lower in qt or qt in kw_lower:
                    score += 2.0
                    break

    return score


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """
    主检索入口。
    返回排序后的模块列表，每个模块包含 id、type、score、files、description。
    """
    if not query or not query.strip():
        return []

    index = _load_index()
    query_tokens = _tokenize(query)

    scored = []

    for side in ["backend", "frontend"]:
        for mod_id, mod_info in index.get(side, {}).items():
            score = _keyword_match_score(query_tokens, mod_info["keywords"])
            if score > 0:
                scored.append({
                    "id": mod_id,
                    "type": side,
                    "score": round(score, 1),
                    "files": mod_info["files"],
                    "description": mod_info["description"],
                })

    # 按得分降序排序
    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:top_k]


def smart_retrieve(query: str) -> dict:
    """
    智能检索：自动识别查询意图，返回前后端分离的结果。
    返回 { backend: [...], frontend: [...], explanation: "..." }
    """
    results = retrieve(query, top_k=6)

    backend = [r for r in results if r["type"] == "backend"]
    frontend = [r for r in results if r["type"] == "frontend"]

    # 各取 top-2（最多总共 4 个模块，符合 3-5 文件限制）
    return {
        "query": query,
        "backend": backend[:2],
        "frontend": frontend[:2],
    }
