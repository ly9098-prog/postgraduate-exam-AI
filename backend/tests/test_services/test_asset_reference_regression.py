"""Regression checks for fail-closed asset scans and transaction isolation."""

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.asset_reference_service import AssetReferenceService


@pytest.mark.asyncio
async def test_failed_reference_scan_isolated_from_followup_queries():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with async_sessionmaker(engine)() as db:
            nested_transactions = []
            event.listen(
                db.sync_session,
                "after_transaction_create",
                lambda _session, transaction: nested_transactions.append(
                    transaction.nested
                ),
            )
            # Missing scan tables force database exceptions, not only Python exceptions.
            report = await AssetReferenceService(db).resolve(
                "question-assets/missing.png"
            )
            assert report.errors
            assert not report.safe_to_delete
            assert sum(nested_transactions) == 8  # 3 question + 4 import + 1 revision
            assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pinned_revision_query_casts_json_and_does_not_distinct_it():
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
    await AssetReferenceService(db)._scan_pinned_question_versions(
        "question-assets/920/pinned.png"
    )
    statement = str(db.execute.call_args.args[0])
    assert "SELECT DISTINCT" not in statement
    assert "COALESCE(qv.image_url, '')" not in statement
    for column in ("content", "image_url", "options"):
        assert f"CAST(qv.{column} AS TEXT) LIKE :needle" in statement
