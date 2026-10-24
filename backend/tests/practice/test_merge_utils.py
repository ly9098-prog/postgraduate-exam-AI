"""Tests for the extracted practice merge and fingerprint helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.practice.merge_utils import (
    build_fallback_metadata,
    extract_graph_context,
    practice_submission_fingerprint,
    round_robin_merge,
    round_robin_merge_with_metadata,
)


class TestRoundRobinMerge:
    def test_empty_buckets(self):
        assert round_robin_merge([], 5) == []

    def test_all_empty_lists(self):
        assert round_robin_merge([[], []], 5) == []

    def test_count_zero(self):
        assert round_robin_merge([[1, 2, 3]], 0) == []

    def test_single_bucket(self):
        assert round_robin_merge([[1, 2, 3]], 2) == [1, 2]

    def test_interleaves_buckets(self):
        result = round_robin_merge([[1, 3, 5], [2, 4, 6]], 6)
        assert result == [1, 2, 3, 4, 5, 6]

    def test_deduplicates_by_id(self):
        a = SimpleNamespace(id=1)
        b = SimpleNamespace(id=2)
        c = SimpleNamespace(id=1)  # same id as a
        result = round_robin_merge([[a, b], [c]], 5)
        assert len(result) == 2
        assert result[0].id == 1
        assert result[1].id == 2

    def test_unequal_buckets(self):
        result = round_robin_merge([[1, 3, 5], [2]], 5)
        assert result == [1, 2, 3, 5]


class TestRoundRobinMergeWithMetadata:
    def test_empty(self):
        merged, meta = round_robin_merge_with_metadata([], 5)
        assert merged == []
        assert meta == {}

    def test_merges_with_metadata(self):
        q1 = SimpleNamespace(id=1)
        q2 = SimpleNamespace(id=2)
        meta1 = {"score": 0.9}
        meta2 = {"score": 0.5}
        merged, meta = round_robin_merge_with_metadata(
            [[(q1, meta1)], [(q2, meta2)]], 2
        )
        assert len(merged) == 2
        assert merged[0].id == 1
        assert merged[1].id == 2
        assert meta[1] == meta1
        assert meta[2] == meta2

    def test_deduplicates(self):
        q1 = SimpleNamespace(id=1)
        meta1 = {"score": 0.9}
        merged, meta = round_robin_merge_with_metadata(
            [[(q1, meta1)], [(q1, meta1)]], 5
        )
        assert len(merged) == 1
        assert len(meta) == 1


class TestBuildFallbackMetadata:
    def test_builds_correct_structure(self):
        result = build_fallback_metadata("some reason", "random")
        assert result["recommend_score"] is None
        assert result["recommend_reason"] == "some reason"
        assert result["strategy"] == "random"
        assert result["similarity"] is None


class TestExtractGraphContext:
    def test_empty_dict(self):
        blocked, prereqs, prereqs_by_target = extract_graph_context({})
        assert blocked == {}
        assert prereqs == {}
        assert prereqs_by_target == {}

    def test_extracts_fields(self):
        ctx = {
            "blocked_targets": {"1": ["a"]},
            "prerequisite_candidates": {"2": ["b"]},
            "prerequisites_by_target": {"3": ["c"]},
        }
        blocked, prereqs, prereqs_by = extract_graph_context(ctx)
        assert blocked == {"1": ["a"]}
        assert prereqs == {"2": ["b"]}
        assert prereqs_by == {"3": ["c"]}


class TestPracticeSubmissionFingerprint:
    def _meta(self):
        return {
            "request_id": "req-1",
            "subject_id": 1,
            "mode": "random",
            "started_at": "2025-08-08T10:00:00Z",
            "finished_at": "2025-08-08T10:10:00Z",
            "duration_sec": 600,
            "question_count": 2,
            "answered_count": 2,
        }

    def _answers(self):
        return [
            {"question_id": 2, "user_answer": "B", "used_time": 30, "request_id": "r2"},
            {"question_id": 1, "user_answer": "A", "used_time": 20, "request_id": "r1"},
        ]

    def test_deterministic_hash(self):
        fp1 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        fp2 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_different_answers_different_hash(self):
        fp1 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        answers2 = self._answers()
        answers2[0]["user_answer"] = "C"
        fp2 = practice_submission_fingerprint(
            answers=answers2,
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        assert fp1 != fp2

    def test_different_token_different_hash(self):
        fp1 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        fp2 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token456",
        )
        assert fp1 != fp2

    def test_answer_order_does_not_affect_hash(self):
        fp1 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        # Reversed order — should produce same hash (sorted by question_id)
        answers_rev = list(reversed(self._answers()))
        fp2 = practice_submission_fingerprint(
            answers=answers_rev,
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        assert fp1 == fp2

    def test_skipped_questions_affect_hash(self):
        fp1 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[],
            session_meta=self._meta(),
            batch_token="token123",
        )
        fp2 = practice_submission_fingerprint(
            answers=self._answers(),
            skipped_question_ids=[99],
            session_meta=self._meta(),
            batch_token="token123",
        )
        assert fp1 != fp2
