"""Review submission stage — submit questions to review queue.

Extracted from ``pipeline_orchestrator.py:_run_review`` (P5-2).
"""

from __future__ import annotations

import logging

from app.features.pipeline_stages._helpers import _log_multi_blank_stage
from app.features.review_service import submit_to_review

logger = logging.getLogger(__name__)


async def run_review_stage(
    questions: list[dict],
    *,
    source_file: str = "",
    source_type: str = "",
    subject: str | None = None,
    subject_id: int | None = None,
    pipeline_id: str = "",
    db=None,
) -> dict:
    """Submit questions to review queue.

    Returns:
        dict with ``batch_id``, ``written``, ``skipped``, ``total``, ``items``,
        ``review_new_hashes``, ``warnings``, ``review_commit`` keys.
    """
    if db is None:
        return {
            "batch_id": "",
            "written": 0,
            "skipped": 0,
            "total": len(questions),
            "warnings": ["no db session provided, review stage skipped"],
        }

    batch_meta = {
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject or "",
        "subject_id": subject_id,
        "pipeline_id": pipeline_id,
    }
    _log_multi_blank_stage("review_input", questions, source_type=source_type, source_file=source_file)
    result = await submit_to_review(db, questions, batch_meta, skip_existing=True)

    warnings: list[str] = []
    dup_filtered = result.get("duplicates_filtered", 0)
    if dup_filtered > 0:
        warnings.append(f"{dup_filtered} duplicates filtered (already in bank)")
    if result["skipped"] > 0:
        warnings.append(f"{result['skipped']} questions skipped in review")

    # Build new hashes for GlobalHashIndex
    items = result.get("items", [])
    question_subjects = [
        (q.get("subject") if isinstance(q, dict) else None) for q in questions
    ]
    new_hashes: list[tuple[str, str, int]] = []
    for idx, item in enumerate(items):
        qhash = item.get("question_hash")
        iid = item.get("id")
        if not qhash or not iid:
            continue
        qsubject = subject or (question_subjects[idx] if idx < len(question_subjects) else None) or ""
        if qsubject:
            new_hashes.append((qsubject, qhash, iid))

    logger.info(
        "【OCR-8】数据库入库结果 | batch=%s source=%s total=%d written=%d skipped=%d dup=%d",
        result["batch_id"], source_file,
        result["total"], result["written"], result["skipped"],
        result.get("duplicates_filtered", 0),
    )
    for idx, item in enumerate(items):
        q = questions[idx] if idx < len(questions) else {}
        opts = q.get("parsed_options") or q.get("options") or {}
        opt_count = len(opts) if isinstance(opts, (dict, list)) else 0
        logger.info(
            "  ▶ import_id=%s hash=%s status=%s type=%s options=%d conf=%.2f answer=%s",
            item.get("id", "?"), item.get("question_hash", "?")[:12],
            item.get("status", "?"), q.get("question_type", "?"),
            opt_count, q.get("confidence_score", 0),
            q.get("answer") or "❌",
        )

    return {
        "batch_id": result["batch_id"],
        "written": result["written"],
        "skipped": result["skipped"],
        "total": result["total"],
        "items": items,
        "review_new_hashes": new_hashes,
        "warnings": warnings,
        "review_commit": {
            "batch_size": 50,
            "total_questions": result["total"],
            "written": result["written"],
            "duplicates_filtered": dup_filtered,
            "pipeline_id": pipeline_id,
        },
    }
