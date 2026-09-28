"""PostgreSQL JSON reference scanning and rollback-to-savepoint regression."""

import pytest
from sqlalchemy import text

from app.services.asset_reference_service import AssetReferenceService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pinned_json_versions_and_failed_scan_keep_transaction_usable(pg_session):
    asset = "/static/question-assets/920/pinned.png"
    async with pg_session() as db:
        # Temporary tables keep test data independent of the application database.
        await db.execute(
            text(
                "CREATE TEMP TABLE questions (id integer, content json, image_url json, options json)"
            )
        )
        await db.execute(
            text(
                "CREATE TEMP TABLE question_imports (id integer, parsed_content json, raw_data json, parsed_options json, source_image_name text)"
            )
        )
        await db.execute(
            text(
                "CREATE TEMP TABLE question_versions (id integer PRIMARY KEY, content json, image_url json, options json)"
            )
        )
        for name in (
            "exam_paper_questions",
            "practice_records",
            "wrong_questions",
            "review_schedules",
            "review_records",
        ):
            await db.execute(
                text(f"CREATE TEMP TABLE {name} (question_version_id integer)")
            )
        await db.execute(
            text(
                "INSERT INTO question_versions VALUES (1, :content, :images, :options), (2, '{}', :images, NULL)"
            ),
            {
                "content": '{"image":"' + asset + '"}',
                "images": '["' + asset + '"]',
                "options": '{"A":"' + asset + '"}',
            },
        )
        await db.execute(text("INSERT INTO practice_records VALUES (1)"))
        service = AssetReferenceService(db)
        report = await service.resolve("question-assets/920/pinned.png")
        assert report.errors == []
        assert {ref.entity_id for ref in report.references} == {"1"}
        assert {ref.field_name for ref in report.references} == {
            "content",
            "image_url",
            "options",
        }
        assert not report.safe_to_delete

        # PostgreSQL normally aborts a transaction when a SELECT hits a missing
        # table. A failed reference scan must not break later work on this session.
        await db.execute(text("DROP TABLE question_imports"))
        report = await service.resolve("question-assets/920/pinned.png")
        assert report.errors
        assert {ref.entity_id for ref in report.references} == {"1"}
        assert not report.safe_to_delete
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
