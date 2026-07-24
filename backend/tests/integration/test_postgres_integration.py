"""PostgreSQL integration tests — requires ``--run-integration``.

Verifies that the app's models work against a real PostgreSQL database.
Tests create async sessions inline from the sessionmaker fixture to avoid
pytest-asyncio 1.3.0 "attached to a different loop" error.

Each test uses a unique UUID in test data to avoid cross-test contamination.
"""

import uuid

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

        uid = uuid.uuid4().hex[:12]

        async with pg_session() as session:
            user = User(
                openid=f"test_openid_{uid}",
                nickname="testuser_pg",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            assert user.id is not None
            assert user.openid == f"test_openid_{uid}"

            result = await session.execute(
                select(User).where(User.openid == f"test_openid_{uid}")
            )
            fetched = result.scalar_one()
            assert fetched.nickname == "testuser_pg"

    @pytest.mark.asyncio
    async def test_import_pipeline_crud(self, pg_session):
        """Create an ImportPipeline row, update status, read back."""
        from app.models.import_pipeline import ImportPipeline

        pid = f"pl_int_{uuid.uuid4().hex[:8]}"

        async with pg_session() as session:
            pipeline = ImportPipeline(
                pipeline_id=pid,
                source_type="pdf",
                source_file="test_integration.pdf",
                status="running",
                total_pages=10,
            )
            session.add(pipeline)
            await session.commit()

            pipeline.status = "completed"
            await session.commit()

            result = await session.execute(
                select(ImportPipeline).where(ImportPipeline.pipeline_id == pid)
            )
            fetched = result.scalar_one()
            assert fetched.status == "completed"
            assert fetched.total_pages == 10

    @pytest.mark.asyncio
    async def test_question_import_crud(self, pg_session):
        """Create a QuestionImport row with JSON fields."""
        from app.models.question_import import QuestionImport

        bid = f"batch_int_{uuid.uuid4().hex[:8]}"

        async with pg_session() as session:
            qi = QuestionImport(
                batch_id=bid,
                question_type="single_choice",
                source_type="pdf",
                raw_data={"stem": "What is 1+1?"},
                parsed_options={"A": "1", "B": "2", "C": "3"},
                parsed_answer="B",
                status="pending",
                source_order_index=1,
            )
            session.add(qi)
            await session.commit()
            await session.refresh(qi)

            assert qi.id is not None
            assert qi.parsed_options["B"] == "2"

            result = await session.execute(
                select(QuestionImport).where(QuestionImport.batch_id == bid)
            )
            rows = result.scalars().all()
            assert len(rows) == 1
