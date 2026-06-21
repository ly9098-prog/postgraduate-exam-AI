"""PaddleOCR 结果缓存：基于图片 SHA256 + 配置 hash 的文件缓存。

只在缓存 PaddleOCR 结果（text/boxes/confidence），不缓存 LLM 输出。
配置变化（语言、检测阈值等）自动导致缓存失效。
"""
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_DIR = os.environ.get("OCR_CACHE_DIR", os.path.join(os.getcwd(), ".backend_cache", "ocr"))
_ENABLED = os.environ.get("OCR_CACHE_ENABLED", "true").lower() == "true"
_TTL_SECONDS = 86400 * 14  # 14 天
_CLEANUP_INTERVAL = 50  # 每写入 N 次执行一次惰性清理
_cache_write_counter = 0


@dataclass
class OcrCacheEntry:
    text: str
    boxes: list[dict] = field(default_factory=list)
    avg_confidence: float = 0.0
    engine: str = "paddleocr"
    config_hash: str = ""
    created_at: str = ""


def _build_config_hash() -> str:
    """基于影响 OCR 输出的配置参数生成 hash。

    配置变化时 hash 改变 → 旧缓存自动失效。
    """
    raw = "|".join([
        settings.OCR_LANGUAGE or "ch",
        str(settings.OCR_DET_DB_THRESH),
        str(settings.OCR_DET_DB_BOX_THRESH),
        str(settings.OCR_DET_DB_UNCLIP_RATIO),
        str(settings.OCR_DROP_SCORE),
        str(os.environ.get("OCR_LOW_CONF_THRESHOLD", "0.55")),
    ])
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _image_sha256(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _cache_path(sha256: str, config_hash: str) -> str:
    """缓存文件路径：.backend_cache/ocr/{sha256[:2]}/{sha256}_{config_hash}.json

    使用 sha256 前 2 位作为子目录避免单目录文件过多。
    """
    subdir = sha256[:2]
    dir_path = os.path.join(_CACHE_DIR, subdir)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{sha256}_{config_hash}.json")


def make_cache_key(image_bytes: bytes) -> tuple[str, str]:
    """计算缓存 key 的组成部分。

    Returns:
        (sha256, config_hash)
    """
    sha256 = _image_sha256(image_bytes)
    config_hash = _build_config_hash()
    return sha256, config_hash


def _load_entry(path: str) -> OcrCacheEntry | None:
    """从文件加载缓存条目，损坏或超时时返回 None（超时的条目会顺便删除）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - os.path.getmtime(path)
        if _TTL_SECONDS > 0 and age > _TTL_SECONDS:
            logger.debug("OCR cache expired: %s (age=%.0fs)", path, age)
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        return OcrCacheEntry(**data)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.debug("OCR cache load failed for %s: %s", path, e)
        return None


def _save_entry(path: str, entry: OcrCacheEntry) -> None:
    """写入缓存条目。失败不抛异常。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(entry), f, ensure_ascii=False)
        _lazy_cache_cleanup()
    except OSError as e:
        logger.warning("OCR cache write failed: %s", e)


def _lazy_cache_cleanup() -> None:
    """惰性清理过期缓存文件。每写入 _CLEANUP_INTERVAL 次全量扫描一次。"""
    global _cache_write_counter
    _cache_write_counter += 1
    if _cache_write_counter % _CLEANUP_INTERVAL != 0:
        return
    try:
        now = time.time()
        expired = 0
        for root, _dirs, files in os.walk(_CACHE_DIR):
            for name in files:
                path = os.path.join(root, name)
                try:
                    if now - os.path.getmtime(path) > _TTL_SECONDS:
                        os.remove(path)
                        expired += 1
                except OSError:
                    pass
        if expired:
            logger.debug("OCR cache cleanup: removed %d expired files", expired)
    except Exception as e:
        logger.debug("OCR cache cleanup failed: %s", e)


def get_cached(
    image_bytes: bytes,
) -> OcrCacheEntry | None:
    """根据图片 bytes 查询 OCR 缓存。

    Args:
        image_bytes: 页面 PNG bytes

    Returns:
        缓存命中时返回 OcrCacheEntry，否则 None
    """
    if not _ENABLED:
        return None

    try:
        sha256, config_hash = make_cache_key(image_bytes)
        path = _cache_path(sha256, config_hash)
        entry = _load_entry(path)
        if entry is not None and entry.config_hash == config_hash:
            logger.debug("OCR cache HIT: sha256=%s... path=%s", sha256[:12], path)
            return entry
        if entry is not None:
            logger.debug(
                "OCR cache config mismatch: cached=%s current=%s",
                entry.config_hash, config_hash,
            )
    except Exception as e:
        logger.warning("OCR cache lookup failed, falling through: %s", e)

    return None


def set_cached(
    image_bytes: bytes,
    text: str,
    boxes: list[dict],
    avg_confidence: float,
) -> None:
    """将 OCR 结果写入缓存。

    Args:
        image_bytes: 页面 PNG bytes（用于计算 sha256）
        text: OCR 识别文本
        boxes: 检测框列表
        avg_confidence: 平均置信度
    """
    if not _ENABLED:
        return

    try:
        sha256, config_hash = make_cache_key(image_bytes)
        path = _cache_path(sha256, config_hash)
        entry = OcrCacheEntry(
            text=text,
            boxes=boxes,
            avg_confidence=round(avg_confidence, 4),
            engine="paddleocr",
            config_hash=config_hash,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        _save_entry(path, entry)
    except Exception as e:
        logger.warning("OCR cache write failed, skipping: %s", e)


def get_cache_stats() -> dict:
    """返回缓存统计信息。"""
    return {
        "enabled": _ENABLED,
        "cache_dir": _CACHE_DIR,
        "config_hash": _build_config_hash(),
        "ttl_seconds": _TTL_SECONDS,
    }
