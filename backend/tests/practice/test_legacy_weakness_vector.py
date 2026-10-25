"""Compatibility contract for the retained legacy weakness-vector strategy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import true

from app.services.practice.legacy_weakness_vector import (
    LegacyWeaknessRequest,
    run_legacy_weakness_vector,
)


def request(**overrides):
    defaults = dict(
        db=MagicMock(),
        user_id=9,
        subject_code="ds",
        count=3,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=True,
        subject_ids=[2],
        skip_finalize=True,
        request_id="request-1",
        experiment_id=7,
        variant_key="a",
        logger=MagicMock(),
        load_mastery=AsyncMock(return_value=[{"name": "队列"}]),
        compute_weak_kps=AsyncMock(),
        load_random=AsyncMock(),
        vector_recall=AsyncMock(return_value=[]),
        load_strategy_config=AsyncMock(return_value=None),
        rerank=AsyncMock(
            side_effect=lambda _db, _uid, qs, meta, _cfg, _kps: (qs, meta)
        ),
        build_excluded=lambda **_kwargs: None,
        revision_condition=lambda _scope: true(),
        kp_any_condition=lambda _names: true(),
        random_sample=lambda query, total, limit, order: (query, total, limit, order),
        finalize=AsyncMock(side_effect=lambda qs, meta, *_args, **_kwargs: (qs, meta)),
    )
    defaults.update(overrides)
    return LegacyWeaknessRequest(**defaults)


def question(question_id: int):
    return SimpleNamespace(id=question_id)


@pytest.mark.asyncio
async def test_no_weak_points_uses_random_and_preserves_finalize_context():
    payload = request(
        load_mastery=AsyncMock(return_value=[]),
        compute_weak_kps=AsyncMock(return_value=[]),
        load_random=AsyncMock(return_value=[question(1), question(2)]),
    )

    questions, metadata = await run_legacy_weakness_vector(payload)

    assert [q.id for q in questions] == [1, 2]
    assert all(item["strategy"] == "random_fallback" for item in metadata.values())
    payload.finalize.assert_awaited_once_with(
        questions,
        metadata,
        True,
        payload.db,
        9,
        "ds",
        request_id="request-1",
        experiment_id=7,
        variant_key="a",
    )


@pytest.mark.asyncio
async def test_vector_matches_are_used_without_extra_fill_when_complete():
    payload = request(
        count=2,
        vector_recall=AsyncMock(
            return_value=[
                {"question_id": 1, "recommend_score": 0.8, "similarity": 0.9},
                {"question_id": 2, "recommend_score": 0.7, "similarity": 0.8},
            ]
        ),
    )
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [question(1), question(2)]
    rows.scalar.return_value = 0
    payload.db.execute = AsyncMock(return_value=rows)

    questions, metadata = await run_legacy_weakness_vector(payload)

    assert [q.id for q in questions] == [1, 2]
    assert metadata[1]["strategy"] == "smart_vector"
    assert metadata[1]["recommend_reason"] == "薄弱知识点推荐：队列"
    assert payload.db.execute.await_count == 1


@pytest.mark.asyncio
async def test_shortfall_uses_kp_fill_then_random_fill():
    payload = request(
        vector_recall=AsyncMock(
            return_value=[{"question_id": 1, "recommend_score": 0.8}]
        )
    )
    vector_rows = MagicMock()
    vector_rows.scalars.return_value.all.return_value = [question(1)]
    count_rows = MagicMock()
    count_rows.scalar.return_value = 1
    kp_rows = MagicMock()
    kp_rows.scalars.return_value.all.return_value = [question(3)]
    random_count_rows = MagicMock()
    random_count_rows.scalar.return_value = 1
    random_rows = MagicMock()
    random_rows.scalars.return_value.all.return_value = [question(4)]
    payload.db.execute = AsyncMock(
        side_effect=[vector_rows, count_rows, kp_rows, random_count_rows, random_rows]
    )

    questions, metadata = await run_legacy_weakness_vector(payload)

    assert [q.id for q in questions] == [1, 3, 4]
    assert metadata[3]["strategy"] == "kp_fallback"
    assert metadata[3]["recommend_reason"] == "薄弱知识点补齐：队列"
    assert metadata[4]["strategy"] == "random_fallback"
    assert metadata[4]["recommend_reason"] == "随机补齐"
