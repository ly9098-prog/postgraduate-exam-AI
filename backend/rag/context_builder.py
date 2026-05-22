"""
上下文构建器。
根据检索结果，只加载命中的文件，组装成面向 LLM 的结构化上下文。
严格遵守：最多 3-5 个文件，前后端分开，不加载全项目。
"""

import json
import os

from .chunker import chunk_module, summarize_module
from .retriever import smart_retrieve

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.json")


def _load_index() -> dict:
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_module_info(mod_id: str, side: str) -> dict | None:
    """根据模块 ID 获取模块信息"""
    index = _load_index()
    return index.get(side, {}).get(mod_id)


def build_context(query: str, max_preview_lines: int = 60) -> dict:
    """
    核心入口。
    1. 检索匹配模块
    2. 读取命中文件（只读需要的文件，不读全项目）
    3. 组装前后端分离的上下文
    4. 返回结构化结果

    返回:
    {
        "query": str,
        "match_summary": str,       # 命中摘要
        "frontend_context": str,    # 前端代码（WXML/JS/WXSS）
        "backend_context": str,     # 后端代码（Python）
        "token_estimate": int,      # 估算 token 数
    }
    """
    result = smart_retrieve(query)
    backend_modules = result["backend"]
    frontend_modules = result["frontend"]

    # 收集所有需要读取的文件（去重）
    seen_files = set()
    backend_chunks = []
    frontend_chunks = []
    matched_summaries = []

    for mod in backend_modules:
        info = _get_module_info(mod["id"], "backend")
        if not info:
            continue
        matched_summaries.append(f"[backend/{mod['id']}] {info['description']} (score={mod['score']})")
        for f in info["files"]:
            if f not in seen_files:
                seen_files.add(f)
                chunks = chunk_module(mod["id"], [f])
                backend_chunks.extend(chunks)

    for mod in frontend_modules:
        info = _get_module_info(mod["id"], "frontend")
        if not info:
            continue
        matched_summaries.append(f"[frontend/{mod['id']}] {info['description']} (score={mod['score']})")
        for f in info["files"]:
            if f not in seen_files:
                seen_files.add(f)
                chunks = chunk_module(mod["id"], [f])
                frontend_chunks.extend(chunks)

    # --- 构建上下文文本 ---

    # 前端上下文
    frontend_parts = []
    total_lines = 0
    for chunk in frontend_chunks:
        lines = chunk["content"].split("\n")
        take = min(max_preview_lines - total_lines, len(lines))
        if take <= 0:
            break
        frontend_parts.append(f"### {chunk['file']} ({chunk['type']}: {chunk['name']})")
        frontend_parts.append("```" + _ext(chunk["file"]))
        frontend_parts.append("\n".join(lines[:take]))
        frontend_parts.append("```")
        total_lines += take

    # 后端上下文
    backend_parts = []
    total_lines = 0
    for chunk in backend_chunks:
        lines = chunk["content"].split("\n")
        take = min(max_preview_lines - total_lines, len(lines))
        if take <= 0:
            break
        backend_parts.append(f"### {chunk['file']} ({chunk['type']}: {chunk['name']})")
        backend_parts.append("```python")
        backend_parts.append("\n".join(lines[:take]))
        backend_parts.append("```")
        total_lines += take

    frontend_text = "\n\n".join(frontend_parts) if frontend_parts else "(无匹配前端模块)"
    backend_text = "\n\n".join(backend_parts) if backend_parts else "(无匹配后端模块)"

    # 估算 token（中文 1.5 token/字，英文 0.3 token/字，近似）
    raw = frontend_text + backend_text
    token_estimate = int(len(raw) * 0.5)

    return {
        "query": query,
        "match_summary": "\n".join(matched_summaries) if matched_summaries else "无匹配模块",
        "frontend_context": frontend_text,
        "backend_context": backend_text,
        "token_estimate": token_estimate,
        "is_empty": len(matched_summaries) == 0,
    }


def _ext(filename: str) -> str:
    """根据文件后缀返回代码块语言标识"""
    map_ext = {
        ".py": "python",
        ".js": "javascript",
        ".wxml": "html",
        ".wxss": "css",
        ".json": "json",
    }
    _, ext = os.path.splitext(filename)
    return map_ext.get(ext, "text")


def build_context_minimal(query: str) -> str:
    """
    极简模式：只返回文本上下文，适合直接拼到 AI prompt 前部。
    输出格式：

    [FRONTEND CONTEXT]
    - pages/practice/practice.js
    - components/question-card

    [BACKEND CONTEXT]
    - sm2.py
    - wrong_questions.py
    """
    result = build_context(query, max_preview_lines=30)
    parts = []

    if result["frontend_context"] != "(无匹配前端模块)":
        parts.append("[FRONTEND CONTEXT]")
        parts.append(result["frontend_context"])

    if result["backend_context"] != "(无匹配后端模块)":
        parts.append("[BACKEND CONTEXT]")
        parts.append(result["backend_context"])

    return "\n\n".join(parts)
