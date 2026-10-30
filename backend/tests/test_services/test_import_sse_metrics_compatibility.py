"""Pure-function compatibility baseline for the import SSE counter registry.

Pins the process-local counter dict keys, zero defaults, int value types,
mutable-dict semantics (single owner shared by reference), and the exact
key set consumed by runtime_sse_metrics / admin_imports so that later
refactors cannot silently rename a counter key (which would silently drop
it from the Prometheus output) or change the shared-owner contract that
admin_imports relies on for in-place mutation.
"""

from __future__ import annotations

import runpy
from unittest.mock import AsyncMock, patch

import pytest

import app.services.import_sse_metrics as module
from app.services.import_sse_metrics import counters


class TestCounterRegistryDefaults:
    """counters has exactly six SSE counter keys, all defaulting to zero."""

    def test_exact_key_set(self):
        assert set(counters.keys()) == {
            "active",
            "per_user_rejected",
            "global_rejected",
            "disconnected",
            "max_duration_closed",
            "max_idle_closed",
        }

    def test_key_count_is_six(self):
        assert len(counters) == 6

    def test_all_defaults_zero(self):
        # Earlier SSE tests may have incremented the live process counters.
        initialized = runpy.run_path(module.__file__)["counters"]
        assert all(v == 0 for v in initialized.values())

    def test_all_values_are_int(self):
        assert all(isinstance(v, int) for v in counters.values())

    def test_is_plain_dict(self):
        # Not a defaultdict, OrderedDict, or custom mapping — a plain dict so
        # attribute-style typos fail loudly instead of creating phantom keys
        assert type(counters) is dict


class TestSharedOwnerContract:
    """The dict is a single process-local owner shared by reference."""

    def test_module_attribute_identity(self):
        # Importers get the SAME dict object, not a copy per import
        assert module.counters is counters

    def test_mutation_visible_across_imports(self):
        # admin_imports mutates in place: counters["global_rejected"] += 1
        # Simulate and revert to avoid cross-test leakage
        original = counters["global_rejected"]
        try:
            counters["global_rejected"] += 1
            # A fresh import binding sees the mutation (same object)
            assert module.counters["global_rejected"] == original + 1
        finally:
            counters["global_rejected"] = original

    def test_inplace_increment_semantics(self):
        # The += pattern used by admin_imports works on every counter key
        for key in list(counters.keys()):
            original = counters[key]
            try:
                counters[key] += 1
                assert counters[key] == original + 1
            finally:
                counters[key] = original


class TestPrometheusProjectionContract:
    """runtime_sse_metrics renders each key as sse_<key> <value>."""

    def test_each_key_projected_with_sse_prefix(self):
        # The renderer iterates counters.items() and appends f"sse_{key} {v}".
        # Renaming a key here would change the exported metric name silently;
        # pin the six exact metric names the exporter must emit.
        expected_metric_names = {
            "sse_active",
            "sse_per_user_rejected",
            "sse_global_rejected",
            "sse_disconnected",
            "sse_max_duration_closed",
            "sse_max_idle_closed",
        }
        assert {f"sse_{k}" for k in counters} == expected_metric_names


class TestRendererOutputFormat:
    """append_sse_metrics emits each counter as 'sse_<key> <value>'."""

    @pytest.mark.asyncio
    async def test_renderer_emits_space_separated_key_value(self):
        import app.features.batch_image_import_service as batch_svc
        from app.services.runtime_sse_metrics import append_sse_metrics

        lines: list[str] = []
        # The renderer reads batch_svc._active_sse_connections; the attr is
        # created lazily by admin_imports at SSE time. Set and restore it.
        had_attr = hasattr(batch_svc, "_active_sse_connections")
        original = getattr(batch_svc, "_active_sse_connections", None)
        batch_svc._active_sse_connections = {"u1": 2, "u2": 1}
        try:
            with patch(
                "app.services.sse_pubsub.check_health",
                new=AsyncMock(return_value=True),
            ):
                await append_sse_metrics(lines)
        finally:
            if had_attr:
                batch_svc._active_sse_connections = original
            else:
                if hasattr(batch_svc, "_active_sse_connections"):
                    del batch_svc._active_sse_connections

        # Pin the exact 'sse_<key> <value>' format with a space separator
        for key, value in counters.items():
            assert f"sse_{key} {value}" in lines

    @pytest.mark.asyncio
    async def test_renderer_reflects_mutation(self):
        import app.features.batch_image_import_service as batch_svc
        from app.services.runtime_sse_metrics import append_sse_metrics

        lines: list[str] = []
        original = counters["global_rejected"]
        had_attr = hasattr(batch_svc, "_active_sse_connections")
        original_conns = getattr(batch_svc, "_active_sse_connections", None)
        batch_svc._active_sse_connections = {}
        counters["global_rejected"] = 7
        try:
            with patch(
                "app.services.sse_pubsub.check_health",
                new=AsyncMock(return_value=True),
            ):
                await append_sse_metrics(lines)
        finally:
            counters["global_rejected"] = original
            if had_attr:
                batch_svc._active_sse_connections = original_conns
            else:
                if hasattr(batch_svc, "_active_sse_connections"):
                    del batch_svc._active_sse_connections
        # The renderer reads the live dict, so the mutation is visible
        assert "sse_global_rejected 7" in lines


class TestAdminImportsMutationSites:
    """admin_imports mutates the exact six counter keys in place.

    A key rename at the call site would leave the registry and renderer
    intact while the counter silently stops incrementing. Pin the six
    mutation expressions via AST so the baseline catches call-site renames.
    """

    def test_admin_imports_mutates_all_six_counter_keys(self):
        import ast
        from pathlib import Path

        source_path = Path("app/api/v1/admin_imports.py").resolve()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        mutated_keys: set[str] = set()
        for node in ast.walk(tree):
            # Match both forms used by admin_imports:
            #   import_sse_metrics.counters["<key>"] += 1  (five counters)
            #   import_sse_metrics.counters["active"] = sum(...)  (gauge)
            targets: list[ast.expr] = []
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                targets = [node.target]
            elif isinstance(node, ast.Assign):
                targets = list(node.targets)
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "counters"
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "import_sse_metrics"
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    mutated_keys.add(target.slice.value)

        assert mutated_keys == {
            "active",
            "per_user_rejected",
            "global_rejected",
            "disconnected",
            "max_duration_closed",
            "max_idle_closed",
        }

    def test_admin_imports_uses_inplace_augmented_assignment(self):
        import ast
        from pathlib import Path

        source_path = Path("app/api/v1/admin_imports.py").resolve()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        counters_aug_assigns = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.Add)
            and isinstance(node.target, ast.Subscript)
            and isinstance(node.target.value, ast.Attribute)
            and node.target.value.attr == "counters"
            and isinstance(node.target.value.value, ast.Name)
            and node.target.value.value.id == "import_sse_metrics"
        ]
        # Five counters are incremented in place via +=; "active" is a
        # derived gauge assigned via = sum(active_conns.values()) and is
        # pinned separately below.
        assert len(counters_aug_assigns) == 5
        for node in counters_aug_assigns:
            assert isinstance(node.target.slice, ast.Constant)

    def test_active_counter_is_assigned_gauge(self):
        import ast
        from pathlib import Path

        source_path = Path("app/api/v1/admin_imports.py").resolve()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        active_assigns = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "sum"
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].slice, ast.Constant)
            and node.targets[0].slice.value == "active"
        ]
        assert len(active_assigns) == 1
