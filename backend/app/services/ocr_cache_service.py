"""PaddleOCR 结果缓存：基于图片 SHA256 + 配置 fingerprint 的文件缓存。

只在缓存 PaddleOCR 结果（text/boxes/confidence），不缓存 LLM 输出。
配置变化（语言、检测阈值等）自动导致缓存失效。

缓存键包含：
- 图片内容（SHA256）
- OCR 引擎配置（语言、阈值、drop_score 等）
- 引擎版本指纹（ppocrv4）
- 预处理策略版本（prep_v1）
- 输出 schema 版本（schema_v1）
"""
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)

_CACHE_DIR = os.environ.get("OCR_CACHE_DIR", os.path.join(os.getcwd(), ".backend_cache", "ocr"))
_ENABLED = os.environ.get("OCR_CACHE_ENABLED", "true").lower() == "true"
_TTL_SECONDS = 86400 * 14  # 14 天

# Schema version — bump when the cache entry format changes to invalidate
# all existing entries
_CACHE_SCHEMA_VERSION = "s1"

# Periodic cleanup: runs cleanup_expired_entries every N writes to prevent
# unbounded disk growth from stale cache entries (engine upgrade, config change).
_CLEANUP_INTERVAL = 200
_cache_write_counter = 0


@dataclass
class OcrCacheEntry:
    text: str
    boxes: list[dict] = field(default_factory=list)
    avg_confidence: float = 0.0
    engine: str = "paddleocr"
    config_hash: str = ""
    schema_version: str = _CACHE_SCHEMA_VERSION
    created_at: str = ""


def _build_engine_fingerprint() -> str:
    """Build a content-addressed fingerprint of all cache-relevant dimensions.

    When any dimension changes, the fingerprint changes and existing cache
    entries are naturally invalidated (different filename).

    Dimensions:
    - OCR configuration (language, thresholds, etc.)
    - Engine version identifier
    - Preprocessing strategy version
    - Cache schema version
    - Python version (minor ABI changes may affect preprocessing)
    """
    raw = "|".join([
        settings.OCR_LANGUAGE or "ch",
        str(settings.OCR_DET_DB_THRESH),
        str(settings.OCR_DET_DB_BOX_THRESH),
        str(settings.OCR_DET_DB_UNCLIP_RATIO),
        str(settings.OCR_DROP_SCORE),
        str(os.environ.get("OCR_LOW_CONF_THRESHOLD", "0.55")),
        "engine:ppocrv4",
        "prep:v1",
        f"schema:{_CACHE_SCHEMA_VERSION}",
        f"py:{sys.version_info.major}.{sys.version_info.minor}",
    ])
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _image_sha256(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _cache_path(sha256: str, fingerprint: str) -> str:
    """缓存文件路径：.backend_cache/ocr/{sha256[:2]}/{sha256}_{fingerprint}.json

    使用 sha256 前 2 位作为子目录避免单目录文件过多。
    """
    subdir = sha256[:2]
    dir_path = os.path.join(_CACHE_DIR, subdir)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{sha256}_{fingerprint}.json")


def make_cache_key(image_bytes: bytes) -> tuple[str, str]:
    """计算缓存 key 的组成部分。

    Returns:
        (sha256, fingerprint)
    """
    sha256 = _image_sha256(image_bytes)
    fingerprint = _build_engine_fingerprint()
    return sha256, fingerprint


def _load_entry(path: str) -> OcrCacheEntry | None:
    """从文件加载缓存条目，损坏或超时时返回 None（超时的条目会顺便删除）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - os.path.getmtime(path)
        if _TTL_SECONDS > 0 and age > _TTL_SECONDS:
            logger.debug("OCR cache expired: %s (age=%.0fs)", path, age)
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        entry = OcrCacheEntry(**data)
        # Reject entries with unknown schema version
        if entry.schema_version != _CACHE_SCHEMA_VERSION:
            logger.debug(
                "OCR cache schema mismatch: cached=%s current=%s",
                entry.schema_version, _CACHE_SCHEMA_VERSION,
            )
            return None
        return entry
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.debug("OCR cache load failed for %s: %s", path, e)
        return None


def _save_entry(path: str, entry: OcrCacheEntry) -> None:
    """写入缓存条目。使用 tempfile + fsync + os.replace 原子写入。"""
    try:
        dir_path = os.path.dirname(path)
        os.makedirs(dir_path, exist_ok=True)
        tmp = path + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(entry), f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("OCR cache write failed: %s", e)
        try:
            os.remove(tmp)
        except OSError:
            pass


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
        sha256, fingerprint = make_cache_key(image_bytes)
        path = _cache_path(sha256, fingerprint)
        entry = _load_entry(path)
        if entry is not None and entry.config_hash == fingerprint:
            logger.debug("OCR cache HIT: sha256=%s... path=%s", sha256[:12], path)
            return entry
        if entry is not None:
            logger.debug(
                "OCR cache fingerprint mismatch: cached=%s current=%s",
                entry.config_hash, fingerprint,
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
        sha256, fingerprint = make_cache_key(image_bytes)
        path = _cache_path(sha256, fingerprint)
        entry = OcrCacheEntry(
            text=text,
            boxes=boxes,
            avg_confidence=round(avg_confidence, 4),
            engine="paddleocr",
            config_hash=fingerprint,
            schema_version=_CACHE_SCHEMA_VERSION,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        _save_entry(path, entry)

        # 定期清理过期缓存，防止引擎升级/配置变更后旧文件无限堆积
        global _cache_write_counter
        _cache_write_counter += 1
        if _cache_write_counter >= _CLEANUP_INTERVAL:
            _cache_write_counter = 0
            try:
                result = cleanup_expired_entries()
                if result.get("deleted_count", 0) > 0:
                    logger.info(
                        "OCR cache cleanup: deleted %d expired entries (%.1f MB)",
                        result["deleted_count"],
                        result.get("freed_bytes", 0) / 1024 / 1024,
                    )
            except Exception:
                logger.warning("OCR cache cleanup failed, skipping", exc_info=True)
    except Exception as e:
        logger.warning("OCR cache write failed, skipping: %s", e)


def get_cache_stats() -> dict:
    """返回缓存统计信息。"""
    return {
        "enabled": _ENABLED,
        "cache_dir": _CACHE_DIR,
        "config_hash": _build_engine_fingerprint(),
        "ttl_seconds": _TTL_SECONDS,
        "schema_version": _CACHE_SCHEMA_VERSION,
    }


def cleanup_expired_entries(
    ttl: int | None = None,
    dry_run: bool = False,
) -> dict:
    """扫描 OCR 缓存目录并删除过期条目。

    Args:
        ttl: 过期秒数（默认 _TTL_SECONDS = 14 天）。
        dry_run: 为 True 时只扫描不删除。

    Returns:
        {
            "scanned_count": 扫描文件数,
            "deleted_count": 删除文件数,
            "freed_bytes": 释放字节数,
            "skipped_count": 跳过的文件数（非缓存文件等）,
        }
    """
    if not os.path.isdir(_CACHE_DIR):
        logger.info("OCR cache directory %s does not exist, nothing to clean", _CACHE_DIR)
        return {"scanned_count": 0, "deleted_count": 0, "freed_bytes": 0, "skipped_count": 0}

    ttl = ttl or _TTL_SECONDS
    now = time.time()
    cutoff = now - ttl

    scanned = 0
    deleted = 0
    freed = 0
    skipped = 0

    for root, dirs, files in os.walk(_CACHE_DIR):
        for filename in files:
            if not filename.endswith(".json"):
                skipped += 1
                continue

            path = os.path.join(root, filename)
            scanned += 1
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                skipped += 1
                continue

            if mtime < cutoff:
                size = 0
                try:
                    size = os.path.getsize(path)
                except OSError:
                    pass

                if not dry_run:
                    try:
                        os.remove(path)
                        deleted += 1
                        freed += size
                    except OSError as exc:
                        logger.warning("Failed to remove expired cache entry %s: %s", path, exc)
                else:
                    deleted += 1
                    freed += size

        # Try to remove empty subdirectories (only when not dry_run)
        if not dry_run:
            for d in dirs:
                subdir = os.path.join(root, d)
                try:
                    if not os.listdir(subdir):
                        os.rmdir(subdir)
                except OSError:
                    pass

    # Try to remove top-level empty subdirs
    if not dry_run:
        try:
            for entry in os.listdir(_CACHE_DIR):
                sub = os.path.join(_CACHE_DIR, entry)
                if os.path.isdir(sub) and not os.listdir(sub):
                    os.rmdir(sub)
        except OSError:
            pass

    logger.info(
        "OCR cache cleanup: scanned=%d, deleted=%d, freed=%d bytes, skipped=%d (dry_run=%s)",
        scanned, deleted, freed, skipped, dry_run,
    )
    return {
        "scanned_count": scanned,
        "deleted_count": deleted,
        "freed_bytes": freed,
        "skipped_count": skipped,
    }
