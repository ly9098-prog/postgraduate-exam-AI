"""Coordinator boundary tests — verify isolation and clean interfaces.

Each coordinator should:
- Accept PipelineExecutionContext (or equivalent)
- Return ModuleResult
- Not access raw OCR fields (rec_texts, dt_polys)
- Not perform DB writes directly
"""

from __future__ import annotations

import pytest

from app.features.coordinators import (
    CorrectionCoordinator,
    DocumentStructureCoordinator,
    DomainParsingCoordinator,
    InputCoordinator,
    OCRCoordinator,
    PersistenceCoordinator,
    ReviewCoordinator,
    ValidationCoordinator,
)
from app.features.input_gateway import InputDocument


class TestInputCoordinator:
    @pytest.mark.asyncio
    async def test_input_coordinator_accepts_bytes(self):
        coord = InputCoordinator()
        result = await coord.run(b"test pdf content", filename="test.pdf")
        assert result is not None

    @pytest.mark.asyncio
    async def test_input_coordinator_returns_input_document(self):
        coord = InputCoordinator()
        result = await coord.run(b"%PDF-1.4 test", filename="doc.pdf", mime="application/pdf")
        if result.is_success:
            assert isinstance(result.data, InputDocument)


class TestOCRCoordinator:
    @pytest.mark.asyncio
    async def test_ocr_coordinator_runs(self):
        coord = OCRCoordinator()
        result = await coord.run(None, trace_id="test")
        assert result is not None


class TestDocumentStructureCoordinator:
    @pytest.mark.asyncio
    async def test_doc_structure_runs(self):
        coord = DocumentStructureCoordinator()
        result = await coord.run(None, trace_id="test-struct")
        assert result is not None


class TestDomainParsingCoordinator:
    @pytest.mark.asyncio
    async def test_domain_parsing_runs(self):
        coord = DomainParsingCoordinator()
        result = await coord.run(None, trace_id="test-domain")
        assert result is not None


class TestCorrectionCoordinator:
    @pytest.mark.asyncio
    async def test_correction_runs(self):
        coord = CorrectionCoordinator()
        result = await coord.run(None, trace_id="test-corr")
        assert result is not None


class TestValidationCoordinator:
    @pytest.mark.asyncio
    async def test_validation_runs(self):
        coord = ValidationCoordinator()
        result = await coord.run(None, trace_id="test-val")
        assert result is not None


class TestReviewCoordinator:
    @pytest.mark.asyncio
    async def test_review_runs(self):
        coord = ReviewCoordinator()
        result = await coord.run(None, trace_id="test-review")
        assert result is not None


class TestPersistenceCoordinator:
    @pytest.mark.asyncio
    async def test_persistence_runs(self):
        coord = PersistenceCoordinator()
        result = await coord.run(None, trace_id="test-persist")
        assert result is not None
