"""OCR Job state machine tests — pure unit, no DB needed."""

from __future__ import annotations

import pytest

from app.models.pipeline_enums import (
    OCR_JOB_TRANSITIONS,
    OCRJobStatus,
    guard_ocr_job_transition,
)


class TestOCRJobStateTransitions:
    """Verify every valid and invalid transition for OCRJobStatus."""

    def test_transition_map_is_complete(self):
        """Every status appears as a key in the transition map."""
        for status in OCRJobStatus:
            assert status.value in OCR_JOB_TRANSITIONS, (
                f"Missing transition entry for {status.value}"
            )

    def test_terminal_states_have_no_outgoing(self):
        """Terminal states must have empty transition sets."""
        terminal = [
            OCRJobStatus.COMPLETED,
            OCRJobStatus.FAILED,
            OCRJobStatus.DEAD_LETTER,
            OCRJobStatus.CANCELLED,
        ]
        for s in terminal:
            assert OCR_JOB_TRANSITIONS[s.value] == set(), (
                f"Terminal state {s.value} should have no outgoing transitions, got {OCR_JOB_TRANSITIONS[s.value]}"
            )

    def test_valid_transitions_succeed(self):
        guard_ocr_job_transition("pending", "leased")
        guard_ocr_job_transition("pending", "cancelled")
        guard_ocr_job_transition("leased", "downloading")
        guard_ocr_job_transition("leased", "cancelled")

    def test_valid_transitions_run(self):
        """Happy path: pending → leased → downloading → running → uploading → completed"""
        valid = [
            ("pending", "leased"),
            ("leased", "downloading"),
            ("downloading", "running"),
            ("running", "uploading"),
            ("uploading", "completed"),
        ]
        for current, next_s in valid:
            guard_ocr_job_transition(current, next_s)  # should not raise

    def test_retry_path(self):
        """Retryable → pending or dead_letter."""
        guard_ocr_job_transition("retryable", "pending")
        guard_ocr_job_transition("retryable", "dead_letter")

    def test_failure_paths(self):
        """running → failed, uploading → failed."""
        guard_ocr_job_transition("running", "failed")
        guard_ocr_job_transition("uploading", "failed")

    def test_invalid_transition_raises(self):
        cases = [
            ("pending", "completed"),
            ("pending", "downloading"),
            ("pending", "failed"),
            ("completed", "pending"),
            ("cancelled", "pending"),
            ("failed", "pending"),
            ("dead_letter", "pending"),
            ("downloading", "cancelled"),
            ("downloading", "leased"),
        ]
        for current, next_s in cases:
            with pytest.raises(ValueError, match="Invalid OCR job status transition"):
                guard_ocr_job_transition(current, next_s)

    def test_leased_can_be_cancelled(self):
        guard_ocr_job_transition("leased", "cancelled")

    def test_uploading_can_be_retryable(self):
        guard_ocr_job_transition("uploading", "retryable")

    def test_running_can_be_retryable(self):
        guard_ocr_job_transition("running", "retryable")

    def test_downloading_can_be_retryable(self):
        guard_ocr_job_transition("downloading", "retryable")
