"""Tests for ExecutionQuota — standalone to avoid control_plane imports of env."""
from __future__ import annotations

import pytest

from app.features.control_plane import (
    ExecutionQuota,
    PipelineExecutionContext,
    QuotaExceededError,
)


class TestExecutionQuotaStandalone:
    def test_quota_immutable(self):
        q = ExecutionQuota(max_pages=10, max_ocr_calls=5)
        assert q.max_pages == 10
        assert q.max_ocr_calls == 5

    def test_page_limit_check(self):
        ctx = PipelineExecutionContext(pipeline_id="t", quota=ExecutionQuota(max_pages=50))
        ctx.check_page_limit(49)
        with pytest.raises(QuotaExceededError) as exc:
            ctx.check_page_limit(51)
        assert exc.value.code == "PAGE_LIMIT_EXCEEDED"

    def test_input_size_check(self):
        ctx = PipelineExecutionContext(pipeline_id="t", quota=ExecutionQuota(max_input_bytes=1000))
        ctx.check_input_size(999)
        with pytest.raises(QuotaExceededError) as exc:
            ctx.check_input_size(1001)
        assert exc.value.code == "INPUT_TOO_LARGE"
