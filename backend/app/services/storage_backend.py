import asyncio
import io
import logging
import os
import posixpath
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# Resolve backend root directory for consistent relative path handling.
_BACKEND_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Dedicated executor for storage I/O (off event loop)
_storage_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="storage")


# ── Image compression ────────────────────────────────────────────────────

MAX_IMAGE_DIMENSION = 1200
JPEG_QUALITY = 85
PNG_OPTIMIZE = True


def compress_image(data: bytes, max_dimension: int = MAX_IMAGE_DIMENSION) -> bytes:
    """Compress and optionally resize an image to reduce file size.

    - Resizes so that max(width, height) ≤ max_dimension (preserving aspect ratio).
    - JPEG: quality 85.
    - PNG: optimize=True, convert to palette if possible.
    - WebP: quality 85.
    - Other formats (GIF, BMP, TIFF): convert to JPEG.
    """
    img = Image.open(io.BytesIO(data))
    fmt = img.format or "JPEG"

    # Resize if needed
    if max(img.size) > max_dimension:
        ratio = max_dimension / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()

    if fmt == "PNG":
        # Convert to RGB if no transparency, keep RGBA otherwise
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img.save(buf, format="PNG", optimize=PNG_OPTIMIZE)
        else:
            img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    elif fmt in ("JPEG", "WEBP"):
        img.save(buf, format=fmt, quality=JPEG_QUALITY)
    else:
        # GIF, BMP, TIFF → JPEG
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)

    return buf.getvalue()


class StorageBackend(ABC):
    def __init__(self, prefix: str = "static/formulas"):
        self._prefix = prefix.rstrip("/")

    @abstractmethod
    async def upload(self, filename: str, data: bytes) -> str:
        """上传图片，返回绝对 HTTP URL"""
        ...

    @abstractmethod
    async def delete(self, url_or_key: str) -> bool:
        """删除已上传的文件。失败或不存在时返回 False。"""
        ...


class LocalFileStorage(StorageBackend):
    def __init__(self, prefix: str = "static/formulas"):
        self._prefix = prefix

    async def upload(self, filename: str, data: bytes) -> str:
        loop = asyncio.get_running_loop()
        filepath = os.path.join(_BACKEND_ROOT, self._prefix, filename)
        await loop.run_in_executor(
            _storage_executor, self._sync_upload, filepath, data,
        )
        url_prefix = self._prefix.rstrip("/")
        return f"{settings.PUBLIC_BASE_URL}/{url_prefix}/{filename}"

    @staticmethod
    def _sync_upload(filepath: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)

    async def delete(self, url_or_key: str) -> bool:
        """删除本地文件。（路径解析快速完成，文件 I/O 在 executor 中执行）"""
        rel = self._resolve_delete_path(url_or_key)
        if rel is None:
            return False

        filepath = os.path.join(_BACKEND_ROOT, rel)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _storage_executor, self._sync_delete, filepath,
        )

    def _resolve_delete_path(self, url_or_key: str) -> str | None:
        """Resolve URL or key to a relative path, with path traversal protection."""
        if url_or_key.startswith("http"):
            if settings.PUBLIC_BASE_URL and url_or_key.startswith(settings.PUBLIC_BASE_URL):
                rel = url_or_key[len(settings.PUBLIC_BASE_URL):].lstrip("/")
            elif "/static/" in url_or_key:
                rel = url_or_key.split("/static/", 1)[1]
            else:
                logger.warning("Cannot extract path from URL outside public base: %s", url_or_key)
                return None
        else:
            rel = url_or_key

        normalized = posixpath.normpath(rel)
        if normalized.startswith(".."):
            logger.warning("Path traversal rejected: %s", url_or_key)
            return None
        if normalized.startswith("/"):
            normalized = normalized.lstrip("/")
            prefix_normalized = self._prefix.lstrip("/")
            if not normalized.startswith(prefix_normalized + "/"):
                logger.warning("Delete rejected: path %s outside prefix %s", normalized, self._prefix)
                return None
        else:
            if not normalized.startswith(self._prefix.lstrip("/") + "/"):
                logger.warning("Delete rejected: path %s outside prefix %s", normalized, self._prefix)
                return None
        return normalized

    @staticmethod
    def _sync_delete(filepath: str) -> bool:
        if not os.path.exists(filepath):
            return True
        try:
            os.remove(filepath)
            return True
        except OSError as e:
            logger.error("Failed to delete %s: %s", filepath, e)
            return False


class COSStorage(StorageBackend):
    """Tencent Cloud Object Storage backend.

    Requires COS_BUCKET, COS_REGION, COS_SECRET_ID, and COS_SECRET_KEY
    to be configured in settings. Falls back gracefully with a log warning
    if credentials are missing.
    """

    def __init__(self, prefix: str = "static/formulas") -> None:
        super().__init__(prefix)
        self._client = None
        self._bucket = settings.COS_BUCKET
        self._region = settings.COS_REGION
        self._cos_prefix = settings.COS_PREFIX or "static/formulas/"

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._bucket or not self._region:
            logger.warning("COS_BUCKET or COS_REGION not configured, upload will fail")
            return None
        from qcloud_cos import CosConfig, CosS3Client

        config = CosConfig(
            Region=self._region,
            SecretId=settings.COS_SECRET_ID,
            SecretKey=settings.COS_SECRET_KEY,
            Endpoint=settings.COS_ENDPOINT or None,
        )
        self._client = CosS3Client(config)
        return self._client

    def _build_key(self, filename: str) -> str:
        return f"{self._cos_prefix.rstrip('/')}/{filename.lstrip('/')}"

    async def upload(self, filename: str, data: bytes) -> str:
        client = self._get_client()
        if client is None:
            logger.error("COS backend not configured, falling back to local storage")
            return await LocalFileStorage(self._prefix).upload(filename, data)

        key = self._build_key(filename)
        try:
            client.put_object(Bucket=self._bucket, Body=data, Key=key)
            return f"https://{self._bucket}.cos.{self._region}.myqcloud.com/{key}"
        except Exception:
            logger.exception("COS upload failed, falling back to local storage")
            return await LocalFileStorage(self._prefix).upload(filename, data)

    async def delete(self, url_or_key: str) -> bool:
        """删除 COS 对象。

        安全限制：
        - 只能删除 self._cos_prefix 命名空间下的对象
        - 删除失败时记录错误
        - 对象不存在时视为成功（幂等）
        """
        client = self._get_client()
        if client is None:
            logger.warning("COS delete skipped: backend not configured")
            return False

        # 从 URL 提取 key
        bucket_domain = f"{self._bucket}.cos.{self._region}.myqcloud.com"
        if bucket_domain in url_or_key:
            key = url_or_key.split(bucket_domain, 1)[1].lstrip("/")
        else:
            key = url_or_key

        # 验证命名空间
        prefix = self._cos_prefix.rstrip("/")
        if not key.startswith(prefix + "/"):
            logger.warning("COS delete rejected: key %s outside prefix %s", key, prefix)
            return False

        try:
            client.delete_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as e:
            logger.error("COS delete failed for %s: %s", key, e)
            return False


def get_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "cos":
        return COSStorage()
    return LocalFileStorage()


def get_question_assets_storage() -> StorageBackend:
    """获取用于题图存储的 storage backend（独立于公式图存储）。"""
    prefix = "static/question-assets"
    if settings.STORAGE_BACKEND == "cos":
        return COSStorage(prefix=prefix)
    return LocalFileStorage(prefix=prefix)
