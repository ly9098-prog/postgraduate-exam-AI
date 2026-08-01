import asyncio
import io
import logging
import os
import posixpath
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# Set PIL decompression bomb protection to prevent OOM from pathological images.
# The limit matches the maximum allowed PDF page pixel count from settings.
Image.MAX_IMAGE_PIXELS = settings.PDF_MAX_PAGE_PIXELS

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

    @staticmethod
    def _validated_upload_key(filename: str) -> str:
        """Return a normalized relative object key or reject path traversal."""
        raw = str(filename or "").strip()
        if not raw or len(raw) > 512:
            raise ValueError("invalid storage filename")
        if "\x00" in raw or "\\" in raw or any(ord(ch) < 32 for ch in raw):
            raise ValueError("invalid storage filename")
        if raw.startswith("/") or os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
            raise ValueError("absolute storage paths are not allowed")
        normalized = posixpath.normpath(raw)
        if normalized in {"", ".", ".."} or normalized.startswith("../"):
            raise ValueError("storage path traversal is not allowed")
        if any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("invalid storage filename")
        return normalized

    @abstractmethod
    async def upload(self, filename: str, data: bytes) -> str:
        """上传文件，返回绝对 URL 或可访问路径"""
        ...

    @abstractmethod
    async def delete(self, url_or_key: str) -> bool:
        """删除已上传的文件。失败或不存在时返回 False。"""
        ...

    @abstractmethod
    async def exists(self, url_or_key: str) -> bool:
        """检查文件是否存在。"""
        ...

    @abstractmethod
    async def get_download_url(self, url_or_key: str, expiry_sec: int = 3600) -> str | None:
        """获取下载 URL。

        LocalFileStorage: 返回 None（通过鉴权接口流式读取）。
        COSStorage: 返回短时签名 URL。
        """
        ...


class LocalFileStorage(StorageBackend):
    def __init__(self, prefix: str = "static/formulas"):
        super().__init__(prefix)

    async def upload(self, filename: str, data: bytes) -> str:
        safe_key = self._validated_upload_key(filename)
        base_dir = (
            os.path.realpath(self._prefix)
            if os.path.isabs(self._prefix)
            else os.path.realpath(os.path.join(_BACKEND_ROOT, self._prefix))
        )
        filepath = os.path.realpath(os.path.join(base_dir, safe_key))
        if not filepath.startswith(base_dir + os.sep):
            raise ValueError("storage path traversal is not allowed")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _storage_executor, self._sync_upload, filepath, data,
        )
        url_prefix = self._prefix.rstrip("/")
        if os.path.isabs(url_prefix):
            # Absolute local export directories are not directly public.
            return safe_key
        return f"{settings.PUBLIC_BASE_URL}/{url_prefix}/{safe_key}"

    @staticmethod
    def _sync_upload(filepath: str, data: bytes) -> None:
        """Write through a sibling temp file and atomically replace the target.

        Re-export uses the same stable file key. ``os.replace`` guarantees that
        readers either see the previous complete document or the new complete
        document, never a partially-written file.
        """
        directory = os.path.dirname(filepath)
        os.makedirs(directory, exist_ok=True)
        temp_path = f"{filepath}.tmp-{uuid.uuid4().hex}"
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, filepath)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

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

    async def get_download_url(self, url_or_key: str, expiry_sec: int = 3600) -> str | None:
        """Local storage: no public URL — stream through auth endpoint."""
        return None

    async def exists(self, url_or_key: str) -> bool:
        """Check if a local file exists."""
        rel = self._resolve_delete_path(url_or_key)
        if rel is None:
            return False
        filepath = os.path.join(_BACKEND_ROOT, rel)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _storage_executor, os.path.exists, filepath,
        )

    def _resolve_delete_path(self, url_or_key: str) -> str | None:
        """Resolve URL or key to a relative path, with path traversal protection.

        Accepts:
        - Full HTTP URL (extracts the path component)
        - Absolute path that already includes self._prefix
        - Relative key that will be joined with self._prefix

        When ``self._prefix`` is an absolute path, returns an absolute path.
        When ``self._prefix`` is a relative path, returns a path relative to
        ``_BACKEND_ROOT``.
        """
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

        if os.path.isabs(self._prefix):
            # Absolute prefix: resolve directly
            filepath = os.path.join(self._prefix, normalized)
            # Ensure it's within the prefix (path traversal protection)
            real_prefix = os.path.realpath(self._prefix)
            real_path = os.path.realpath(filepath)
            if not real_path.startswith(real_prefix + os.sep):
                logger.warning("Path traversal blocked: %s -> %s", url_or_key, real_path)
                return None
            return filepath

        if normalized.startswith("/"):
            normalized = normalized.lstrip("/")
            prefix_normalized = self._prefix.lstrip("/")
            if not normalized.startswith(prefix_normalized + "/"):
                logger.warning("Delete rejected: path %s outside prefix %s", normalized, self._prefix)
                return None
            return normalized
        else:
            prefix_clean = self._prefix.lstrip("/")
            # If the key already starts with the prefix, use it as-is
            if normalized.startswith(prefix_clean + "/"):
                return normalized
            # Otherwise, join with prefix (relative key mode for export files)
            return f"{prefix_clean}/{normalized}"

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
        try:
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(
                Region=self._region,
                SecretId=settings.COS_SECRET_ID,
                SecretKey=settings.COS_SECRET_KEY,
                Endpoint=settings.COS_ENDPOINT or None,
            )
            self._client = CosS3Client(config)
            return self._client
        except Exception as e:
            logger.warning("COS client init failed: %s", e)
            return None

    def _build_key(self, filename: str) -> str:
        safe_key = self._validated_upload_key(filename)
        return f"{self._cos_prefix.rstrip('/')}/{safe_key}"

    def _normalize_key(self, key: str) -> str:
        """Ensure a storage key includes the COS prefix.

        Saved file_key may be just '{task.id}/{filename}' without the
        'var/exports/' prefix. This method normalizes it so that
        delete, get_download_url, and exists find the correct object.
        """
        bucket_domain = f"{self._bucket}.cos.{self._region}.myqcloud.com"
        if bucket_domain in key:
            return key.split(bucket_domain, 1)[1].lstrip("/")
        prefix = self._cos_prefix.rstrip("/")
        if not key.startswith(prefix + "/") and not key.startswith("http"):
            return f"{prefix}/{key.lstrip('/')}"
        return key

    async def upload(self, filename: str, data: bytes) -> str:
        client = self._get_client()
        if client is None:
            if settings.COS_ALLOW_LOCAL_FALLBACK:
                logger.error("COS backend not configured, falling back to local storage")
                return await LocalFileStorage(self._prefix).upload(filename, data)
            raise RuntimeError("COS backend not configured and local fallback is disabled")

        key = self._build_key(filename)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                _storage_executor,
                lambda: client.put_object(Bucket=self._bucket, Body=data, Key=key),
            )
            return f"https://{self._bucket}.cos.{self._region}.myqcloud.com/{key}"
        except Exception:
            if settings.COS_ALLOW_LOCAL_FALLBACK:
                logger.exception("COS upload failed, falling back to local storage")
                return await LocalFileStorage(self._prefix).upload(filename, data)
            logger.exception("COS upload failed and local fallback is disabled")
            raise

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

        key = self._normalize_key(url_or_key)

        # 验证命名空间
        prefix = self._cos_prefix.rstrip("/")
        if not key.startswith(prefix + "/"):
            logger.warning("COS delete rejected: key %s outside prefix %s", key, prefix)
            return False

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                _storage_executor,
                lambda: client.delete_object(Bucket=self._bucket, Key=key),
            )
            return True
        except Exception as e:
            logger.error("COS delete failed for %s: %s", key, e)
            return False

    async def get_download_url(self, url_or_key: str, expiry_sec: int = 3600) -> str | None:
        """Generate a short-lived signed URL for secure download.

        Returns None if the backend is not configured or the key is invalid.
        """
        client = self._get_client()
        if client is None:
            return None

        key = self._normalize_key(url_or_key)

        try:
            loop = asyncio.get_running_loop()
            signed_url = await loop.run_in_executor(
                _storage_executor,
                lambda: client.get_presigned_url(
                    Bucket=self._bucket,
                    Key=key,
                    Method="GET",
                    Expired=expiry_sec,
                ),
            )
            return str(signed_url)
        except Exception as e:
            logger.error("Failed to generate signed URL for %s: %s", key, e)
            return None

    async def exists(self, url_or_key: str) -> bool:
        """Check if a COS object exists."""
        client = self._get_client()
        if client is None:
            return False

        key = self._normalize_key(url_or_key)

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                _storage_executor,
                lambda: client.object_exists(Bucket=self._bucket, Key=key),
            )
            return bool(response)
        except Exception as e:
            logger.error("COS exists check failed for %s: %s", key, e)
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


# Singleton cache for storage instances (avoid creating new COS clients per call)
_export_storage_instance: StorageBackend | None = None


def get_export_storage() -> StorageBackend:
    """获取用于导出文件的 storage backend。

    LocalFileStorage: 写入 EXPORT_DIR 目录。
    COSStorage: 使用 EXPORT_DIR 作为 COS 对象前缀。

    Returns a cached singleton instance to avoid creating new COS clients
    (with their connection pools) on every call.
    """
    global _export_storage_instance
    if _export_storage_instance is not None:
        return _export_storage_instance

    prefix = settings.EXPORT_DIR
    if settings.STORAGE_BACKEND == "cos":
        cos = COSStorage(prefix=prefix)
        cos._cos_prefix = f"{prefix}/"
        _export_storage_instance = cos
    else:
        _export_storage_instance = LocalFileStorage(prefix=prefix)
    return _export_storage_instance


def get_export_storage_root() -> str:
    """Return the absolute filesystem root directory for export files.

    Used by both the storage backend and API layer to resolve file paths
    consistently. Prevents directory traversal and symlink attacks.
    """
    root = os.path.realpath(os.path.join(_BACKEND_ROOT, settings.EXPORT_DIR))
    # Ensure directory exists
    os.makedirs(root, exist_ok=True)
    return root
