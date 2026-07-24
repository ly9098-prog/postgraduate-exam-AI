"""PostgreSQL integration tests — requires ``--run-integration``.

Verifies that the app's models work against a real PostgreSQL database.
"""

import pytest
from sqlalchemy import select, text


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestPostgresConnectivity:
    """Basic PG connectivity and CRUD."""

    @pytest.mark.asyncio
    async def test_engine_connects(self, pg_engine):
        async with pg_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 AS v"))
            row = result.one()
            assert row._mapping["v"] == 1

    @pytest.mark.asyncio
    async def test_version_string(self, pg_engine):
        async with pg_engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.one()
            version = row._mapping["version"]
            assert "PostgreSQL" in version

    @pytest.mark.asyncio
    async def test_create_and_query_user(self, pg_session):
        """Insert a User row and read it back."""
        from app.models.user import User

        user = User(
            openid="test_openid_001",
            username="testuser_pg",
            hashed_password="dummy_hash",
        )
        pg_session.add(user)
        await pg_session.commit()
        await pg_session.refresh(user)

        assert user.id is not None
        assert user.openid == "test_openid_001"

        result = await pg_session.execute(
            select(User).where(User.openid == "test_openid_001")
        )
        fetched = result.scalar_one()
        assert fetched.username == "testuser_pg"

    @pytest.mark.asyncio
    async def test_import_pipeline_crud(self, pg_session):
        """Create an ImportPipeline row, update status, read back."""
        from datetime import datetime
        from app.models.import_pipeline import ImportPipeline

        pipeline = ImportPipeline(
            pipeline_id="pl_integration_001",
            source_type="pdf",
            source_file="test_integration.pdf",
            status="processing",
            total_pages=10,
            created_at=datetime.utcnow(),
        )
        pg_session.add(pipeline)
        await pg_session.commit()

        pipeline.status = "completed"
        await pg_session.commit()

        result = await pg_session.execute(
            select(ImportPipeline).where(
                ImportPipeline.pipeline_id == "pl_integration_001"
            )
        )
        fetched = result.scalar_one()
        assert fetched.status == "completed"
        assert fetched.total_pages == 10

    @pytest.mark.asyncio
    async def test_question_import_crud(self, pg_session):
        """Create a QuestionImport row with JSON fields."""
        from datetime import datetime
        from app.models.question_import import QuestionImport

        qi = QuestionImport(
            batch_id="batch_integration_001",
            question_type="single_choice",
            stem="What is 1+1?",
            options={"A": "1", "B": "2", "C": "3"},
            answer="B",
            source_type="pdf",
            source_order=1,
            review_status="pending",
            created_at=datetime.utcnow(),
        )
        pg_session.add(qi)
        await pg_session.commit()
        await pg_session.refresh(qi)

        assert qi.id is not None
        assert qi.options["B"] == "2"

        result = await pg_session.execute(
            select(QuestionImport).where(
                QuestionImport.batch_id == "batch_integration_001"
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
