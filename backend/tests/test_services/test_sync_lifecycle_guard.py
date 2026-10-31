"""sync:write 不得绕过审核流转：生命周期字段仅在 allow_lifecycle 时生效。"""
import asyncio
import tempfile
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.question import Question


@dataclass
class _Db:
    session_factory: sessionmaker


@pytest.fixture()
def db():
    f = tempfile.NamedTemporaryFile(prefix="sync_lifecycle_", suffix=".db", delete=False)
    f.close()

    import app.models  # noqa: F401
    from app.core.database import Base

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{f.name}", connect_args={"check_same_thread": False}
    )

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return _Db(sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


def _pkg(uuid: str, **extra) -> dict:
    q = {
        "sync_uuid": uuid,
        "subject_id": 1,
        "question_type": "single_choice",
        "content": {"text": "q"},
        "answer": "A",
        "question_hash": "h" + uuid,
        "updated_at": "2026-08-02T00:00:00",
        "review_status": "approved",
        "is_active": True,
    }
    q.update(extra)
    return {"tags": [], "questions": [q]}


@pytest.mark.asyncio
async def test_new_question_without_lifecycle_permission_is_re_pending_inactive(db):
    from app.features.sync_merge_service import merge_sync_package

    async with db.session_factory() as s:
        await merge_sync_package(s, _pkg("lc-new"))
        await s.commit()
        q = (await s.execute(select(Question).where(Question.sync_uuid == "lc-new"))).scalar_one()
        assert q.review_status == "re_pending"
        assert q.is_active is False


@pytest.mark.asyncio
async def test_update_preserves_lifecycle_state_without_permission(db):
    from app.features.sync_merge_service import merge_sync_package

    async with db.session_factory() as s:
        from datetime import datetime

        s.add(Question(subject_id=1, question_type="single_choice", content={"text": "old"},
                       answer="A", question_hash="hlc-upd", sync_uuid="lc-upd",
                       review_status="rejected", is_active=False,
                       updated_at=datetime(2026, 8, 1)))
        await s.commit()
        await merge_sync_package(s, _pkg("lc-upd", updated_at="2026-08-03T00:00:00"))
        await s.commit()
        q = (await s.execute(select(Question).where(Question.sync_uuid == "lc-upd"))).scalar_one()
        assert q.review_status == "rejected"
        assert q.is_active is False


@pytest.mark.asyncio
async def test_lifecycle_applies_with_permission_for_new_rows(db):
    from app.features.sync_merge_service import merge_sync_package

    async with db.session_factory() as s:
        await merge_sync_package(s, _pkg("lc-perm"), allow_lifecycle=True)
        await s.commit()
        q = (await s.execute(select(Question).where(Question.sync_uuid == "lc-perm"))).scalar_one()
        assert q.review_status == "approved"
        assert q.is_active is True


@pytest.mark.asyncio
async def test_permission_cannot_force_disallowed_transition(db):
    from datetime import datetime

    from app.features.sync_merge_service import merge_sync_package

    async with db.session_factory() as s:
        s.add(Question(subject_id=1, question_type="single_choice", content={"text": "old"},
                       answer="A", question_hash="hlc-t", sync_uuid="lc-t",
                       review_status="approved", is_active=True,
                       updated_at=datetime(2026, 8, 1)))
        await s.commit()
        await merge_sync_package(
            s, _pkg("lc-t", review_status="re_pending", updated_at="2026-08-03T00:00:00"),
            allow_lifecycle=True,
        )
        await s.commit()
        q = (await s.execute(select(Question).where(Question.sync_uuid == "lc-t"))).scalar_one()
        assert q.review_status == "approved"
