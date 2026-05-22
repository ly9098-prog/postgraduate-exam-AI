"""
轻量代码分块器。
按模块读取源文件，提取函数/类/页面的代码片段。
前后端统一处理，不加载整个项目。
"""

import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINIPROGRAM_DIR = os.path.join(os.path.dirname(BASE_DIR), "miniprogram")


def _read_file(path: str) -> str | None:
    """安全读取文件，不存在返回 None"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _chunk_python(source: str, file_rel: str) -> list[dict]:
    """Python 文件按函数/类分块"""
    chunks = []
    lines = source.split("\n")

    current_type = "code"
    current_start = 0
    current_name = file_rel

    for i, line in enumerate(lines):
        class_match = re.match(r"^class\s+(\w+)", line)
        def_match = re.match(r"^async\s+def\s+(\w+)|^def\s+(\w+)", line)
        if class_match:
            if i > current_start:
                chunks.append({
                    "file": file_rel,
                    "type": current_type,
                    "name": current_name,
                    "lines": (current_start + 1, i),
                    "content": "\n".join(lines[current_start:i]),
                })
            current_type = "class"
            current_name = class_match.group(1)
            current_start = i
        elif def_match:
            name = def_match.group(1) or def_match.group(2)
            if i > current_start:
                chunks.append({
                    "file": file_rel,
                    "type": current_type,
                    "name": current_name,
                    "lines": (current_start + 1, i),
                    "content": "\n".join(lines[current_start:i]),
                })
            current_type = "function"
            current_name = name
            current_start = i

    # 最后一块
    chunks.append({
        "file": file_rel,
        "type": current_type,
        "name": current_name,
        "lines": (current_start + 1, len(lines)),
        "content": "\n".join(lines[current_start:]),
    })

    return chunks


def _chunk_wxml(source: str, file_rel: str) -> list[dict]:
    """WXML 模板按 view/block 分块"""
    return [{"file": file_rel, "type": "template", "name": file_rel, "lines": (1, len(source.split("\n"))), "content": source}]


def _chunk_wxss(source: str, file_rel: str) -> list[dict]:
    """WXSS 样式作为一个整体"""
    return [{"file": file_rel, "type": "style", "name": file_rel, "lines": (1, len(source.split("\n"))), "content": source}]


def _chunk_js(source: str, file_rel: str) -> list[dict]:
    """JS 文件按 Page/Component 定义分块"""
    chunks = []
    lines = source.split("\n")

    for i, line in enumerate(lines):
        page_match = re.match(r"(Page|Component|App)\(\{", line)
        if page_match:
            name = page_match.group(1)
            chunks.append({
                "file": file_rel,
                "type": name.lower(),
                "name": name,
                "lines": (i + 1, len(lines)),
                "content": "\n".join(lines[i:]),
            })
            break

    if not chunks:
        # 没有 Page() 定义，可能是工具模块，整个文件作为一个 chunk
        funcs = re.findall(r"^(?:async\s+)?function\s+(\w+)|^const\s+(\w+)\s*=", source, re.MULTILINE)
        for func_name in [f[0] or f[1] for f in funcs]:
            if func_name:
                chunks.append({
                    "file": file_rel,
                    "type": "function",
                    "name": func_name,
                    "lines": (1, len(lines)),
                    "content": source[:500],
                })

        if not chunks:
            chunks.append({
                "file": file_rel,
                "type": "module",
                "name": file_rel,
                "lines": (1, len(lines)),
                "content": source,
            })

    return chunks


def chunk_module(module_id: str, files: list[str]) -> list[dict]:
    """根据模块 ID 和文件列表，读取并分块"""
    all_chunks = []

    for file_rel in files:
        # 尝试 backend 路径
        path = os.path.join(BASE_DIR, file_rel)
        # 尝试 frontend 路径
        if not os.path.exists(path):
            path = os.path.join(MINIPROGRAM_DIR, file_rel)
        if not os.path.exists(path):
            continue

        source = _read_file(path)
        if not source:
            continue

        ext = os.path.splitext(file_rel)[1]
        if ext == ".py":
            chunks = _chunk_python(source, file_rel)
        elif ext == ".js":
            chunks = _chunk_js(source, file_rel)
        elif ext == ".wxml":
            chunks = _chunk_wxml(source, file_rel)
        elif ext == ".wxss":
            chunks = _chunk_wxss(source, file_rel)
        else:
            chunks = [{"file": file_rel, "type": "file", "name": file_rel, "lines": (1, len(source.split("\n"))), "content": source}]

        for c in chunks:
            c["module"] = module_id

        all_chunks.extend(chunks)

    return all_chunks


def summarize_module(module_id: str, files: list[str], max_lines: int = 80) -> str:
    """获取模块的概要（前 N 行），适合快速预览"""
    parts = []
    remaining = max_lines

    for file_rel in files:
        if remaining <= 0:
            break

        path = os.path.join(BASE_DIR, file_rel)
        if not os.path.exists(path):
            path = os.path.join(MINIPROGRAM_DIR, file_rel)
        if not os.path.exists(path):
            continue

        source = _read_file(path)
        if not source:
            continue

        lines = source.split("\n")
        take = min(remaining, len(lines), 30)  # 每文件最多 30 行
        preview = "\n".join(lines[:take])
        parts.append(f"# {file_rel}\n{preview}")
        remaining -= take

    return "\n\n".join(parts)
