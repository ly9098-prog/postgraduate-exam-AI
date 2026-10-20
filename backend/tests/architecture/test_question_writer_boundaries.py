"""The question core owns normalization; writer entry points have no reverse imports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import cyclic_edges, scan_application

APP = Path(__file__).resolve().parents[2] / "app"
CORE = "app.features.question_pipeline"
WRITER = "app.features.question_import_writer"


def test_question_core_and_writer_form_one_way_dependency():
    graph, _ = scan_application(APP)
    assert CORE in graph[WRITER]
    assert WRITER not in graph[CORE]
    assert not any(source in (CORE, WRITER) or target in (CORE, WRITER)
                   for source, target in cyclic_edges(graph))
    for consumer in (
        "app.api.v1.imports", "app.api.v1.admin_imports",
        "app.features.text_question_parser", "app.features.question_draft_generator",
        "app.services.task_queue_worker",
    ):
        assert WRITER in graph[consumer], consumer


@pytest.mark.parametrize("module", [CORE, WRITER, "app.features.text_question_parser"])
def test_question_modules_can_be_imported_first_in_fresh_process(module):
    probe = """
import importlib
import sys
module = importlib.import_module(sys.argv[1])
if sys.argv[1] == 'app.features.question_pipeline':
    assert 'app.features.question_import_writer' not in sys.modules
    assert 'app.features.question_ai_complete' not in sys.modules
    assert 'app.features.question_ai_enrich' not in sys.modules
core = importlib.import_module('app.features.question_pipeline')
writer = importlib.import_module('app.features.question_import_writer')
for name in (
    'import_excel', 'import_pdf', 'approve_question', 'batch_approve',
    'generate_template', 'list_batches', 'get_batch_detail',
    '_create_question_import', '_guess_subject', '_parse_excel', '_parse_pdf',
    '_extract_pdf_text', '_parse_excel_row', '_parse_option_line',
):
    assert not hasattr(core, name), name
    assert callable(getattr(writer, name)), name
assert writer.process_question_pipeline is core.process_question_pipeline
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, module], cwd=APP.parent,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
