"""DOCX and OMML renderers share font policy without importing each other backwards."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
FONTS = APP / "services/export/docx_fonts.py"


def test_font_policy_depends_only_on_document_primitives():
    source = FONTS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports == {"__future__", "docx.oxml", "docx.oxml.ns", "docx.text.run"}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert len(source.splitlines()) <= 300
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == ["set_east_asian_font"]
    assert all(node.end_lineno - node.lineno + 1 <= 50 for node in functions)


def test_both_renderers_depend_on_fonts_without_an_omml_reverse_import():
    graph, _ = scan_application(APP)
    docx = "app.services.export.docx_exporter"
    omml = "app.services.export.omml_converter"
    fonts = "app.services.export.docx_fonts"
    assert graph[fonts] == set()
    assert fonts in graph[docx]
    assert fonts in graph[omml]
    assert omml in graph[docx]
    assert docx not in graph[omml]
    tree = ast.parse((APP / "services/export/docx_exporter.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "_set_east_asian_font"
                   for node in ast.walk(tree))


def test_fresh_raw_formula_fallback_does_not_import_the_document_exporter():
    probe = """
import sys
from app.services.export import omml_converter
assert 'docx' not in sys.modules
assert 'app.services.export.docx_fonts' not in sys.modules
from docx import Document
omml_converter.latex_to_omml_xml = lambda *args: None
paragraph = Document().add_paragraph()
assert omml_converter.render_latex_as_omml_or_fallback(
    'synthetic', False, paragraph, fallback_png=False,
) is False
assert paragraph.text == ' [公式] synthetic '
assert 'app.services.export.docx_exporter' not in sys.modules
assert 'app.core.database' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
