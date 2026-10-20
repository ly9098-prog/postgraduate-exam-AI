"""Question AI entry points must not be re-exported by the normalization core."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import cyclic_edges, scan_application

APP = Path(__file__).resolve().parents[2] / "app"
CORE = "app.features.question_pipeline"
AI_MODULES = {
    "app.features.question_ai_complete",
    "app.features.question_ai_enrich",
    "app.features.question_draft_generator",
}


def test_normalization_core_does_not_import_ai_entry_points():
    graph, _ = scan_application(APP)
    assert not graph[CORE] & AI_MODULES
    assert not any(source in AI_MODULES or target in AI_MODULES
                   for source, target in cyclic_edges(graph))
    assert "app.features.question_ai_complete" in graph["app.services.admin_import_service"]
    assert CORE not in graph["app.services.admin_import_service"]
    assert "app.features.question_draft_generator" in graph["app.api.v1.ai_import"]


@pytest.mark.parametrize("module", sorted(AI_MODULES))
def test_ai_module_can_be_imported_first_in_fresh_process(module):
    probe = """
import importlib
import sys
module = importlib.import_module(sys.argv[1])
core = importlib.import_module('app.features.question_pipeline')
for name in (
    'complete_import', 'complete_import_with_strategy', 'batch_complete_questions',
    'enrich_import', 'enrich_batch', 'generate_drafts', '_has_complete_answer_risk',
):
    assert not hasattr(core, name), name
assert callable(core.process_question_pipeline)
assert callable(core.list_logs)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, module], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_ai_route_and_admin_service_use_defining_functions():
    from app.api.v1 import ai_import
    from app.features import (
        question_ai_complete,
        question_draft_generator,
        question_pipeline,
    )
    from app.services import admin_import_service

    assert ai_import.question_draft_generator is question_draft_generator
    assert ai_import.question_pipeline.list_logs is question_pipeline.list_logs
    assert admin_import_service.question_ai_complete is question_ai_complete
