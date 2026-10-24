"""Aggregated smart-practice orchestration with provider ownership."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from logging import Logger
from typing import Any, Protocol


class SubjectRecord(Protocol):
    id: int
    code: str


class QuestionRecord(Protocol):
    id: int
    subject_id: int


class SubjectLoader(Protocol):
    async def __call__(self, subject_ids: list[int]) -> list[SubjectRecord]: ...


class SmartLoader(Protocol):
    async def __call__(
        self, **kwargs: Any
    ) -> tuple[list[QuestionRecord], dict[int, dict]]: ...


class MetadataMerger(Protocol):
    def __call__(
        self,
        buckets: list[list[tuple[QuestionRecord, dict]]],
        count: int,
        *,
        randomize_order: bool = False,
    ) -> tuple[list[QuestionRecord], dict[int, dict]]: ...


class SmartFinalizer(Protocol):
    async def __call__(
        self, **kwargs: Any
    ) -> tuple[list[QuestionRecord], dict[int, dict]]: ...


async def load_aggregated_subject_codes(
    load_subjects: SubjectLoader,
    subject_ids: list[int],
) -> dict[int, str]:
    """Return the exact requested subject IDs that have a non-empty code."""
    subjects = await load_subjects(subject_ids)
    return {int(subject.id): str(subject.code) for subject in subjects if subject.code}


def build_smart_buckets(
    questions: list[QuestionRecord],
    metadata: dict[int, dict],
) -> list[tuple[QuestionRecord, dict]]:
    """Pair each returned question with its own metadata snapshot."""
    return [(question, metadata.get(question.id, {})) for question in questions]


def single_bucket_result(
    bucket: list[tuple[QuestionRecord, dict]],
    count: int,
) -> tuple[list[QuestionRecord], dict[int, dict]]:
    selected = bucket[:count]
    return [question for question, _ in selected], {
        question.id: metadata for question, metadata in selected
    }


async def run_aggregated_smart(
    *,
    db: Any,
    user_id: int,
    subject_code: str,
    subject_ids: list[int],
    count: int,
    exclude_answered: bool,
    no_repeat_days: int | None,
    use_leitner: bool,
    request_id: str | None,
    smart_strategy: str,
    logger: Logger,
    load_subjects: SubjectLoader,
    load_smart: SmartLoader,
    merge_metadata: MetadataMerger,
    finalize: SmartFinalizer,
) -> tuple[list[QuestionRecord], dict[int, dict]]:
    """Fan out per-subject smart selection, then merge and finalize once."""
    subject_codes = await load_aggregated_subject_codes(load_subjects, subject_ids)
    buckets = await _load_smart_buckets(
        db=db,
        user_id=user_id,
        subject_ids=subject_ids,
        count=count,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        use_leitner=use_leitner,
        request_id=request_id,
        smart_strategy=smart_strategy,
        subject_codes=subject_codes,
        load_smart=load_smart,
    )

    if not buckets:
        _log_no_buckets(logger, subject_code, subject_ids, count)
        return [], {}

    questions, metadata = _merge_smart_buckets(buckets, count, merge_metadata)
    _log_merged_buckets(logger, subject_code, subject_ids, count, buckets, questions)
    return await finalize(
        questions=questions,
        metadata=metadata,
        db=db,
        user_id=user_id,
        subject_code=subject_code,
        request_id=request_id,
    )


def _merge_smart_buckets(
    buckets: list[list[tuple[QuestionRecord, dict]]],
    count: int,
    merge_metadata: MetadataMerger,
) -> tuple[list[QuestionRecord], dict[int, dict]]:
    if len(buckets) == 1:
        return single_bucket_result(buckets[0], count)
    return merge_metadata(buckets, count, randomize_order=False)


async def _load_smart_buckets(**kwargs: Any) -> list[list[tuple[QuestionRecord, dict]]]:
    return await _SmartBucketLoader(**kwargs).load()


@dataclass(slots=True)
class _SmartBucketLoader:
    db: Any
    user_id: int
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    request_id: str | None
    smart_strategy: str
    subject_codes: dict[int, str]
    load_smart: SmartLoader
    subject_ids: list[int]

    async def load(self) -> list[list[tuple[QuestionRecord, dict]]]:
        buckets: list[list[tuple[QuestionRecord, dict]]] = []
        for subject_id in self.subject_ids:
            bucket = await self.load_subject(subject_id)
            if bucket:
                buckets.append(bucket)
        return buckets

    async def load_subject(self, subject_id: int) -> list[tuple[QuestionRecord, dict]]:
        code = self.subject_codes.get(subject_id)
        if not code:
            return []
        questions, metadata = await self.load_smart(
            db=self.db,
            user_id=self.user_id,
            subject_code=code,
            count=self.count,
            exclude_answered=self.exclude_answered,
            no_repeat_days=self.no_repeat_days,
            use_leitner=self.use_leitner,
            request_id=self.request_id,
            smart_strategy=self.smart_strategy,
            skip_finalize=True,
            subject_ids=[subject_id],
        )
        return build_smart_buckets(questions, metadata) if questions else []


def _log_no_buckets(
    logger: Logger, subject_code: str, subject_ids: list[int], count: int
) -> None:
    logger.info(
        "[AGG_SMART] subject_code=%s subject_ids=%s count=%d no_buckets",
        subject_code,
        subject_ids,
        count,
    )


def _log_single_bucket(
    logger: Logger,
    subject_code: str,
    subject_ids: list[int],
    count: int,
    question_count: int,
) -> None:
    logger.info(
        "[AGG_SMART] subject_code=%s subject_ids=%s count=%d buckets=%d "
        "returned=%d (single)",
        subject_code,
        subject_ids,
        count,
        1,
        question_count,
    )


def _log_merged_buckets(
    logger: Logger,
    subject_code: str,
    subject_ids: list[int],
    count: int,
    buckets: list[list[tuple[QuestionRecord, dict]]],
    questions: list[QuestionRecord],
) -> None:
    if len(buckets) == 1:
        _log_single_bucket(logger, subject_code, subject_ids, count, len(questions))
        return
    per_subject = Counter(question.subject_id for question in questions)
    logger.info(
        "[AGG_SMART] subject_code=%s subject_ids=%s count=%d "
        "non_empty_buckets=%d returned=%d per_subject=%s",
        subject_code,
        subject_ids,
        count,
        len(buckets),
        len(questions),
        dict(per_subject),
    )
