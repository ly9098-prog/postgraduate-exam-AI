"""Tests for dual freeze analysis script.

Tests the analyze_freeze_dual.py analysis logic in isolation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.analyze_freeze_dual import analyze, build_markdown_report, save_report


_SAMPLE_DIAGNOSTICS = {
    "legacy_option_count": 10,
    "ir_option_count": 10,
    "option_key_match": 1.0,
    "option_text_match": 0.95,
    "binding_lost_count": 0,
}

_SAMPLE_DIFFS = [
    {"type": "text_mismatch", "source": "test_case", "option_key": "A",
     "legacy_text": "10", "ir_text": "10 "},
    {"type": "binding_lost", "source": "test_case", "option_key": "B",
     "legacy_text": "20", "ir_text": ""},
]

_SAMPLE_DATA = {
    "diagnostics": _SAMPLE_DIAGNOSTICS,
    "differences": _SAMPLE_DIFFS,
    "documents_total": 1,
    "questions_total": 5,
    "fallback_count": 0,
}


class TestAnalyze:
    def test_analyze_basic_metrics(self):
        stats = analyze(_SAMPLE_DATA)
        assert stats["legacy_option_count"] == 10
        assert stats["ir_option_count"] == 10
        assert stats["option_key_match"] == 1.0
        assert stats["differences_count"] == 2
        assert stats["questions_total"] == 5

    def test_differences_by_type(self):
        stats = analyze(_SAMPLE_DATA)
        by_type = stats["differences_by_type"]
        assert by_type.get("text_mismatch") == 1
        assert by_type.get("binding_lost") == 1

    def test_differences_by_source(self):
        stats = analyze(_SAMPLE_DATA)
        assert stats["differences_by_source"].get("test_case") == 2

    def test_differences_by_key(self):
        stats = analyze(_SAMPLE_DATA)
        assert stats["differences_by_key"].get("A") == 1
        assert stats["differences_by_key"].get("B") == 1

    def test_empty_diffs(self):
        data = {"diagnostics": _SAMPLE_DIAGNOSTICS, "differences": [],
                "documents_total": 1, "questions_total": 0}
        stats = analyze(data)
        assert stats["differences_count"] == 0


class TestMarkdownReport:
    def test_report_contains_readiness(self):
        stats = analyze(_SAMPLE_DATA)
        report = build_markdown_report(stats)
        assert "Dual Freeze Analysis Report" in report
        assert "option_key_match" in report

    def test_report_ready_when_criteria_met(self):
        data = {
            "diagnostics": {
                "legacy_option_count": 10,
                "ir_option_count": 10,
                "option_key_match": 1.0,
                "option_text_match": 0.96,
                "binding_lost_count": 0,
            },
            "differences": [{"type": "text_mismatch", "source": "test", "option_key": "A",
                             "legacy_text": "10", "ir_text": "10 "}],
            "documents_total": 1,
            "questions_total": 5,
            "fallback_count": 0,
        }
        stats = analyze(data)
        report = build_markdown_report(stats)
        assert "recommended for pre-release" in report

    def test_report_not_ready_when_binding_lost(self):
        data = dict(_SAMPLE_DATA)
        data["diagnostics"] = dict(_SAMPLE_DIAGNOSTICS)
        data["diagnostics"]["binding_lost_count"] = 1
        stats = analyze(data)
        report = build_markdown_report(stats)
        assert "NOT yet ready" in report


class TestSaveReport:
    def test_save_creates_files(self):
        stats = analyze(_SAMPLE_DATA)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_report(stats, _SAMPLE_DIFFS, tmpdir)
            assert Path(paths["summary"]).exists()
            assert Path(paths["differences"]).exists()
            assert Path(paths["metrics_by_bucket"]).exists()
            assert Path(paths["report"]).exists()

    def test_summary_json_valid(self):
        stats = analyze(_SAMPLE_DATA)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_report(stats, _SAMPLE_DIFFS, tmpdir)
            with open(paths["summary"]) as f:
                loaded = json.load(f)
            assert loaded["legacy_option_count"] == 10
