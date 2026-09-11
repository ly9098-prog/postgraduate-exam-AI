"""Regression tests for the CI migration helpers."""

import json
from pathlib import Path

from scripts.ci_collect_migration_checkpoints import collect_checkpoints
from scripts.ci_migration_matrix_check import _load_checkpoints


def test_collect_migration_checkpoints_is_a_non_empty_unique_chain():
    checkpoints = collect_checkpoints()

    assert checkpoints
    assert len(checkpoints) == len(set(checkpoints))
    assert checkpoints[-1] == "s408seq20260911"


def test_load_migration_checkpoints_rejects_invalid_shape(tmp_path: Path):
    path = tmp_path / "checkpoints.json"
    path.write_text(json.dumps({"revision": "head"}), encoding="utf-8")

    try:
        _load_checkpoints(path)
    except ValueError as exc:
        assert "non-empty JSON array" in str(exc)
    else:
        raise AssertionError("invalid checkpoint JSON was accepted")
