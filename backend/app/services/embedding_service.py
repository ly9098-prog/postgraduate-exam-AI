"""Embedding 服务：文本构建、向量计算、批量处理。"""

import hashlib
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.embedding")


def build_question_embedding_text(question: Any) -> str:
    """将题目信息组装为 embedding 文本。

    包含: subject, question_type, difficulty, knowledge_points, stem, options, analysis。
    **不包含 answer**，防止 embedding 泄露答案信息。
    """
    parts: list[str] = []

    # 科目
    subject = getattr(question, "subject", "") or ""
    if subject:
        parts.append(f"科目：{subject}")

    # 题型
    q_type = getattr(question, "question_type", "") or ""
    if q_type:
        parts.append(f"题型：{q_type}")

    # 难度
    difficulty = getattr(question, "difficulty", None)
    if difficulty is not None:
        parts.append(f"难度：{difficulty}")

    # 知识点
    kps = getattr(question, "knowledge_points", None) or []
    if kps:
        parts.append(f"知识点：{'、'.join(str(k) for k in kps)}")

    # 题干
    content = getattr(question, "content", None) or {}
    if isinstance(content, dict):
        stem = content.get("text", "") or content.get("stem", "") or ""
    else:
        stem = str(content or "")
    if stem:
        parts.append(f"题干：{stem.strip()}")

    # 选项
    options = getattr(question, "options", None)
    if options and isinstance(options, dict):
        opt_lines = []
        for key in sorted(options.keys()):
            opt_lines.append(f"{key}. {options[key]}")
        if opt_lines:
            parts.append("选项：\n" + "\n".join(opt_lines))

    # 解析（可选）
    analysis = getattr(question, "analysis", None) or ""
    if analysis:
        parts.append(f"解析摘要：{str(analysis).strip()[:500]}")

    return "\n".join(parts)


def compute_content_hash(text: str) -> str:
    """SHA-256 哈希，返回 64 位 hex 字符串。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_embedding_configured() -> bool:
    """检查 embedding 所需配置是否完整。"""
    return bool(
        settings.EMBEDDING_API_KEY
        and settings.EMBEDDING_BASE_URL
        and settings.EMBEDDING_MODEL
    )


async def get_embedding(text: str) -> list[float] | None:
    """调用 OpenAI-compatible embeddings API 获取单条文本的 embedding 向量。

    返回 None 表示获取失败（配置缺失、请求异常、维度不匹配等）。
    """
    if not _is_embedding_configured():
        logger.warning("Embedding 配置不完整，跳过向量生成")
        return None

    if not text or not text.strip():
        return None

    url = f"{settings.EMBEDDING_BASE_URL.rstrip('/')}/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": text,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.EMBEDDING_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Embedding API 请求超时")
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("Embedding API 返回错误: status=%s", exc.response.status_code)
        return None
    except Exception:
        logger.warning("Embedding API 请求失败", exc_info=True)
        return None

    # 解析返回
    try:
        embedding = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Embedding API 返回格式异常")
        return None

    if not isinstance(embedding, list):
        logger.warning("Embedding 返回值不是 list")
        return None

    expected_dim = settings.EMBEDDING_DIM
    if len(embedding) != expected_dim:
        logger.warning(
            "Embedding 维度不匹配: expected=%d, got=%d", expected_dim, len(embedding)
        )
        return None

    return embedding


async def get_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """批量获取 embedding。按 EMBEDDING_BATCH_SIZE 分批调用 API。

    如果供应商不支持批量 input，自动逐条 fallback。
    返回与 texts 等长的列表，失败位置为 None。
    """
    if not texts:
        return []

    if not _is_embedding_configured():
        logger.warning("Embedding 配置不完整，跳过批量向量生成")
        return [None] * len(texts)

    results: list[list[float] | None] = [None] * len(texts)
    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)

    for batch_start in range(0, len(texts), batch_size):
        batch_end = min(batch_start + batch_size, len(texts))
        batch_texts = texts[batch_start:batch_end]

        # 过滤空文本
        valid_indices = [i for i, t in enumerate(batch_texts) if t and t.strip()]
        if not valid_indices:
            continue

        valid_texts = [batch_texts[i] for i in valid_indices]

        batch_embeddings = await _fetch_batch_embeddings(valid_texts)

        if batch_embeddings is None:
            # 批量失败，逐条 fallback
            for idx_pos, global_idx in enumerate(valid_indices):
                single = await get_embedding(batch_texts[global_idx])
                results[batch_start + global_idx] = single
        else:
            for idx_pos, global_idx in enumerate(valid_indices):
                if idx_pos < len(batch_embeddings):
                    results[batch_start + global_idx] = batch_embeddings[idx_pos]

    return results


async def _fetch_batch_embeddings(texts: list[str]) -> list[list[float]] | None:
    """尝试批量调用 embedding API。失败返回 None。"""
    url = f"{settings.EMBEDDING_BASE_URL.rstrip('/')}/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": texts,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.EMBEDDING_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.warning("Embedding 批量 API 请求失败", exc_info=True)
        return None

    try:
        items = sorted(data["data"], key=lambda x: x.get("index", 0))
        embeddings = [item["embedding"] for item in items]
    except (KeyError, TypeError):
        logger.warning("Embedding 批量 API 返回格式异常")
        return None

    expected_dim = settings.EMBEDDING_DIM
    for emb in embeddings:
        if not isinstance(emb, list) or len(emb) != expected_dim:
            logger.warning("Embedding 批量结果中存在维度不匹配")
            return None

    return embeddings


def vector_to_pg_literal(vec: list[float]) -> str:
    """将 Python list 转为 pgvector 可接受的字符串格式，如 [0.1,0.2,0.3]。"""
    return "[" + ",".join(str(v) for v in vec) + "]"
