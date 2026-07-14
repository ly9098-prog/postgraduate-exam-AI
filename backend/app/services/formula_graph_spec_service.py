"""Graph spec orchestration service — preview, confirm, regenerate, batch."""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.formula import FormulaCard, FormulaGraphAsset, FormulaGraphPreview
from app.services.storage_backend import get_storage
from app.services.formula_graph_spec_renderer import (
    RENDERER_VERSION,
    GRAPH_THEME,
    check_quality,
    render_and_check,
    _resize_to_canvas,
    _create_thumbnail,
)

logger = logging.getLogger(__name__)

# ── Constants ──

PREVIEW_TTL_MINUTES = 60
BATCH_MAX_SIZE = 50
MAX_RETRIES = 3
CACHE_KEY_PARTS = [
    "formula_graph_cache_v1",
    str(RENDERER_VERSION),
    str(GRAPH_THEME["version"]),
    str(GRAPH_THEME.get("font", {}).get("family", "")),
]

STORAGE_PREFIX = "graphs"


def _spec_cache_key(spec: dict) -> str:
    """Deterministic cache key from spec + version info."""
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    parts = CACHE_KEY_PARTS + [raw]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _storage_path(card_id: int, subdir: str, checksum: str, suffix: str = "") -> str:
    return f"{STORAGE_PREFIX}/{card_id}/{subdir}/{checksum}{suffix}.png"


# ── Per-card concurrency guard ──

_card_locks: dict[int, asyncio.Lock] = {}
_lock_guard = asyncio.Lock()


async def _acquire_card_lock(card_id: int) -> asyncio.Lock | None:
    """Try to acquire a per-card generation lock. Returns None if already locked."""
    async with _lock_guard:
        lock = _card_locks.get(card_id)
        if lock and lock.locked():
            return None
        new_lock = asyncio.Lock()
        _card_locks[card_id] = new_lock
    await new_lock.acquire()
    return new_lock


def _release_card_lock(card_id: int, lock: asyncio.Lock) -> None:
    try:
        lock.release()
    except RuntimeError:
        pass


# ═══════════════════════════════════════════════════════════════
# Preview
# ═══════════════════════════════════════════════════════════════

async def generate_preview(
    db: AsyncSession,
    card: FormulaCard,
    spec_dict: dict,
    admin_id: int,
) -> dict:
    """Generate a preview image for a graph_spec.

    Steps:
    1. Acquire per-card lock (raises 429 if busy)
    2. Compute cache key; if same spec already has preview, return existing
    3. Set card.graph_status = "generating"
    4. Render in subprocess with quality check
    5. If quality errors → raise ValueError with details
    6. Save preview + thumbnail to storage
    7. Upsert FormulaGraphPreview
    8. Set card.draft_graph_spec = spec_dict, card.graph_status = "draft"
    9. Return preview data dict

    Returns dict with: preview_url, thumbnail_url, preview_token,
    checksum, width, height, mime_type, quality, expires_at.
    """
    lock = await _acquire_card_lock(card.id)
    if lock is None:
        raise ValueError("A generation task is already running for this card", "429")

    try:
        checksum = _spec_cache_key(spec_dict)

        # Check existing preview with same checksum
        existing_result = await db.execute(
            select(FormulaGraphPreview).where(
                FormulaGraphPreview.formula_card_id == card.id,
                FormulaGraphPreview.checksum == checksum,
                FormulaGraphPreview.expires_at > datetime.now(timezone.utc),
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return _preview_to_dict(existing)

        # Set generating status
        card.graph_status = "generating"
        card.draft_graph_spec = spec_dict
        card.graph_last_error = None
        await db.flush()

        # Render
        try:
            png_bytes, metadata, quality = await render_and_check(spec_dict)
        except TimeoutError as e:
            card.graph_status = "failed"
            card.graph_last_error = str(e)
            await db.flush()
            raise ValueError(str(e))
        except ValueError as e:
            card.graph_status = "failed"
            card.graph_last_error = str(e)
            await db.flush()
            raise

        if not quality["passed"]:
            # Save preview anyway for debugging, but surface errors
            error_msg = "; ".join(quality.get("errors", []))
            logger.warning("Quality check errors for card %d: %s", card.id, error_msg)

        # Save to storage
        storage = get_storage()
        main_path = _storage_path(card.id, "preview", checksum)
        thumb_path = _storage_path(card.id, "preview", checksum, "-thumb")

        # Resize to canvas dimensions
        png_final = _resize_to_canvas(png_bytes, GRAPH_THEME["width"], GRAPH_THEME["height"])
        thumb_bytes = _create_thumbnail(png_bytes)

        # Upload with compensation
        try:
            image_url = await storage.upload(main_path, png_final)
            thumbnail_url = await storage.upload(thumb_path, thumb_bytes)
        except Exception:
            card.graph_status = "failed"
            card.graph_last_error = "Storage upload failed"
            await db.flush()
            raise

        mime_type = "image/png"
        width = GRAPH_THEME["width"]
        height = GRAPH_THEME["height"]
        file_size = len(png_final)

        # Delete old preview record + files for this card
        old_result = await db.execute(
            select(FormulaGraphPreview).where(
                FormulaGraphPreview.formula_card_id == card.id
            )
        )
        old_preview = old_result.scalar_one_or_none()
        if old_preview:
            _safe_delete_preview_files(old_preview)
            await db.delete(old_preview)
            await db.flush()

        # Create new preview
        preview_token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=PREVIEW_TTL_MINUTES)

        preview = FormulaGraphPreview(
            formula_card_id=card.id,
            preview_token=preview_token,
            checksum=checksum,
            preview_url=image_url,
            thumbnail_url=thumbnail_url,
            width=width,
            height=height,
            mime_type=mime_type,
            file_size=file_size,
            renderer_version=RENDERER_VERSION,
            quality_errors=quality.get("errors", []),
            quality_warnings=quality.get("warnings", []),
            expires_at=expires_at,
        )
        db.add(preview)

        card.graph_status = "draft"
        await db.flush()

        return _preview_to_dict(preview, quality)

    finally:
        _release_card_lock(card.id, lock)


def _preview_to_dict(preview: FormulaGraphPreview, quality: dict | None = None) -> dict:
    return {
        "preview_url": preview.preview_url or "",
        "thumbnail_url": preview.thumbnail_url,
        "preview_token": preview.preview_token,
        "checksum": preview.checksum,
        "width": preview.width or 1600,
        "height": preview.height or 1000,
        "mime_type": preview.mime_type or "image/png",
        "quality": {
            "errors": preview.quality_errors or [],
            "warnings": preview.quality_warnings or [],
            "passed": len(preview.quality_errors or []) == 0,
        } if quality is None else quality,
        "expires_at": preview.expires_at.isoformat() if preview.expires_at else None,
    }


def _safe_delete_preview_files(preview: FormulaGraphPreview) -> None:
    """Best-effort delete preview files from storage."""
    from app.services.formula_graph_asset_service import _safe_delete_file
    if preview.preview_url:
        _safe_delete_file(preview.preview_url)
    if preview.thumbnail_url:
        _safe_delete_file(preview.thumbnail_url)


# ═══════════════════════════════════════════════════════════════
# Confirm
# ═══════════════════════════════════════════════════════════════

async def confirm_preview(
    db: AsyncSession,
    card: FormulaCard,
    preview_token: str,
    card_version: int,
    accept_warnings: bool,
    admin_id: int,
    alt_text: str | None = None,
    description: str | None = None,
) -> FormulaGraphAsset:
    """Promote a preview to an official generated asset.

    Validates preview_token, expiry, card_version, and quality warnings.
    Atomic transaction: creates asset, updates card, deletes preview.

    Returns the created FormulaGraphAsset.
    """
    # Verify card state
    if card.graph_status != "draft":
        raise ValueError(f"Card status must be 'draft', got '{card.graph_status}'", "422")

    if card.version != card_version:
        raise ValueError(
            f"Card version mismatch: expected {card_version}, current {card.version}. "
            "The formula has been modified since preview. Regenerate preview.",
            "409",
        )

    # Load preview
    result = await db.execute(
        select(FormulaGraphPreview).where(
            FormulaGraphPreview.preview_token == preview_token,
            FormulaGraphPreview.formula_card_id == card.id,
        )
    )
    preview = result.scalar_one_or_none()
    if not preview:
        raise ValueError("Preview not found or token invalid", "404")

    if preview.expires_at and preview.expires_at < datetime.now(timezone.utc):
        raise ValueError("Preview has expired. Please regenerate.", "422")

    # Check quality
    errors = preview.quality_errors or []
    warnings = preview.quality_warnings or []
    if errors:
        raise ValueError(
            f"Cannot confirm: quality errors remain: {'; '.join(errors)}", "422"
        )
    if warnings and not accept_warnings:
        raise ValueError(
            f"Quality warnings present; set accept_warnings=true to confirm: "
            f"{'; '.join(warnings)}", "422"
        )

    # Atomic confirm
    try:
        # 1. Delete old generated asset if exists
        old_result = await db.execute(
            select(FormulaGraphAsset).where(
                FormulaGraphAsset.formula_card_id == card.id,
                FormulaGraphAsset.source_type == "generated",
            )
        )
        old_asset = old_result.scalar_one_or_none()
        old_image_url = None
        old_thumbnail_url = None
        if old_asset:
            old_image_url = old_asset.image_url
            old_thumbnail_url = old_asset.thumbnail_url
            await db.delete(old_asset)
            await db.flush()

        # 2. Copy preview files to generated paths
        checksum = preview.checksum
        storage = get_storage()
        main_path = _storage_path(card.id, "generated", checksum)
        thumb_path = _storage_path(card.id, "generated", checksum, "-thumb")

        # Read preview files (runs in thread to avoid blocking)
        preview_data = await _read_local_file(preview.preview_url)
        thumb_data = await _read_local_file(preview.thumbnail_url)

        new_image_url = await storage.upload(main_path, preview_data) if preview_data else (preview.preview_url or "")
        new_thumbnail_url = await storage.upload(thumb_path, thumb_data) if thumb_data else (preview.thumbnail_url or "")

        # 3. Create new generated asset
        now = datetime.now(timezone.utc)
        asset = FormulaGraphAsset(
            formula_card_id=card.id,
            source_type="generated",
            image_url=new_image_url,
            thumbnail_url=new_thumbnail_url,
            mime_type=preview.mime_type or "image/png",
            width=preview.width,
            height=preview.height,
            file_size=preview.file_size,
            checksum=checksum,
            renderer_version=RENDERER_VERSION,
            reviewed_by=admin_id,
            reviewed_at=now,
            published_version=card.version,
        )

        # Auto-generate alt_text and description (allow overrides)
        asset.alt_text = alt_text if alt_text is not None else _auto_alt_text(card, preview)
        asset.description = description if description is not None else _auto_description(card, preview)

        db.add(asset)

        # 4. Update card
        card.graph_spec = card.draft_graph_spec
        card.draft_graph_spec = None
        card.graph_status = "ready"
        card.graph_last_error = None
        card.graph_generated_at = now
        card.graph_confirmed_at = now

        # 5. Delete preview record
        preview_url_old = preview.preview_url
        thumb_url_old = preview.thumbnail_url
        await db.delete(preview)
        await db.flush()

        # 6. Delete old files (best-effort, after successful flush)
        if old_image_url:
            _safe_delete_file_later(old_image_url)
        if old_thumbnail_url:
            _safe_delete_file_later(old_thumbnail_url)
        _safe_delete_file_later(preview_url_old)
        _safe_delete_file_later(thumb_url_old)

        return asset

    except Exception:
        raise


async def _read_local_file(file_url: str | None) -> bytes | None:
    """Read a local storage file by URL. Returns None if not found."""
    if not file_url:
        return None
    prefix = f"{settings.PUBLIC_BASE_URL}/static/formulas/"
    if not file_url.startswith(prefix):
        return None
    rel_path = file_url[len(prefix):]
    abs_path = os.path.normpath(os.path.join("static/formulas", rel_path))
    if not abs_path.startswith(os.path.normpath("static/formulas/")):
        return None

    def _read():
        if not os.path.exists(abs_path):
            return None
        with open(abs_path, "rb") as f:
            return f.read()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read)


def _safe_delete_file_later(file_url: str | None) -> None:
    """Best-effort async file deletion (fire-and-forget)."""
    if not file_url:
        return
    from app.services.formula_graph_asset_service import _safe_delete_file
    try:
        _safe_delete_file(file_url)
    except Exception:
        logger.warning("Failed to delete file: %s", file_url, exc_info=True)


def _auto_alt_text(card: FormulaCard, preview: FormulaGraphPreview) -> str:
    """Auto-generate alt text from card title and spec."""
    title = card.title or ""
    return f"{title} 函数图像" if title else "函数图像"


def _auto_description(card: FormulaCard, preview: FormulaGraphPreview) -> str | None:
    """Auto-generate longer description from spec."""
    spec = card.draft_graph_spec or {}
    panels = spec.get("panels", [])
    parts = [f"公式: {card.title}"]
    for i, panel in enumerate(panels):
        exprs = [e.get("expression", "") for e in panel.get("expressions", [])]
        if exprs:
            parts.append(f"面板{i+1}: {', '.join(exprs)}")
    return " | ".join(parts) if parts else None


# ═══════════════════════════════════════════════════════════════
# Regenerate
# ═══════════════════════════════════════════════════════════════

async def regenerate_asset(
    db: AsyncSession,
    card: FormulaCard,
    spec_dict: dict | None,
    admin_id: int,
) -> FormulaGraphAsset:
    """Regenerate and replace the official generated asset."""
    if spec_dict:
        spec = spec_dict
    elif card.graph_spec:
        spec = card.graph_spec
    else:
        raise ValueError("No graph_spec available for regeneration", "422")

    # Generate preview first, then confirm
    preview_data = await generate_preview(db, card, spec, admin_id)
    card_version = card.version  # capture before potential flush changes

    asset = await confirm_preview(
        db, card, preview_data["preview_token"],
        card_version=card_version,
        accept_warnings=True,
        admin_id=admin_id,
    )
    return asset


# ═══════════════════════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════════════════════

async def delete_generated_asset(
    db: AsyncSession,
    card: FormulaCard,
) -> bool:
    """Delete the generated asset (record + files). Does NOT clear graph_spec."""
    result = await db.execute(
        select(FormulaGraphAsset).where(
            FormulaGraphAsset.formula_card_id == card.id,
            FormulaGraphAsset.source_type == "generated",
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        return False

    image_url = asset.image_url
    thumbnail_url = asset.thumbnail_url

    await db.delete(asset)
    await db.flush()

    # Update card status
    if card.graph_spec:
        card.graph_status = "missing"
    else:
        card.graph_status = "unconfigured"

    # Best-effort delete files
    _safe_delete_file_later(image_url)
    _safe_delete_file_later(thumbnail_url)

    return True


# ═══════════════════════════════════════════════════════════════
# Batch
# ═══════════════════════════════════════════════════════════════

_batch_jobs: dict[str, dict] = {}
_batch_lock = asyncio.Lock()


async def start_batch_generate(
    db: AsyncSession,
    admin_id: int,
    batch_size: int = BATCH_MAX_SIZE,
) -> str:
    """Start batch generation for missing/failed cards. Returns job_id."""
    # Check for running batch
    async with _batch_lock:
        for jid, job in list(_batch_jobs.items()):
            if job.get("status") == "running":
                raise ValueError("A batch generation job is already running", "429")

    # Query cards
    result = await db.execute(
        select(FormulaCard).where(
            FormulaCard.graph_spec.isnot(None),
            FormulaCard.graph_status.in_(["missing", "failed"]),
            FormulaCard.deleted_at.is_(None),
        ).limit(batch_size)
    )
    cards = list(result.scalars().all())

    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": "running",
        "progress": 0.0,
        "total": len(cards),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    _batch_jobs[job_id] = job

    # Launch background processing
    asyncio.create_task(_process_batch(job_id, cards, admin_id))

    return job_id


async def get_batch_status(job_id: str) -> dict | None:
    """Get batch job status. Returns None if job not found."""
    return _batch_jobs.get(job_id)


async def _process_batch(job_id: str, cards: list[FormulaCard], admin_id: int) -> None:
    """Process batch cards sequentially with per-card timeout and retry."""
    job = _batch_jobs.get(job_id)
    if not job:
        return

    from app.core.database import async_session

    for idx, card in enumerate(cards):
        try:
            # Create a new DB session for each card
            async with async_session() as session:
                async with session.begin():
                    # Reload card in this session
                    card_reload = await session.get(FormulaCard, card.id)
                    if not card_reload or card_reload.deleted_at:
                        job["skipped"] += 1
                        continue
                    if card_reload.graph_status not in ("missing", "failed"):
                        job["skipped"] += 1
                        continue

                    spec = card_reload.graph_spec
                    if not spec:
                        job["skipped"] += 1
                        continue

                    retries = 0
                    last_error = None
                    while retries <= MAX_RETRIES:
                        try:
                            preview = await generate_preview(
                                session, card_reload, spec, admin_id,
                            )
                            await confirm_preview(
                                session, card_reload,
                                preview["preview_token"],
                                card_version=card_reload.version,
                                accept_warnings=True,
                                admin_id=admin_id,
                            )
                            job["succeeded"] += 1
                            break
                        except ValueError as e:
                            retries += 1
                            last_error = str(e)
                            if retries > MAX_RETRIES:
                                raise
                            await asyncio.sleep(1)

        except Exception as e:
            job["failed"] += 1
            job["errors"].append({
                "card_id": card.id,
                "title": card.title,
                "error": str(e)[:200],
            })
            logger.warning("Batch card %d failed after %d retries: %s",
                           card.id, MAX_RETRIES, e)

        job["processed"] += 1
        job["progress"] = (idx + 1) / len(cards) if cards else 1.0

    # Determine final status
    if job["succeeded"] > 0 and job["failed"] == 0:
        job["status"] = "completed"
    elif job["succeeded"] > 0 and job["failed"] > 0:
        job["status"] = "partial_failed"
    elif job["failed"] > 0:
        job["status"] = "failed"
    else:
        job["status"] = "completed"
    job["finished_at"] = datetime.now(timezone.utc).isoformat()

    # Cleanup old jobs (keep last 10)
    _cleanup_old_jobs()


def _cleanup_old_jobs(max_keep: int = 10) -> None:
    """Remove oldest completed jobs beyond max_keep."""
    completed = [(jid, j) for jid, j in _batch_jobs.items()
                 if j.get("status") in ("completed", "partial_failed", "failed")]
    if len(completed) > max_keep:
        completed.sort(key=lambda x: x[1].get("finished_at", ""))
        for jid, _ in completed[:len(completed) - max_keep]:
            _batch_jobs.pop(jid, None)
