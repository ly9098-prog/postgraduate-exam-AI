"""Knowledge-point service ownership, budget and pure-resolution-policy gates."""

import ast
from pathlib import Path

import pytest

from tests.architecture.dependency_scan import scan_application

APP = Path(__file__).resolve().parents[2] / "app"
MODULE = "app.services.knowledge_point_service"
RESOLUTION_MODULE = "app.services.knowledge_point_resolution"
FILE = APP / "services/knowledge_point_service.py"

FUNCTION_BUDGET = 50
# Frozen legacy ceiling: every future extraction must lower it, never raise it.
FILE_CEILING = 609

RESOLUTION_ENTRY = "resolve_knowledge_points"
SYNC_ENTRY = "sync_question_knowledge_points"
HELPERS = (
    "_resolve_entry_point",
    "_resolve_kp_entries",
    "_sync_summary",
    "_sync_without_subject",
    "_swap_question_positions",
    "_insert_missing_mappings",
    "_replace_question_mappings",
    "_append_missing_mappings",
)


def _functions(source: str) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def budget_violations(source: str) -> list[str]:
    violations = []
    if len(source.splitlines()) > FILE_CEILING:
        violations.append(f"file exceeds frozen ceiling {FILE_CEILING}")
    for name, node in _functions(source).items():
        size = node.end_lineno - node.lineno + 1
        if size > FUNCTION_BUDGET:
            violations.append(f"{name} is {size} lines")
    return violations


def _ordered(text: str, sequence) -> list[str]:
    violations = []
    positions = []
    for name in sequence:
        if name not in text:
            violations.append(f"lost {name}")
        else:
            positions.append(text.index(name))
    if positions != sorted(positions):
        violations.append("call order changed")
    return violations


def ownership_violations(source: str) -> list[str]:
    violations = []
    functions = _functions(source)
    for name in HELPERS:
        if name not in functions:
            violations.append(f"missing helper {name}")

    resolution = functions.get(RESOLUTION_ENTRY)
    if resolution is None:
        violations.append(f"missing entry {RESOLUTION_ENTRY}")
    else:
        text = ast.unparse(resolution)
        violations += _ordered(
            text,
            (
                "normalize_kp_input",
                "subject_id 不能为空",
                "_load_subject_knowledge_points",
                "_build_resolution_indexes",
                "_resolve_entry_point",
            ),
        )
        if "seen_ids" not in text:
            violations.append("resolution lost the identity dedupe")
        if "select(" in text or ".execute(" in text:
            violations.append("resolution entry owns SQL")

    entry_point = functions.get("_resolve_entry_point")
    if entry_point is not None:
        point_text = ast.unparse(entry_point)
        for fragment in (
            "_resolve_from_indexes",
            "block_inactive=create_if_missing",
            "_create_canonical_knowledge_point",
            "active_names[normalized] = point",
        ):
            if fragment not in point_text:
                violations.append(f"resolution policy lost {fragment}")

    sync = functions.get(SYNC_ENTRY)
    if sync is None:
        violations.append(f"missing entry {SYNC_ENTRY}")
    else:
        text = ast.unparse(sync)
        violations += _ordered(
            text,
            (
                "_sync_summary(0, 0, 0, 0)",
                "lock_question_for_revision",
                "normalize_kp_input",
                "_load_mappings",
                "_sync_without_subject",
                "_resolve_kp_entries",
                "_replace_question_mappings",
                "_append_missing_mappings",
                "db.flush",
                "_sync_summary(created, updated, deleted, len(entries))",
            ),
        )
        if "from app.services.question_revision_service import" not in text:
            violations.append("sync lost the revision lock import boundary")
        if "select(" in text or ".execute(" in text:
            violations.append("sync entry owns SQL")
        if "db.commit" in text or "db.rollback" in text:
            violations.append("sync entry owns the request transaction")

    without_subject = functions.get("_sync_without_subject")
    if without_subject is not None:
        text = ast.unparse(without_subject)
        for fragment in (
            "replace and existing",
            "db.delete",
            "db.flush",
            "has no subject, skip",
        ):
            if fragment not in text:
                violations.append(f"no-subject branch lost {fragment}")

    swap = functions.get("_swap_question_positions")
    if swap is not None:
        text = ast.unparse(swap)
        if "1000000" not in text.replace("_", ""):
            violations.append("position swap lost the temporary offset")
        if text.count("db.flush") != 2:
            violations.append("position swap lost its two-phase flush")

    insert = functions.get("_insert_missing_mappings")
    if insert is not None:
        text = ast.unparse(insert)
        for fragment in ("role='main'", "weight=1.0", "source=source", "base + offset"):
            if fragment not in text:
                violations.append(f"insert lost {fragment}")

    summary = functions.get("_sync_summary")
    if summary is not None:
        text = ast.unparse(summary)
        for key in ("changed", "created", "updated", "deleted", "total"):
            if f"'{key}'" not in text:
                violations.append(f"summary lost {key}")
    return violations


def test_knowledge_point_service_keeps_function_budget_and_frozen_ceiling():
    source = FILE.read_text(encoding="utf-8")
    assert budget_violations(source) == []


def test_knowledge_point_service_keeps_resolution_and_sync_ownership():
    assert ownership_violations(FILE.read_text(encoding="utf-8")) == []


def test_resolution_policy_stays_pure_and_service_keeps_dependencies():
    graph, _ = scan_application(APP)
    assert graph[RESOLUTION_MODULE] == set()
    dependencies = graph[MODULE]
    assert RESOLUTION_MODULE in dependencies
    assert "app.services.question_revision_service" in dependencies
    assert not any(
        name == "app.api" or name.startswith("app.api.") for name in dependencies
    )


def test_budget_gate_rejects_injected_long_function():
    source = FILE.read_text(encoding="utf-8")
    source += "def injected():\n" + "\n".join("    value = 1" for _ in range(50)) + "\n"
    assert "injected is 51 lines" in budget_violations(source)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "\n    await db.flush()\n    return _sync_summary(",
            "\n    return _sync_summary(",
            "lost db.flush",
        ),
        (
            "        block_inactive=create_if_missing,",
            "        block_inactive=False,",
            "lost block_inactive=create_if_missing",
        ),
        (
            "has no subject, skip",
            "skipped without subject",
            "no-subject branch lost has no subject, skip",
        ),
        (
            "    from app.services.question_revision_service import lock_question_for_revision\n",
            "    import app.services.question_revision_service as _revision\n",
            "lost the revision lock import boundary",
        ),
        (
            'role="main"',
            'role="aux"',
            "insert lost role='main'",
        ),
    ],
)
def test_ownership_gate_rejects_injected_mutations(old, new, expected):
    source = FILE.read_text(encoding="utf-8")
    assert old in source, old
    violations = ownership_violations(source.replace(old, new, 1))
    assert any(expected in violation for violation in violations), violations


def test_ownership_gate_rejects_removed_helper():
    source = FILE.read_text(encoding="utf-8")
    node = _functions(source)["_swap_question_positions"]
    lines = source.splitlines()
    mutated = "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno :]) + "\n"
    assert "missing helper _swap_question_positions" in ownership_violations(mutated)
