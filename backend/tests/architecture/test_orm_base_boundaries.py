"""Models and Alembic must share a declarative registry without creating an app engine."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
BASE = APP / "core/orm_base.py"


def test_neutral_base_has_one_standard_orm_dependency():
    source = BASE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [(node.module, [alias.name for alias in node.names])
               for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == [("sqlalchemy.orm", ["DeclarativeBase"])]
    assert not any(isinstance(node, (ast.Import, ast.Call)) for node in ast.walk(tree))
    assert len(source.splitlines()) <= 300


def test_model_graph_does_not_depend_on_runtime_database():
    graph, _ = scan_application(APP)
    assert graph["app.core.orm_base"] == set()
    assert "app.core.orm_base" in graph["app.core.database"]
    assert "app.models" in graph["app.core.database"]
    model_graph = {name: targets for name, targets in graph.items() if name.startswith("app.models")}
    assert model_graph
    for name, targets in model_graph.items():
        assert "app.core.database" not in targets, name
    owners = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "DeclarativeBase" for base in node.bases
            ):
                owners.append(path)
    assert owners == [BASE]


def test_fresh_model_registration_does_not_load_runtime_config_or_engine():
    probe = """
import sys
from app.core.orm_base import Base
assert not Base.metadata.tables
assert 'app.models' not in sys.modules
import app.models
from sqlalchemy.orm import configure_mappers
configure_mappers()
assert Base.metadata.tables
for mapper in Base.registry.mappers:
    assert issubclass(mapper.class_, Base)
    assert mapper.local_table.metadata is Base.metadata
for name in ('app.core.config', 'app.core.database'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_alembic_environment_uses_canonical_metadata_without_runtime_engine():
    probe = """
import runpy
import sys
from contextlib import nullcontext
from alembic import context
from alembic.config import Config
context.config = Config()
context.is_offline_mode = lambda: True
configured = []
context.configure = lambda **kwargs: configured.append(kwargs)
context.begin_transaction = nullcontext
context.run_migrations = lambda: None
runpy.run_path('alembic/env.py')
from app.core.orm_base import Base
assert len(configured) == 1
assert configured[0]['target_metadata'] is Base.metadata
assert Base.metadata.tables
assert 'app.core.database' not in sys.modules
assert 'app.core.config' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=APP.parent, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
