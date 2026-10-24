"""Provider contracts for the smart-practice knowledge-path branch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.practice.smart_path_supplement import (
    SmartPathRequest,
    build_path_metadata,
    run_smart_path,
)


def question(qid: int):
    return SimpleNamespace(id=qid)


def make_request(**overrides):
    defaults = dict(
        db=object(),
        user_id=9,
        subject_code="ds",
        count=2,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=False,
        scope_ids=[2],
        skip_finalize=False,
        experiment_id=11,
        variant_key="B",
        request_id="request",
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None
        ),
        load_path=AsyncMock(),
        load_fallback=AsyncMock(),
        merge_results=Mock(
            side_effect=lambda primary, primary_meta, fallback, fallback_meta, **kwargs: (
                primary + fallback[: kwargs["count"] - len(primary)],
                {
                    **primary_meta,
                    **{
                        qid: meta
                        for qid, meta in fallback_meta.items()
                        if qid
                        in {
                            row.id for row in fallback[: kwargs["count"] - len(primary)]
                        }
                    },
                },
            )
        ),
        finalize=AsyncMock(
            side_effect=lambda questions, metadata, *args, **kwargs: (
                questions,
                metadata,
            )
        ),
        build_conditions=Mock(return_value=[]),
    )
    defaults.update(overrides)
    return SmartPathRequest(**defaults)


def make_db(rows):
    db = Mock()
    db.execute = AsyncMock(
        return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=rows))))
    )
    return db


@pytest.mark.asyncio
async def test_full_path_result_finalizes_only_returned_rows():
    rows = [question(1), question(2), question(3)]
    db = make_db(rows)
    request = make_request(db=db)
    request.load_path.return_value = {
        "recommended_question_ids": [1, 2, 3],
        "nodes": [
            {
                "recommended_question_ids": [1, 2, 3],
                "priority": 0.8,
                "reason": "path",
            }
        ],
    }

    result = await run_smart_path(request)

    assert result == (
        rows[:2],
        build_path_metadata(rows[:2], request.load_path.return_value),
    )
    request.load_fallback.assert_not_awaited()
    request.merge_results.assert_not_called()
    request.finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_short_path_merges_fallback_before_slice():
    rows = [question(1)]
    fallback_rows = [question(2), question(3)]
    db = make_db(rows)
    request = make_request(db=db, count=2)
    request.load_path.return_value = {"recommended_question_ids": [1], "nodes": []}
    request.load_fallback.return_value = (
        fallback_rows,
        {2: {"strategy": "vector"}, 3: {"strategy": "vector"}},
    )

    result = await run_smart_path(request)

    assert result == (
        rows + fallback_rows[:1],
        {
            **build_path_metadata(rows, request.load_path.return_value),
            2: {"strategy": "vector"},
        },
    )
    request.load_fallback.assert_awaited_once_with(
        request.db,
        request.user_id,
        request.subject_code,
        count=1,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
        use_leitner=request.use_leitner,
        exclude_ids={1},
        subject_ids=request.scope_ids,
    )
    request.merge_results.assert_called_once()
    request.finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_path_failure_returns_none_without_fallback():
    request = make_request()
    request.load_path.side_effect = RuntimeError("path unavailable")

    assert await run_smart_path(request) is None
    request.load_fallback.assert_not_awaited()
    request.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_or_unmatched_candidates_return_none():
    empty = make_request()
    empty.load_path.return_value = {"recommended_question_ids": []}
    assert await run_smart_path(empty) is None

    unmatched = make_request(db=make_db([]))
    unmatched.load_path.return_value = {"recommended_question_ids": [1]}
    assert await run_smart_path(unmatched) is None
    assert unmatched.finalize.await_count == 0


def test_path_metadata_prefers_node_reason_and_priority():
    rows = [question(1), question(2)]
    result = {
        "nodes": [
            {
                "recommended_question_ids": [1],
                "reason": "node reason",
                "priority": 0.9,
                "name": "node",
            },
            {"recommended_question_ids": [2], "name": "fallback node"},
        ]
    }

    metadata = build_path_metadata(rows, result)

    assert metadata[1] == {
        "recommend_reason": "node reason",
        "recommend_score": 0.9,
        "strategy": "knowledge_path",
        "similarity": None,
    }
    assert metadata[2]["recommend_reason"] == "知识路径推荐：fallback node"
    assert metadata[2]["recommend_score"] is None
