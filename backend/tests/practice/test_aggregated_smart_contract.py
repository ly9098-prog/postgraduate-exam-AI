"""Provider contracts for aggregated smart-practice orchestration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.practice.aggregated_smart import (
    build_smart_buckets,
    load_aggregated_subject_codes,
    run_aggregated_smart,
    single_bucket_result,
)


def question(qid: int, subject_id: int):
    return SimpleNamespace(id=qid, subject_id=subject_id)


def subject(sid: int, code: str):
    return SimpleNamespace(id=sid, code=code)


def real_round_robin(buckets, count, *, randomize_order=False):
    result = []
    metadata = {}
    seen = set()
    for index in range(max((len(bucket) for bucket in buckets), default=0)):
        for bucket in buckets:
            if index >= len(bucket):
                continue
            item, meta = bucket[index]
            if item.id in seen:
                continue
            seen.add(item.id)
            result.append(item)
            metadata[item.id] = meta
            if len(result) == count:
                return result, metadata
    return result, metadata


@pytest.mark.asyncio
async def test_subject_loader_filters_missing_and_empty_codes():
    loader = AsyncMock(
        return_value=[subject(1, "ds"), subject(2, ""), subject(3, "os")]
    )

    assert await load_aggregated_subject_codes(loader, [1, 2, 3]) == {
        1: "ds",
        3: "os",
    }
    loader.assert_awaited_once_with([1, 2, 3])


def test_bucket_and_single_bucket_helpers_preserve_order_and_metadata():
    rows = [question(1, 10), question(2, 10)]
    metadata = {1: {"strategy": "scored"}, 2: {"strategy": "vector"}}

    bucket = build_smart_buckets(rows, metadata)
    selected, selected_metadata = single_bucket_result(bucket, 1)

    assert bucket == [(rows[0], metadata[1]), (rows[1], metadata[2])]
    assert selected == [rows[0]]
    assert selected_metadata == {1: metadata[1]}


@pytest.mark.asyncio
async def test_no_buckets_returns_empty_without_merge_or_finalize():
    load_subjects = AsyncMock(return_value=[])
    load_smart = AsyncMock()
    merge = AsyncMock()
    finalize = AsyncMock()

    result = await run_aggregated_smart(
        db=object(),
        user_id=7,
        subject_code="cs",
        subject_ids=[10, 20],
        count=5,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=False,
        request_id="request",
        smart_strategy="scored",
        logger=SimpleNamespace(info=lambda *_: None),
        load_subjects=load_subjects,
        load_smart=load_smart,
        merge_metadata=merge,
        finalize=finalize,
    )

    assert result == ([], {})
    load_smart.assert_not_awaited()
    merge.assert_not_called()
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_bucket_slices_once_and_finalizes_without_merge():
    db = object()
    rows = [question(1, 10), question(2, 10)]
    metadata = {1: {"strategy": "scored"}, 2: {"strategy": "scored"}}
    load_subjects = AsyncMock(return_value=[subject(10, "ds")])
    load_smart = AsyncMock(return_value=(rows, metadata))
    merge = AsyncMock()
    finalize = AsyncMock(return_value=(rows[:1], {1: metadata[1]}))

    result = await run_aggregated_smart(
        db=db,
        user_id=7,
        subject_code="cs",
        subject_ids=[10],
        count=1,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=True,
        request_id="request",
        smart_strategy="scored",
        logger=SimpleNamespace(info=lambda *_: None),
        load_subjects=load_subjects,
        load_smart=load_smart,
        merge_metadata=merge,
        finalize=finalize,
    )

    assert result == (rows[:1], {1: metadata[1]})
    load_smart.assert_awaited_once_with(
        db=db,
        user_id=7,
        subject_code="ds",
        count=1,
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=True,
        request_id="request",
        smart_strategy="scored",
        skip_finalize=True,
        subject_ids=[10],
    )
    merge.assert_not_called()
    finalize.assert_awaited_once_with(
        questions=rows[:1],
        metadata={1: metadata[1]},
        db=db,
        user_id=7,
        subject_code="cs",
        request_id="request",
    )


@pytest.mark.asyncio
async def test_multiple_buckets_merge_once_and_finalize_final_projection():
    db = object()
    subject_rows = [subject(10, "ds"), subject(20, "os")]
    ds_rows = [question(101, 10), question(102, 10)]
    os_rows = [question(201, 20), question(202, 20)]
    ds_meta = {101: {"strategy": "ds"}, 102: {"strategy": "ds"}}
    os_meta = {201: {"strategy": "os"}, 202: {"strategy": "os"}}
    load_subjects = AsyncMock(return_value=subject_rows)
    load_smart = AsyncMock(
        side_effect=[
            (ds_rows, ds_meta),
            (os_rows, os_meta),
        ]
    )
    merge = Mock(
        return_value=([ds_rows[0], os_rows[0]], {101: ds_meta[101], 201: os_meta[201]})
    )
    finalize = AsyncMock(
        return_value=([ds_rows[0], os_rows[0]], {101: ds_meta[101], 201: os_meta[201]})
    )

    result = await run_aggregated_smart(
        db=db,
        user_id=7,
        subject_code="cs",
        subject_ids=[10, 20],
        count=2,
        exclude_answered=True,
        no_repeat_days=4,
        use_leitner=False,
        request_id="request",
        smart_strategy="path",
        logger=SimpleNamespace(info=lambda *_: None),
        load_subjects=load_subjects,
        load_smart=load_smart,
        merge_metadata=merge,
        finalize=finalize,
    )

    assert result == ([ds_rows[0], os_rows[0]], {101: ds_meta[101], 201: os_meta[201]})
    assert load_smart.await_args_list[0].kwargs["subject_code"] == "ds"
    assert load_smart.await_args_list[1].kwargs["subject_code"] == "os"
    merge.assert_called_once()
    assert merge.call_args.args[0] == [
        [(ds_rows[0], ds_meta[101]), (ds_rows[1], ds_meta[102])],
        [(os_rows[0], os_meta[201]), (os_rows[1], os_meta[202])],
    ]
    assert merge.call_args.args[1] == 2
    assert merge.call_args.kwargs == {"randomize_order": False}
    finalize.assert_awaited_once_with(
        questions=[ds_rows[0], os_rows[0]],
        metadata={101: ds_meta[101], 201: os_meta[201]},
        db=db,
        user_id=7,
        subject_code="cs",
        request_id="request",
    )


@pytest.mark.asyncio
async def test_real_round_robin_keeps_balanced_subject_coverage():
    ds_rows = [question(101, 10), question(102, 10), question(103, 10)]
    os_rows = [question(201, 20), question(202, 20)]
    buckets = [
        [(row, {"strategy": "ds"}) for row in ds_rows],
        [(row, {"strategy": "os"}) for row in os_rows],
    ]

    rows, metadata = real_round_robin(buckets, 4)

    assert [row.id for row in rows] == [101, 201, 102, 202]
    assert {row.subject_id for row in rows} == {10, 20}
    assert metadata[201] == {"strategy": "os"}
