"""Asset reference resolution and safe deletion.

Provides:
- AssetReference: identifies a single reference location for an asset URL
- AssetReferenceReport: aggregate report per storage key
- AssetReferenceService: scans all DB tables for references
- SafeDeleteStateMachine: states (planned→reference_checked→detached→...)
- AssetDeletionOutbox: transactional outbox for async deletion
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Asset URL patterns ────────────────────────────────────────────

# Matches URLs like /static/question-assets/202607/ds_sc/q_229_p229_option_group.png
_STATIC_ASSET_RE = re.compile(r"/static/question-assets/[^\s\"'<>]+")
_COS_ASSET_RE = re.compile(r"https://[^.]+\.cos\.[^/]+\.myqcloud\.com/[^\s\"'<>]+")


# ── Enums ──────────────────────────────────────────────────────────


class DeletionMode(Enum):
    DRY_RUN = "dry-run"
    DETACH_ONLY = "detach-only"
    DELETE_UNREFERENCED = "delete-unreferenced"


class DeletionState(Enum):
    PLANNED = "planned"
    REFERENCE_CHECKED = "reference_checked"
    DETACHED = "detached"
    GRACE_PERIOD = "grace_period"
    DELETING = "deleting"
    DELETED = "deleted"
    RETAINED = "retained"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── Data types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetReference:
    """A single reference to an asset in the database."""

    entity_type: str  # "question" | "question_import" | "pipeline_artifact" | ...
    entity_id: str  # primary key value
    field_name: str  # "content" | "parsed_content" | "source_snapshot_url" | ...
    json_path: str | None  # JSON path within the field, e.g. "segments[0].url"
    asset_url: str  # the URL as stored in the DB
    storage_key: str  # normalized key for file-system lookup


@dataclass
class AssetReferenceReport:
    """Aggregate report for one storage key."""

    storage_key: str
    references: list[AssetReference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def reference_count(self) -> int:
        return len(self.references)

    @property
    def safe_to_delete(self) -> bool:
        # Reference discovery is a safety gate. Any scan error means the
        # absence of references is unproven, so deletion must fail closed.
        return self.reference_count == 0 and not self.errors

    @property
    def reason_codes(self) -> list[str]:
        codes = []
        if self.reference_count > 0:
            types = {r.entity_type for r in self.references}
            codes.append(f"referenced_by_{self.reference_count}_entities")
            codes.append(f"entity_types:{','.join(sorted(types))}")
        if self.errors:
            codes.append(f"errors:{len(self.errors)}")
        return codes


# ── Storage key helpers ───────────────────────────────────────────


def url_to_storage_key(url: str) -> str:
    """Convert an asset URL to a normalized storage key.

    Examples:
        /static/question-assets/202607/ds_sc/q_229.png
            → question-assets/202607/ds_sc/q_229.png
        https://bucket.cos.region.myqcloud.com/static/question-assets/...
            → question-assets/...
    """
    # Strip public base URL
    if "/static/" in url:
        key = url.split("/static/", 1)[1]
    elif ".myqcloud.com/" in url:
        key = url.split(".myqcloud.com/", 1)[1]
    else:
        key = url
    return key.lstrip("/")


def extract_asset_urls(obj: Any, field_name: str = "") -> list[dict]:
    """Recursively extract all asset URLs from a JSON-like structure.

    Returns list of {url, field_name, json_path}.
    """
    results: list[dict] = []

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, str) and _STATIC_ASSET_RE.search(value):
            for m in _STATIC_ASSET_RE.finditer(value):
                results.append({"url": m.group(0), "json_path": path})
        elif isinstance(value, str) and _COS_ASSET_RE.search(value):
            for m in _COS_ASSET_RE.finditer(value):
                results.append({"url": m.group(0), "json_path": path})
        elif isinstance(value, dict):
            for k, v in value.items():
                _walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _walk(item, f"{path}[{i}]")

    _walk(obj, field_name)
    return results


# ── Asset Reference Service ────────────────────────────────────────


class AssetReferenceService:
    """Scans all DB tables for asset URL references.

    Must check at minimum:
      - questions.content
      - question_imports.parsed_content
      - question_imports.raw_data
      - question_imports.parsed_options
      - review records
      - pipeline artifacts
      - image_url fields
      - source_image_name fields

    Historical question versions are retained only when another durable learning
    fact actually pins them (exam paper item, practice record, wrong question or
    review fact). This protects historical exam/practice rendering without making
    every superseded draft revision keep its assets forever.
    """

    # Tables and columns to scan for asset URLs
    _SCAN_TARGETS: list[dict] = [
        # entity_type, table, columns, id_column
        {
            "type": "question",
            "table": "questions",
            "columns": ["content", "image_url", "options"],
            "id_col": "id",
        },
        {
            "type": "question_import",
            "table": "question_imports",
            "columns": [
                "parsed_content",
                "raw_data",
                "parsed_options",
                "source_image_name",
            ],
            "id_col": "id",
        },
    ]

    def __init__(self, db: AsyncSession):
        self._db = db

    async def resolve(self, storage_key: str) -> AssetReferenceReport:
        """Resolve all DB references for a storage key.

        Scans all configured tables/columns for URLs that resolve to
        the given storage key.
        """
        report = AssetReferenceReport(storage_key=storage_key)

        for target in self._SCAN_TARGETS:
            entity_type = target["type"]
            table = target["table"]
            columns = target["columns"]
            id_col = target["id_col"]

            for col in columns:
                try:
                    refs = await self._scan_column(
                        entity_type,
                        table,
                        col,
                        id_col,
                        storage_key,
                    )
                    report.references.extend(refs)
                except Exception as e:
                    report.errors.append(f"scan {table}.{col}: {e}")

        try:
            report.references.extend(
                await self._scan_pinned_question_versions(storage_key)
            )
        except Exception as e:
            # Reference-resolution errors are fail-safe: callers see errors and
            # the deletion state machine must not treat the asset as proven safe.
            report.errors.append(f"scan pinned question_versions: {e}")

        return report

    async def _scan_column(
        self,
        entity_type: str,
        table: str,
        column: str,
        id_col: str,
        target_key: str,
    ) -> list[AssetReference]:
        """Scan a single column for asset references to the target key."""
        references: list[AssetReference] = []
        raw = await self._db.execute(
            text(f"SELECT {id_col}, {column} FROM {table} WHERE {column} IS NOT NULL")
        )
        rows = raw.fetchall()

        for row in rows:
            entity_id = str(row[0])
            value = row[1]

            if isinstance(value, str):
                # Direct URL or JSON text. Both local/static and COS URLs are
                # valid persisted references; missing either family can make a
                # referenced object look orphaned during cleanup.
                urls = _STATIC_ASSET_RE.findall(value) + _COS_ASSET_RE.findall(value)
                for url in dict.fromkeys(urls):
                    if target_key in url or target_key in url_to_storage_key(url):
                        references.append(
                            AssetReference(
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field_name=column,
                                json_path=None,
                                asset_url=url,
                                storage_key=url_to_storage_key(url),
                            )
                        )
                # ``source_image_name`` can be a storage key/path rather than a
                # full URL. The generic URL regex branch above would otherwise
                # never see it because this value is still a string.
                if column == "source_image_name" and not urls:
                    candidate_key = url_to_storage_key(value)
                    if target_key in value or target_key in candidate_key:
                        references.append(
                            AssetReference(
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field_name=column,
                                json_path=None,
                                asset_url=value,
                                storage_key=candidate_key,
                            )
                        )
            elif isinstance(value, (dict, list)):
                # Structured JSON
                extracted = extract_asset_urls(value, column)
                for ex in extracted:
                    url = ex["url"]
                    if target_key in url or target_key in url_to_storage_key(url):
                        references.append(
                            AssetReference(
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field_name=column,
                                json_path=ex.get("json_path"),
                                asset_url=url,
                                storage_key=url_to_storage_key(url),
                            )
                        )

        return references

    async def _scan_pinned_question_versions(
        self, target_key: str
    ) -> list[AssetReference]:
        """Find asset refs in immutable revisions that still back durable facts.

        A superseded revision with no downstream reference may be cleaned up, but
        a revision used by a published/draft exam, historical practice, wrong-book
        entry or review record must keep its media so its frozen semantics remain
        renderable after the current Question is edited.
        """
        raw = await self._db.execute(
            text("""
            SELECT DISTINCT qv.id, qv.content, qv.image_url, qv.options
            FROM question_versions AS qv
            WHERE (
                EXISTS (
                    SELECT 1 FROM exam_paper_questions AS epq
                    WHERE epq.question_version_id = qv.id
                )
                OR EXISTS (
                    SELECT 1 FROM practice_records AS pr
                    WHERE pr.question_version_id = qv.id
                )
                OR EXISTS (
                    SELECT 1 FROM wrong_questions AS wq
                    WHERE wq.question_version_id = qv.id
                )
                OR EXISTS (
                    SELECT 1 FROM review_schedules AS rs
                    WHERE rs.question_version_id = qv.id
                )
                OR EXISTS (
                    SELECT 1 FROM review_records AS rr
                    WHERE rr.question_version_id = qv.id
                )
            )
            AND (
                CAST(qv.content AS TEXT) LIKE :needle
                OR COALESCE(qv.image_url, '') LIKE :needle
                OR CAST(qv.options AS TEXT) LIKE :needle
            )
        """),
            {"needle": f"%{target_key}%"},
        )
        references: list[AssetReference] = []
        for revision_id, content, image_url, options in raw.fetchall():
            for field_name, value in (
                ("content", content),
                ("image_url", image_url),
                ("options", options),
            ):
                if value is None:
                    continue
                if isinstance(value, str):
                    urls = _STATIC_ASSET_RE.findall(value) + _COS_ASSET_RE.findall(
                        value
                    )
                    for url in urls:
                        key = url_to_storage_key(url)
                        if target_key in url or target_key in key:
                            references.append(
                                AssetReference(
                                    entity_type="question_version",
                                    entity_id=str(revision_id),
                                    field_name=field_name,
                                    json_path=None,
                                    asset_url=url,
                                    storage_key=key,
                                )
                            )
                elif isinstance(value, (dict, list)):
                    for extracted in extract_asset_urls(value, field_name):
                        url = extracted["url"]
                        key = url_to_storage_key(url)
                        if target_key in url or target_key in key:
                            references.append(
                                AssetReference(
                                    entity_type="question_version",
                                    entity_id=str(revision_id),
                                    field_name=field_name,
                                    json_path=extracted.get("json_path"),
                                    asset_url=url,
                                    storage_key=key,
                                )
                            )
        return references

    async def resolve_all(
        self, storage_keys: list[str]
    ) -> dict[str, AssetReferenceReport]:
        """Resolve references for multiple storage keys at once."""
        results = {}
        for key in storage_keys:
            results[key] = await self.resolve(key)
        return results


# ── Deletion Outbox ───────────────────────────────────────────────


@dataclass
class DeletionOutboxEntry:
    """A record in the asset deletion outbox.

    Created inside the DB transaction, processed after commit.
    """

    outbox_id: str
    storage_key: str
    request_id: str
    mode: str
    state: str
    reference_count_before: int
    created_at: str
    processed_at: str | None = None
    result: str | None = None
    error: str | None = None


# ── Safe Delete State Machine ──────────────────────────────────────


class SafeDeleteMachine:
    """Finite state machine for safe asset deletion.

    States:
      planned → reference_checked → detached → grace_period → deleting → deleted
                                                                     → failed
                                                                     → retained
                                                                     → cancelled

    Rules:
      - Unknown reference count: must not delete
      - reference_count > 0: must not delete
      - DB transaction committed before file deletion
      - Deletion failure does not set 'deleted'
    """

    VALID_TRANSITIONS: dict[DeletionState, set[DeletionState]] = {
        DeletionState.PLANNED: {
            DeletionState.REFERENCE_CHECKED,
            DeletionState.CANCELLED,
        },
        DeletionState.REFERENCE_CHECKED: {
            DeletionState.DETACHED,
            DeletionState.RETAINED,
            DeletionState.CANCELLED,
        },
        DeletionState.DETACHED: {
            DeletionState.GRACE_PERIOD,
            DeletionState.RETAINED,
            DeletionState.CANCELLED,
        },
        DeletionState.GRACE_PERIOD: {
            DeletionState.DELETING,
            DeletionState.RETAINED,
            DeletionState.CANCELLED,
        },
        DeletionState.DELETING: {
            DeletionState.DELETED,
            DeletionState.FAILED,
        },
        DeletionState.DELETED: set(),
        DeletionState.RETAINED: set(),
        DeletionState.FAILED: {DeletionState.PLANNED, DeletionState.CANCELLED},
        DeletionState.CANCELLED: set(),
    }

    def __init__(self, initial: DeletionState = DeletionState.PLANNED):
        self._state = initial

    @property
    def state(self) -> DeletionState:
        return self._state

    def transition(self, target: DeletionState) -> None:
        if target not in self.VALID_TRANSITIONS.get(self._state, set()):
            raise ValueError(
                f"Invalid transition: {self._state.value} → {target.value}"
            )
        self._state = target
