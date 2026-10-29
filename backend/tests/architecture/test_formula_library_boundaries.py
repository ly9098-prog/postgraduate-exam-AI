"""The complete public formula chain stays behind bounded injected capabilities."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
ROLES = {
    "projection": "_card_to_response _graph_spec_to_dict _batch_load_tags _batch_load_specs",
    "catalog": "_build_category_tree _get_active_categories get_formula_catalog get_formula_tags",
    "filters": "_exam_scope_values _apply_study_card_type_filter _apply_library_type_filter _validate_chapter _apply_list_filters",
    "listing": "list_formulas list_favorite_formulas",
    "access": "get_random_formula get_formula_detail add_formula_favorite remove_formula_favorite",
}
HELPERS = {
    "projection": "load_card_tags load_card_graph_asset load_card_specs project_core_fields project_related_fields",
    "catalog": "inject_catalog_counts",
    "filters": "",
    "listing": "paginate_formula_cards",
    "access": "build_random_query pick_random_card",
}
PORTS = {
    "projection": "FormulaCardTag FormulaGraphAssetResponse FormulaGraphSpec FormulaTag _graph_spec_to_dict is_function_graph resolve_graph_asset_public_url select serialize_utc_datetime",
    "listing": "FormulaCard UserFormulaFavorite _apply_library_type_filter _apply_list_filters _apply_study_card_type_filter _batch_load_specs _batch_load_tags _card_to_response _exam_scope_values _validate_chapter choose_effective_graph_asset func list load_graph_assets_map paginated_response select",
    "access": "FormulaCard HTTPException UserFormulaFavorite ValueError _apply_library_type_filter _apply_list_filters _apply_study_card_type_filter _card_to_response _exam_scope_values func get_random_formula int random select",
    "filters": "EXAM408_FORMULA_SCOPE FormulaCard FormulaCardTag FormulaCategory FormulaGraphAsset FormulaTag HTTPException and_ apply_formula_subject_filter expand_formula_subject_code func len or_ select set str validate_study_card_type",
    "catalog": "FormulaCard FormulaCategory FormulaTag UserFormulaFavorite _apply_library_type_filter _apply_study_card_type_filter _build_category_tree _exam_scope_values _get_active_categories apply_formula_subject_filter collapse_formula_catalog_subjects formula_catalog_category_ids func list select",
}
METHODS = {
    "get",
    "append",
    "sort",
    "items",
    "strip",
    "lower",
    "scalars",
    "all",
    "scalar",
    "scalar_one_or_none",
    "join",
    "where",
    "order_by",
    "asc",
    "in_",
    "is_",
    "isnot",
    "exists",
    "notin_",
    "ilike",
    "group_by",
    "having",
    "label",
    "count",
    "subquery",
    "select_from",
    "offset",
    "limit",
    "split",
    "execute",
    "model_validate",
    "randint",
    "add",
    "delete",
    "commit",
}
IMPORTS = {
    "__future__": {"annotations"},
    "typing": {"TYPE_CHECKING"},
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.models.user": {"User"},
    "app.models.formula": {
        "FormulaCard",
        "FormulaCategory",
        "FormulaGraphAsset",
        "FormulaGraphSpec",
    },
    "app.services.formula_graph_asset_service": {"get_effective_graph_asset_for_card"},
}


def inspect_service(source, role):
    assert len(source.splitlines()) <= 300
    tree = ast.parse(source)
    definitions = [
        n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    expected = set((ROLES[role] + " " + HELPERS[role]).split())
    assert {n.name for n in definitions} == expected and len(definitions) == len(
        expected
    )
    for node in tree.body:
        assert isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ImportFrom, ast.If)
        ) or (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if isinstance(node, ast.If):
            assert isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    for node in ast.walk(tree):
        assert not isinstance(
            node, (ast.Import, ast.Global, ast.Nonlocal, ast.ClassDef, ast.Delete)
        )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.end_lineno - node.lineno + 1 <= 50 and not node.decorator_list
            assert node in definitions or (
                role == "catalog" and node.name == "_sort_tree"
            )
        if isinstance(node, ast.ImportFrom):
            assert not node.level and node.module in IMPORTS
            assert all(a.name in IMPORTS[node.module] for a in node.names)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id in expected | {
                    "ports",
                    "_sort_tree",
                    "get_effective_graph_asset_for_card",
                }
                if node.func.id == "ports":
                    assert len(node.args) == 1 and not node.keywords
                    assert (
                        isinstance(node.args[0], ast.Constant)
                        and node.args[0].value in PORTS[role].split()
                    )
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr in METHODS
                if node.func.attr in {"add", "delete", "commit"}:
                    owner = parents[node]
                    while not isinstance(
                        owner, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        owner = parents[owner]
                    assert role == "access" and owner.name in {
                        "add_formula_favorite",
                        "remove_formula_favorite",
                    }
                    assert (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "db"
                    )
            else:
                assert isinstance(node.func, ast.Call) and isinstance(
                    node.func.func, ast.Name
                )
                assert node.func.func.id == "ports"
    return tree


def inspect_route(source):
    tree = ast.parse(source)
    functions = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for role, names in ROLES.items():
        for name in names.split():
            function = functions[name]
            body = function.body
            if isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ):
                assert isinstance(body[0].value.value, str)
                body = body[1:]
            assert len(body) == 1 and isinstance(body[0], ast.Return)
            call = body[0].value
            if isinstance(function, ast.AsyncFunctionDef):
                assert isinstance(call, ast.Await)
                call = call.value
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            assert call.func.id == "library_" + name
            expected_args = [
                a.arg for a in function.args.posonlyargs + function.args.args
            ]
            assert all(isinstance(n, ast.Name) for n in call.args)
            assert [n.id for n in call.args] == expected_args
            assert [(k.arg, ast.unparse(k.value)) for k in call.keywords] == [
                *[(a.arg, a.arg) for a in function.args.kwonlyargs],
                ("ports", "_formula_library_port"),
            ]
            assert any(
                isinstance(n, ast.ImportFrom)
                and n.module == "app.services.formula_library_" + role
                and any(
                    a.name == name and a.asname == "library_" + name for a in n.names
                )
                for n in tree.body
            )


@pytest.mark.parametrize("role", ROLES)
def test_formula_library_capabilities_and_budgets(role):
    inspect_service(
        (APP / "services" / ("formula_library_" + role + ".py")).read_text(), role
    )


def test_routes_are_single_protocol_adapters():
    inspect_route((APP / "api/v1/formulas.py").read_text())


def test_service_imports_do_not_load_routes_database_or_models():
    modules = ["app.services.formula_library_" + role for role in ROLES]
    script = f"""
import importlib, sys
sys.path.insert(0, {str(APP.parent)!r})
for name in {modules!r}:
    importlib.import_module(name)
assert not any(name == 'fastapi' or name == 'sqlalchemy' or
               name.startswith(('app.api', 'app.models', 'app.core.config', 'app.core.database'))
               for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-I", "-c", script], check=True, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "injection",
    [
        "open('file')",
        "ports('open')('file')",
        "ports(name)()",
        "import subprocess",
        "from app.api.v1 import formulas",
        "db.commit()",
    ],
)
def test_gate_rejects_extra_io_or_ownership(injection):
    source = (
        (APP / "services/formula_library_listing.py").read_text()
        + "\n"
        + injection
        + "\n"
    )
    with pytest.raises(AssertionError):
        inspect_service(source, "listing")


def test_gate_rejects_bypassed_route():
    source = (APP / "api/v1/formulas.py").read_text()
    source = source.replace(
        "return await library_list_formulas(", "return await other(", 1
    )
    with pytest.raises(AssertionError):
        inspect_route(source)
