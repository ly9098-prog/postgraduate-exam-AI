"""Aggregated random-practice orchestration with provider ownership."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from logging import Logger
from typing import Any, Protocol


class QuestionRecord(Protocol):
    id: int
    subject_id: int


class RandomBucketLoader(Protocol):
    async def __call__(
        self,
        db: Any,
        subject_id: int,
        count: int,
    ) -> list[QuestionRecord]: ...


class RandomMerger(Protocol):
    def __call__(
        self,
        buckets: list[list[QuestionRecord]],
        count: int,
        *,
        randomize_order: bool = False,
    ) -> list[QuestionRecord]: ...


@dataclass(slots=True)
class AggregatedRandomRequest:
    db: Any
    subject_code: str
    subject_ids: list[int]
    count: int
    logger: Logger
    load_bucket: RandomBucketLoader
    merge: RandomMerger


async def run_aggregated_random(
    request: AggregatedRandomRequest,
) -> list[QuestionRecord]:
    """Load one ordered bucket per subject, then round-robin merge them."""
    buckets = [
        candidates
        for subject_id in request.subject_ids
        if (
            candidates := await request.load_bucket(
                request.db, subject_id, request.count
            )
        )
    ]
    if not buckets:
        _log_no_buckets(request)
        return []

    result = request.merge(buckets, request.count, randomize_order=True)
    _log_merged_buckets(request, buckets, result)
    return result


def _log_no_buckets(request: AggregatedRandomRequest) -> None:
    request.logger.info(
        "[AGG_RANDOM] subject_code=%s subject_ids=%s count=%d no_buckets",
        request.subject_code,
        request.subject_ids,
        request.count,
    )


def _log_merged_buckets(
    request: AggregatedRandomRequest,
    buckets: list[list[QuestionRecord]],
    result: list[QuestionRecord],
) -> None:
    per_subject = Counter(question.subject_id for question in result)
    request.logger.info(
        "[AGG_RANDOM] subject_code=%s subject_ids=%s count=%d "
        "non_empty_buckets=%d returned=%d per_subject=%s",
        request.subject_code,
        request.subject_ids,
        request.count,
        len(buckets),
        len(result),
        dict(per_subject),
    )
