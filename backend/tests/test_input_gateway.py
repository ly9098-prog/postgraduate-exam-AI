"""Tests for Phase 3: InputGateway."""
from __future__ import annotations

import os
import tempfile

import pytest

from app.features.input_gateway import InputGateway, detect_source_type


class TestInputGateway:
    def test_accept_pdf_bytes(self):
        gateway = InputGateway(storage_root=tempfile.mkdtemp())
        source = b"%PDF-1.4 test content " * 100
        doc = gateway.accept(source, filename="test.pdf", mime="application/pdf")

        assert doc.source_type == "pdf"
        assert doc.mime_type == "application/pdf"
        assert doc.sha256
        assert doc.size_bytes == len(source)
        assert os.path.exists(doc.local_path)

    def test_accept_image_bytes(self):
        gateway = InputGateway(storage_root=tempfile.mkdtemp())
        source = b"\x89PNG\r\n\x1a\n" + b"data" * 100
        doc = gateway.accept(source, filename="img.png")

        assert doc.source_type == "image"
        assert os.path.exists(doc.local_path)

    def test_read_source(self):
        gateway = InputGateway(storage_root=tempfile.mkdtemp())
        source = b"hello world pipeline input"
        doc = gateway.accept(source, filename="test.txt")
        assert gateway.read_source(doc) == source

    def test_detect_source_type_by_extension(self):
        assert detect_source_type(filename="doc.pdf") == "pdf"
        assert detect_source_type(filename="img.png") == "image"
        assert detect_source_type(filename="data.txt") == "txt"

    def test_detect_source_type_by_mime(self):
        assert detect_source_type(mime="application/pdf") == "pdf"
        assert detect_source_type(mime="image/png") == "image"

    def test_detect_source_type_unknown(self):
        assert detect_source_type() == "unknown"
        assert detect_source_type(filename="file.xyz") == "unknown"
