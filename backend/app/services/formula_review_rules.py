"""Formula review transitions shared by single-card and batch administration."""

from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException

from app.core.time_utils import utcnow
from app.models.formula import FormulaCard

_VALID_TRANSITIONS = {
    "draft": ["restore", "approve"],
    "pending_review": ["approve", "reject"],
    "rejected": ["restore"],
    "approved": ["publish"],
    "published": ["offline"],
    "offline": ["publish"],
}

_NEW_STATUS_MAP = {
    ("draft", "approve"): "pending_review",
    ("pending_review", "approve"): "published",
    ("pending_review", "reject"): "rejected",
    ("rejected", "restore"): "draft",
    ("published", "offline"): "offline",
    ("offline", "publish"): "published",
    ("approved", "publish"): "published",
}


def _resolve_status(status: str, action: str) -> str:
    new_status = _NEW_STATUS_MAP.get((status, action))
    if new_status is not None:
        return new_status
    # Draft restore and historical data keep the original fallback mapping.
    return {
        "approve": "approved",
        "reject": "rejected",
        "publish": "published",
        "offline": "offline",
        "restore": "draft",
    }[action]


def _update_review_fields(
    card: FormulaCard,
    action: str,
    admin_id: int,
    now: datetime,
    rejection_reason: str | None,
) -> None:
    if action == "approve" and card.status == "published":
        card.reviewed_by = admin_id
        card.reviewed_at = now
        card.published_at = now
        card.rejection_reason = None
    elif action == "approve" and card.status == "pending_review":
        card.reviewed_by = None
        card.reviewed_at = None
        card.published_at = None
        card.rejection_reason = None
    elif action == "reject":
        card.reviewed_by = admin_id
        card.reviewed_at = now
        card.rejection_reason = rejection_reason
        card.published_at = None
    elif action == "publish":
        card.published_at = now
        card.reviewed_by = admin_id
        card.reviewed_at = now
    elif action in ("offline", "restore"):
        card.reviewed_by = None
        card.reviewed_at = None
        card.published_at = None


def apply_formula_action(
    card: FormulaCard,
    action: str,
    admin_id: int,
    now: datetime | None = None,
    rejection_reason: str | None = None,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> str:
    allowed = _VALID_TRANSITIONS.get(card.status, [])
    if action not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from {card.status} with action {action}. Allowed: {allowed}",
        )
    if now is None:
        now = clock()
    new_status = _resolve_status(card.status, action)
    if action == "reject":
        trimmed = (rejection_reason or "").strip()
        if not trimmed:
            raise HTTPException(status_code=422, detail="Rejection reason required")
        rejection_reason = trimmed
    card.status = new_status
    card.updated_by = admin_id
    card.version += 1
    _update_review_fields(card, action, admin_id, now, rejection_reason)
    return new_status
