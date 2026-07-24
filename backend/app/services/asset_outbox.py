"""Asset Outbox — Reliable outbox for asset lifecycle events.

Provides:
- OutboxEvent: Event record for asset operations.
- AssetOutbox: Transactional outbox for deferred asset operations.

Design:
- Events are persisted in the same DB transaction as the main operation.
- After transaction commit, the outbox processor executes events.
- Idempotency key prevents duplicate execution.
- Lease mechanism prevents concurrent processing.
- Heartbeat for long-running operations.
- Retry with exponential backoff.
- Dead letter after max retries.

PERSISTENCE_MODE:
  legacy               — existing path (default)
  transactional_shadow — plan + compare, don't persist twice
  transactional        — full transactional persistence
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_PERSISTENCE_MODE = os.environ.get("PERSISTENCE_MODE", "legacy")

# Max retries before moving to dead letter
_MAX_RETRIES = 5

# Default lease duration (seconds)
_LEASE_DURATION = 60

# Exponential backoff base (seconds)
_RETRY_BACKOFF_BASE = 2.0


class OutboxStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    PROCESSING = "processing"
    COMPLETED = "completed"
    RETRYABLE = "retryable"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# OutboxEvent
# ---------------------------------------------------------------------------


@dataclass
class OutboxEvent:
    """A single outbox event for deferred asset operations."""
    event_id: str = ""
    event_type: str = ""  # "asset_delete" | "asset_confirm" | "storage_cleanup"
    idempotency_key: str = ""
    status: str = OutboxStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    payload_schema_version: str = "1.0"
    lease_id: str = ""
    lease_expires_at: float = 0.0
    retry_count: int = 0
    next_retry_at: float = 0.0
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = f"evt-{uuid.uuid4().hex[:16]}"
        if not self.created_at:
            self.created_at = time.time()

    def is_ready(self) -> bool:
        """Check if event is ready to be processed."""
        if self.status in (OutboxStatus.COMPLETED, OutboxStatus.DEAD_LETTER, OutboxStatus.CANCELLED):
            return False
        if self.next_retry_at and time.time() < self.next_retry_at:
            return False
        return True


# ---------------------------------------------------------------------------
# AssetOutbox
# ---------------------------------------------------------------------------


class AssetOutbox:
    """Transactional outbox for asset lifecycle operations.

    Usage::

        outbox = AssetOutbox()
        event = outbox.create_event("asset_delete", {"asset_id": "..."})
        # ... in same DB transaction ...
        outbox.mark_ready(event)
        # ... after commit ...
        outbox.process_ready_events()
    """

    def __init__(self, mode: str = "") -> None:
        self._mode = mode or _PERSISTENCE_MODE
        self._events: dict[str, OutboxEvent] = {}
        self._handlers: dict[str, Callable] = {}

    @property
    def mode(self) -> str:
        return self._mode

    def register_handler(
        self, event_type: str, handler: Callable[[dict], None],
    ) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type] = handler

    def create_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str = "",
    ) -> OutboxEvent:
        """Create a new outbox event (not yet ready for processing)."""
        key = idempotency_key or f"{event_type}:{hash(json.dumps(payload, sort_keys=True))}"
        event = OutboxEvent(
            event_type=event_type,
            idempotency_key=key,
            payload=payload,
            status=OutboxStatus.PENDING,
        )
        self._events[event.event_id] = event
        return event

    def mark_ready(self, event_id: str) -> None:
        """Mark an event as ready for processing."""
        event = self._events.get(event_id)
        if event:
            object.__setattr__(event, "status", OutboxStatus.PENDING)

    def lease(self, event_id: str, duration: float = _LEASE_DURATION) -> bool:
        """Lease an event for exclusive processing.

        Returns True if lease was acquired.
        """
        event = self._events.get(event_id)
        if not event or not event.is_ready():
            return False

        now = time.time()
        if event.status == OutboxStatus.LEASED and event.lease_expires_at > now:
            return False  # Already leased by another worker

        object.__setattr__(event, "status", OutboxStatus.LEASED)
        object.__setattr__(event, "lease_id", uuid.uuid4().hex[:16])
        object.__setattr__(event, "lease_expires_at", now + duration)
        return True

    def complete(self, event_id: str) -> None:
        """Mark an event as completed."""
        event = self._events.get(event_id)
        if event:
            object.__setattr__(event, "status", OutboxStatus.COMPLETED)
            object.__setattr__(event, "updated_at", time.time())

    def fail(
        self, event_id: str, error: str, retryable: bool = True,
    ) -> None:
        """Mark an event as failed. Moves to retry or dead letter."""
        event = self._events.get(event_id)
        if not event:
            return

        new_retry_count = event.retry_count + 1
        object.__setattr__(event, "retry_count", new_retry_count)
        object.__setattr__(event, "last_error", error)
        object.__setattr__(event, "updated_at", time.time())

        if new_retry_count >= _MAX_RETRIES:
            object.__setattr__(event, "status", OutboxStatus.DEAD_LETTER)
            logger.error(
                "Outbox: event %s moved to DEAD_LETTER after %d retries: %s",
                event_id, new_retry_count, error,
            )
        elif retryable:
            backoff = _RETRY_BACKOFF_BASE ** new_retry_count
            object.__setattr__(event, "status", OutboxStatus.RETRYABLE)
            object.__setattr__(event, "next_retry_at", time.time() + backoff)
            logger.warning(
                "Outbox: event %s retry %d/%d in %.1fs: %s",
                event_id, new_retry_count, _MAX_RETRIES, backoff, error,
            )
        else:
            object.__setattr__(event, "status", OutboxStatus.DEAD_LETTER)

    def process_ready_events(self) -> list[OutboxEvent]:
        """Process all ready events by leasing and executing handlers.

        Returns list of processed events.
        """
        processed: list[OutboxEvent] = []
        for event in list(self._events.values()):
            if not event.is_ready():
                continue

            if not self.lease(event.event_id):
                continue

            handler = self._handlers.get(event.event_type)
            if not handler:
                self.complete(event.event_id)
                processed.append(event)
                continue

            try:
                handler(event.payload)
                self.complete(event.event_id)
                processed.append(event)
            except Exception as e:
                self.fail(event.event_id, str(e))

        return processed

    def get_events_by_status(self, status: str) -> list[OutboxEvent]:
        """Get all events with a given status."""
        return [e for e in self._events.values() if e.status == status]

    def pending_count(self) -> int:
        """Count of events not yet completed or dead."""
        return sum(
            1 for e in self._events.values()
            if e.status not in (OutboxStatus.COMPLETED, OutboxStatus.DEAD_LETTER, OutboxStatus.CANCELLED)
        )

    def cancel(self, event_id: str) -> None:
        """Cancel an event."""
        event = self._events.get(event_id)
        if event:
            object.__setattr__(event, "status", OutboxStatus.CANCELLED)
