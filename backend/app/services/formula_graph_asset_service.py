"""Formula graph asset service — query, upload, replace, delete with idempotency."""

import asyncio
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import utcnow
from app.models.formula import FormulaCard, FormulaGraphAsset
from app.services.storage_backend import get_storage

# Dedicated executor for CPU-bound image processing (PIL operations)
_image_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="img_proc")

logger = logging.getLogger(__name__)

# Allowed image types
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_WIDTH = 8000
MAX_HEIGHT = 8000
THUMBNAIL_SIZE = (600, 450)
# Function graphs are viewed on phone screens; serving multi-megabyte full-size
# PNGs is the dominant cause of slow rendering in the miniprogram. Cap the
# stored master image and re-encode it losslessly-optimized.
MAX_STORED_DIMENSION = 1600
PNG_OPTIMIZE = True


def _resize_within(img: Image.Image, max_dimension: int) -> Image.Image:
    """Downscale so that max(width, height) <= max_dimension (aspect preserved)."""
    if max(img.size) <= max_dimension:
        return img
    ratio = max_dimension / max(img.size)
    new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def _encode_stored_image(img: Image.Image) -> bytes:
    """Encode an image for storage as the main graph asset PNG."""
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=PNG_OPTIMIZE)
    return buf.getvalue()


def resolve_graph_asset_public_url(url: str | None) -> str | None:
    """Return a client-reachable URL for formula graph assets.

    Historical/local uploads may contain ``PUBLIC_BASE_URL`` with an API path
    (for example ``https://host/api/v1``) or a development host such as
    ``localhost``. Formula graph files are actually mounted at
    ``/static/formulas/...``. Rebase only those local-static URLs onto the
    current public origin, while leaving external object-storage/CDN URLs
    untouched.
    """
    raw = str(url or "").strip()
    if not raw:
        return None

    marker = "/static/formulas/"
    if raw.startswith("static/formulas/"):
        asset_path = "/" + raw
    elif marker in raw:
        asset_path = marker + raw.split(marker, 1)[1].lstrip("/")
    else:
        return raw

    base_raw = str(settings.PUBLIC_BASE_URL or "").strip()
    try:
        base = urlsplit(base_raw)
    except ValueError:
        base = None

    if not base or not base.scheme or not base.netloc:
        return asset_path

    # Root-relative paths and local/dev URLs are ours and should always use the
    # configured public origin. For an absolute URL on another host, preserve
    # it (e.g. COS/CDN) even if its object key contains /static/formulas/.
    try:
        source = urlsplit(raw)
    except ValueError:
        source = None

    source_host = (source.hostname or "").lower() if source else ""
    base_host = (base.hostname or "").lower()
    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    should_rebase = (
        settings.STORAGE_BACKEND == "local"
        or not source
        or not source.scheme
        or not source.netloc
        or source_host in local_hosts
        or source_host == base_host
    )
    if not should_rebase:
        return raw

    return f"{base.scheme}://{base.netloc}{asset_path}"


def choose_effective_graph_asset(
    assets: list[FormulaGraphAsset],
) -> FormulaGraphAsset | None:
    """Select the effective graph asset per priority:
    1. uploaded (manual) with valid image_url
    2. generated (auto-generated from spec) with valid image_url
    3. template (legacy template-based) with valid image_url
    4. any asset with image_url
    5. None
    """
    if not assets:
        return None

    for source in ("uploaded", "generated", "template"):
        matched = [a for a in assets if a.source_type == source and a.image_url]
        if matched:
            return matched[0]

    # Fallback: any asset with image_url
    for a in assets:
        if a.image_url:
            return a

    return None


def is_function_graph(
    card: FormulaCard, effective_asset: FormulaGraphAsset | None = None
) -> bool:
    """Unified classification: determine if a formula card is a function graph.

    Priority:
    1. ``card_type == \"function_graph\"`` → always True (explicit admin choice).
    2. ``card_type == \"pure_formula\"`` → always False (explicit admin choice).
    3. ``card_type == \"auto\"`` / unknown / legacy → True if the card has a valid
       graph image asset.

    This function is the single source of truth — every API endpoint and the
    admin UI should call it rather than duplicating the rules.
    """
    raw = (card.card_type or "").strip().lower()

    if raw == "function_graph":
        return True
    if raw == "pure_formula":
        return False

    # auto / null / unknown → check for an effective graph image
    if effective_asset and effective_asset.image_url:
        return True

    return False


async def load_graph_assets_map(
    db: AsyncSession,
    formula_card_ids: list[int],
) -> dict[int, list[FormulaGraphAsset]]:
    """Batch-load graph assets for multiple card IDs.

    Returns dict[card_id, list[FormulaGraphAsset]].
    """
    if not formula_card_ids:
        return {}

    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id.in_(formula_card_ids)
        )
    )
    assets = list(result.scalars().all())

    mapping: dict[int, list[FormulaGraphAsset]] = {}
    for asset in assets:
        mapping.setdefault(asset.formula_card_id, []).append(asset)

    # Ensure every requested card_id has an entry
    for cid in formula_card_ids:
        if cid not in mapping:
            mapping[cid] = []

    return mapping


def _validate_image(data: bytes, filename: str) -> tuple[Image.Image, str]:
    """Validate image file. Returns (PIL Image, mime_type). Raises ValueError."""
    if len(data) > MAX_IMAGE_SIZE:
        raise ValueError(f"文件大小超过 {MAX_IMAGE_SIZE // (1024 * 1024)}MB 限制")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 PNG/JPG/WebP")

    # Validate with PIL
    try:
        img = Image.open(BytesIO(data))
        img.verify()
    except Exception as e:
        raise ValueError(f"图片解码失败: {e}")

    # Re-open after verify (verify may leave file in a bad state)
    img = Image.open(BytesIO(data))

    # Determine mime type from actual image format
    format_map = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
    img_format = img.format
    mime_type = format_map.get(img_format, "image/png") if img_format else "image/png"

    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"不支持的图片格式: {mime_type}")

    width, height = img.size
    if width > MAX_WIDTH or height > MAX_HEIGHT:
        raise ValueError(
            f"图片尺寸过大 ({width}x{height})，最大支持 {MAX_WIDTH}x{MAX_HEIGHT}"
        )

    return img, mime_type


def _process_image(img: Image.Image) -> bytes:
    """Standardize image: handle EXIF orientation, downscale, save as PNG."""
    img = ImageOps.exif_transpose(img) or img

    # Keep RGBA for transparency, convert others to RGB
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    img = _resize_within(img, MAX_STORED_DIMENSION)
    return _encode_stored_image(img)


def _create_thumbnail(img: Image.Image) -> bytes:
    """Create a 600x450 letterbox thumbnail with white background."""
    img = ImageOps.exif_transpose(img) or img

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    # Create white canvas
    thumb = Image.new("RGBA", THUMBNAIL_SIZE, (255, 255, 255, 255))

    # Resize maintaining aspect ratio
    img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)

    # Paste centered
    x = (THUMBNAIL_SIZE[0] - img.width) // 2
    y = (THUMBNAIL_SIZE[1] - img.height) // 2
    if img.mode == "RGBA":
        thumb.paste(img, (x, y), img)
    else:
        thumb.paste(img, (x, y))

    return _encode_stored_image(thumb)


def _safe_delete_file(file_url: str) -> None:
    """Best-effort delete a local file from a URL path."""
    if not file_url or settings.STORAGE_BACKEND != "local":
        return
    try:
        # Extract relative path from URL
        prefix = f"{settings.PUBLIC_BASE_URL}/static/"
        if file_url.startswith(prefix):
            rel_path = file_url[len(prefix) :]
        elif "/static/" in file_url:
            rel_path = file_url.split("/static/", 1)[1]
        else:
            return

        # Prevent path traversal
        abs_path = os.path.normpath(os.path.join("static", rel_path))
        if not abs_path.startswith(os.path.normpath("static/")):
            logger.warning("Path traversal attempt blocked: %s", file_url)
            return

        if os.path.exists(abs_path):
            os.remove(abs_path)
            logger.info("Deleted old file: %s", abs_path)
    except Exception:
        logger.warning("Failed to delete old file: %s", file_url, exc_info=True)


async def get_graph_assets_for_card(
    db: AsyncSession,
    card_id: int,
) -> list[FormulaGraphAsset]:
    """Get all graph assets for a card."""
    result = await db.execute(
        select(FormulaGraphAsset).where(FormulaGraphAsset.formula_card_id == card_id)
    )
    return list(result.scalars().all())


async def get_effective_graph_asset_for_card(
    db: AsyncSession,
    card_id: int,
) -> FormulaGraphAsset | None:
    """Get the single effective graph asset for a card."""
    assets = await get_graph_assets_for_card(db, card_id)
    return choose_effective_graph_asset(assets)


async def upload_graph_asset(
    db: AsyncSession,
    card: FormulaCard,
    file_data: bytes,
    filename: str,
    admin_id: int,
) -> tuple[FormulaGraphAsset, bool]:
    """Upload or replace a graph asset for a function_graph card.

    Returns (asset, is_new). Idempotent: same checksum → return existing.
    PIL operations are offloaded to a dedicated thread pool.
    """
    loop = asyncio.get_running_loop()

    # Validate and process image in executor (off event loop)
    img, mime_type = await loop.run_in_executor(
        _image_executor,
        _validate_image,
        file_data,
        filename,
    )
    image_bytes = await loop.run_in_executor(
        _image_executor,
        _process_image,
        img,
    )
    thumbnail_bytes = await loop.run_in_executor(
        _image_executor,
        _create_thumbnail,
        img,
    )

    # Compute checksum
    import hashlib

    checksum = hashlib.sha256(image_bytes).hexdigest()

    # Re-open for dimension reading
    final_img = Image.open(BytesIO(image_bytes))
    width, height = final_img.size

    storage = get_storage()

    card_id = card.id
    asset_dir = f"graphs/{card_id}/uploaded"

    # Check if uploaded asset already exists
    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == card_id,
            FormulaGraphAsset.source_type == "uploaded",
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.checksum == checksum:
        # Idempotent: same checksum, skip
        return existing, False

    # Generate new UUID filename
    file_uuid = uuid.uuid4().hex
    main_filename = f"{asset_dir}/{file_uuid}.png"
    thumb_filename = f"{asset_dir}/{file_uuid}-thumb.png"

    # Upload files
    image_url = resolve_graph_asset_public_url(
        await storage.upload(main_filename, image_bytes)
    )
    thumbnail_url = resolve_graph_asset_public_url(
        await storage.upload(thumb_filename, thumbnail_bytes)
    )

    old_image_url = None
    old_thumbnail_url = None

    if existing:
        # Update existing
        old_image_url = existing.image_url
        old_thumbnail_url = existing.thumbnail_url
        existing.image_url = image_url
        existing.thumbnail_url = thumbnail_url
        existing.mime_type = mime_type
        existing.width = width
        existing.height = height
        existing.file_size = len(image_bytes)
        existing.checksum = checksum
        existing.updated_at = utcnow()
        db.add(existing)
        await db.flush()

        # Delete old files (best-effort, after DB flush)
        _safe_delete_file(old_image_url)
        _safe_delete_file(old_thumbnail_url)

        return existing, False
    else:
        # Create new
        asset = FormulaGraphAsset(
            formula_card_id=card_id,
            source_type="uploaded",
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            mime_type=mime_type,
            width=width,
            height=height,
            file_size=len(image_bytes),
            checksum=checksum,
        )
        db.add(asset)
        await db.flush()
        return asset, True


async def delete_asset_by_source_type(
    db: AsyncSession,
    card: FormulaCard,
    source_type: str,
) -> bool:
    """Delete a graph asset by source_type. Returns True if deleted.

    Only deletes from local storage. Files deleted best-effort after DB txn.
    """
    if source_type not in ("uploaded", "template", "generated"):
        raise ValueError(f"Unsupported source_type: {source_type}")

    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == card.id,
            FormulaGraphAsset.source_type == source_type,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        return False

    image_url = asset.image_url
    thumbnail_url = asset.thumbnail_url

    await db.delete(asset)
    await db.flush()

    # Best-effort delete files
    _safe_delete_file(image_url)
    _safe_delete_file(thumbnail_url)

    return True
