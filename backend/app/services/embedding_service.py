"""Embedding 服务：文本构建、向量计算、批量处理。

配置来源优先级：DB（通过 EmbeddingConfig）→ 环境变量（兜底）。
所有异步函数均接受可选的 ``config: EmbeddingConfig`` 参数。
当 config 为 None 时，自动从环境变量构建配置（保持向后兼容）。
"""

import asyncio
import hashlib
import json
import logging
from typing import Any

from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.services.safe_remote_fetch import request_remote_bytes

logger = logging.getLogger("postgraduate-ai.embedding")


# ---------------------------------------------------------------------------
# Lazy import to avoid circular dependency at module load time
# ---------------------------------------------------------------------------


def _get_embedding_config():
    """同步获取 Embedding 配置。"""
    from app.core.config import settings
    from app.services.vector_config_service import EmbeddingConfig

    return EmbeddingConfig(
        api_key="",
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dim=settings.EMBEDDING_DIM,
        timeout=settings.EMBEDDING_TIMEOUT,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
        provider=settings.EMBEDDING_PROVIDER,
    )


# ---------------------------------------------------------------------------
# 文本构建（纯函数，不需要配置）
# ---------------------------------------------------------------------------


def build_question_embedding_text(
    question: Any,
    *,
    subject_code: str | None = None,
    knowledge_points: list[str] | None = None,
) -> str:
    """将题目信息组装为 embedding 文本。

    包含: subject, question_type, difficulty, knowledge_points, stem, options, analysis。
    **不包含 answer**，防止 embedding 泄露答案信息。

    ``subject_code`` 用于调用方已经解析出科目代码、但 ORM relationship
    没有预加载的场景。未提供时保持原有的自动推断行为。
    ``knowledge_points`` 由调用方从 question_knowledge_points 关联表批量加载后传入。
    """
    parts: list[str] = []

    subj_ref = getattr(question, "subject_ref", None)
    subject = (
        subject_code
        or (subj_ref.code if subj_ref else "")
        or (getattr(question, "subject_id", "") or "")
    )
    if subject:
        parts.append(f"科目：{subject}")

    q_type = getattr(question, "question_type", "") or ""
    if q_type:
        parts.append(f"题型：{q_type}")

    difficulty = getattr(question, "difficulty", None)
    if difficulty is not None:
        parts.append(f"难度：{difficulty}")

    kps = knowledge_points if knowledge_points is not None else []
    if kps:
        parts.append(f"知识点：{'、'.join(str(k) for k in kps)}")

    content = getattr(question, "content", None) or {}
    if isinstance(content, dict):
        stem = content.get("text", "") or content.get("stem", "") or ""
    else:
        stem = str(content or "")
    if stem:
        parts.append(f"题干：{stem.strip()}")

    options = getattr(question, "options", None)
    if options and isinstance(options, dict):
        opt_lines = []
        for key in sorted(options.keys()):
            opt_lines.append(f"{key}. {options[key]}")
        if opt_lines:
            parts.append("选项：\n" + "\n".join(opt_lines))

    analysis = getattr(question, "analysis", None) or ""
    if analysis:
        parts.append(f"解析摘要：{str(analysis).strip()[:500]}")

    return "\n".join(parts)


def compute_content_hash(text: str) -> str:
    """SHA-256 哈希，返回 64 位 hex 字符串。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Embedding API 调用
# ---------------------------------------------------------------------------


def build_embeddings_url(base_url: str) -> str:
    """Build an OpenAI-compatible embeddings endpoint from an SDK-style base URL.

    The admin UI stores SDK ``base_url`` values rather than full request URLs.
    Be forgiving for common Alibaba Model Studio inputs because operators often
    paste ``.../compatible-mode`` without the trailing ``/v1``.

    Examples:
    - ``https://api.openai.com/v1`` -> ``.../v1/embeddings``
    - ``.../compatible-mode/v1`` -> ``.../compatible-mode/v1/embeddings``
    - ``.../compatible-mode`` -> ``.../compatible-mode/v1/embeddings``
    - Alibaba workspace host only -> ``.../compatible-mode/v1/embeddings``
    - ``.../api/v3`` -> ``.../api/v3/embeddings``
    - a full ``.../embeddings`` endpoint is preserved
    """
    from urllib.parse import urlparse

    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    path_lower = path.lower()
    host = (parsed.hostname or "").lower()

    if path_lower.endswith("/embeddings"):
        return normalized

    # Alibaba Model Studio's OpenAI-compatible endpoint is rooted at
    # /compatible-mode/v1. Accept the frequently pasted parent path too.
    if path_lower.endswith("/compatible-mode"):
        return f"{normalized}/v1/embeddings"
    if path_lower.endswith("/compatible-mode/v1"):
        return f"{normalized}/embeddings"

    # Workspace-specific Model Studio domains are also commonly pasted as a
    # bare host. Give them the provider's OpenAI-compatible root instead of the
    # generic /v1 root used by OpenAI/vLLM-style servers.
    is_alibaba_model_studio = host.endswith(".maas.aliyuncs.com") or host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "cn-hongkong.dashscope.aliyuncs.com",
    }
    if not path and is_alibaba_model_studio:
        return f"{normalized}/compatible-mode/v1/embeddings"

    if not path:
        return f"{normalized}/v1/embeddings"
    return f"{normalized}/embeddings"


def _is_embedding_configured(cfg=None) -> bool:
    """检查 embedding 所需配置是否完整。"""
    if cfg is not None:
        return bool(cfg.api_key and cfg.base_url and cfg.model)
    cfg = _get_embedding_config()
    return bool(cfg.api_key and cfg.base_url and cfg.model)


async def _request_embeddings(url: str, payload: dict, cfg) -> tuple[int, dict]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    response = await asyncio.to_thread(
        request_remote_bytes,
        url,
        method="POST",
        body=body,
        max_bytes=64 * 1024 * 1024,
        timeout=float(cfg.timeout),
        allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
        follow_redirects=False,
        headers={
            **get_trace_headers(),
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    data = json.loads(response.data.decode("utf-8", errors="strict"))
    return response.status, data


async def get_embedding(text: str, *, config=None) -> list[float] | None:
    """调用 OpenAI-compatible embeddings API 获取单条文本的 embedding 向量。

    Args:
        text: 待向量化的文本。
        config: 可选的 EmbeddingConfig。为 None 时使用环境变量兜底。

    返回 None 表示获取失败（配置缺失、请求异常、维度不匹配等）。
    """
    cfg = config or _get_embedding_config()
    if not (cfg.api_key and cfg.base_url and cfg.model):
        logger.warning("Embedding 配置不完整，跳过向量生成")
        return None

    if not text or not text.strip():
        return None

    url = build_embeddings_url(cfg.base_url)
    payload = {
        "model": cfg.model,
        "input": text,
    }

    try:
        status_code, data = await _request_embeddings(url, payload, cfg)
        if status_code != 200:
            logger.warning("Embedding API 返回错误: status=%s", status_code)
            return None
    except Exception:
        logger.warning("Embedding API 请求失败", exc_info=True)
        return None

    try:
        embedding = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Embedding API 返回格式异常")
        return None

    if not isinstance(embedding, list):
        logger.warning("Embedding 返回值不是 list")
        return None

    if len(embedding) != cfg.dim:
        logger.warning(
            "Embedding 维度不匹配: expected=%d, got=%d", cfg.dim, len(embedding)
        )
        return None

    return embedding


async def get_embeddings_batch(
    texts: list[str], *, config=None
) -> list[list[float] | None]:
    """批量获取 embedding。按 batch_size 分批调用 API。

    如果供应商不支持批量 input，自动逐条 fallback。
    返回与 texts 等长的列表，失败位置为 None。
    """
    if not texts:
        return []

    cfg = config or _get_embedding_config()
    if not (cfg.api_key and cfg.base_url and cfg.model):
        logger.warning("Embedding 配置不完整，跳过批量向量生成")
        return [None] * len(texts)

    results: list[list[float] | None] = [None] * len(texts)
    batch_size = max(1, cfg.batch_size)

    for batch_start in range(0, len(texts), batch_size):
        batch_end = min(batch_start + batch_size, len(texts))
        batch_texts = texts[batch_start:batch_end]

        valid_indices = [i for i, t in enumerate(batch_texts) if t and t.strip()]
        if not valid_indices:
            continue

        valid_texts = [batch_texts[i] for i in valid_indices]

        batch_embeddings = await _fetch_batch_embeddings(valid_texts, cfg)

        if batch_embeddings is None:
            for idx_pos, global_idx in enumerate(valid_indices):
                single = await get_embedding(batch_texts[global_idx], config=cfg)
                results[batch_start + global_idx] = single
        else:
            for idx_pos, global_idx in enumerate(valid_indices):
                if idx_pos < len(batch_embeddings):
                    results[batch_start + global_idx] = batch_embeddings[idx_pos]

    return results


async def _fetch_batch_embeddings(texts: list[str], cfg) -> list[list[float]] | None:
    """尝试批量调用 embedding API。失败返回 None。"""
    url = build_embeddings_url(cfg.base_url)
    payload = {
        "model": cfg.model,
        "input": texts,
    }

    try:
        status_code, data = await _request_embeddings(url, payload, cfg)
        if status_code != 200:
            logger.warning("Embedding 批量 API 返回错误: status=%s", status_code)
            return None
    except Exception:
        logger.warning("Embedding 批量 API 请求失败", exc_info=True)
        return None

    try:
        items = sorted(data["data"], key=lambda x: x.get("index", 0))
        embeddings = [item["embedding"] for item in items]
    except (KeyError, TypeError):
        logger.warning("Embedding 批量 API 返回格式异常")
        return None

    for emb in embeddings:
        if not isinstance(emb, list) or len(emb) != cfg.dim:
            logger.warning("Embedding 批量结果中存在维度不匹配")
            return None

    return embeddings


def vector_to_pg_literal(vec: list[float]) -> str:
    """将 Python list 转为 pgvector 可接受的字符串格式，如 [0.1,0.2,0.3]。"""
    return "[" + ",".join(str(v) for v in vec) + "]"
