"""Export request responsibilities, route contracts and import isolation."""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWNERS = {
    "preview_export_count": "api_queries",
    "list_exports": "api_queries",
    "get_export": "api_queries",
    "_get_user_task": "api_queries",
    "_task_to_config": "api_queries",
    "_build_idempotency_key": "api_queries",
    "_find_existing_task": "api_queries",
    "_sort_dict": "api_queries",
    "create_export": "api_creation",
    "download_export": "api_downloads",
    "stream_export_file": "api_downloads",
    "_resolve_local_path": "api_downloads",
    "_url_encode_filename": "api_downloads",
    "_mime_for_format": "api_downloads",
    "delete_export": "api_deletion",
    "retry_export": "api_regeneration",
    "re_export": "api_regeneration",
    "_task_to_response": "api_projection",
    "export_status_ws": "api_websocket",
}
FUNCTIONS = {
    "api_creation": [
        "create_export",
        "check_creation_capacity",
        "create_and_commit_task",
    ],
    "api_deletion": ["delete_export", "stage_snapshot_deletion", "delete_stored_file"],
    "api_downloads": [
        "download_export",
        "stream_export_file",
        "_resolve_local_path",
        "_url_encode_filename",
        "_mime_for_format",
        "local_download_info",
        "remote_download_info",
    ],
    "api_projection": [
        "_task_to_response",
        "pending_status_warning",
        "build_task_response",
    ],
    "api_queries": [
        "preview_export_count",
        "list_exports",
        "get_export",
        "_get_user_task",
        "_task_to_config",
        "_build_idempotency_key",
        "_find_existing_task",
        "_sort_dict",
    ],
    "api_regeneration": [
        "retry_export",
        "re_export",
        "create_retry_task",
        "validate_reexport_snapshot",
        "reset_reexport_state",
    ],
    "api_websocket": ["export_status_ws", "serve_authenticated_socket"],
}
METADATA = {
    "_mime_for_format": "9d159826b47c473c37912e44e83014591b765c0137aeea3055be544a024fbd6b",
    "_wake_local_export_processor": "9270a0cab072e911ea3fb03291c14d0a442c5437b96653f3fa28d0794e886d9e",
    "export_health": "c3e24cc4521685a3798f03e76661cdb2aaa94fedad2f14e0e9a922d7be40e50f",
    "export_capabilities": "9abed01594c8b58a44cecadb435e3a559a91237cc0cdbfdbd62947933a9f45b1",
    "preview_export_count": "386a8d9453bb79ec79ccdd52b2b9796d09cf02a8fbe9885adfd118f67b81c76d",
    "create_export": "2e156d0450f11f65e59fb732b3af56780be422a5abdc7980d316630d51a99a8d",
    "list_exports": "aa8379f607879d3fd2393bb4bc3a70338a5d6e1553ee8b1b81d5d54dcd791433",
    "get_export": "4b0d39be73f598204de1f3a1df5d4978fdc84b2710b14fe46a6b89b2ee1d469c",
    "download_export": "4573f2f2de1926649ce3fe9c511c5bb91161b38529351ab255aa2feaf63d33e8",
    "stream_export_file": "409c8d2682e6a67e4f952d66401224113a1fe65f89e53aaa489457bc0a832fa5",
    "delete_export": "b3368ccd3b6cc2533b51921cdd70ee704d8a025a55bee6a9ddf1bf4a700853fc",
    "retry_export": "39e4ed3c42932a3b215a2eb647e54a49174532eeb06511ee6f8a19eae2f10a74",
    "re_export": "125a22bdd188af32912fd79dbadd5f9a5382dc8ae57108c0d9e781119a4d1a4e",
    "export_status_ws": "bc0c46f2ba6ec990d7dff2d7ee0aff9bf156611a766904f5d66555f3067a08fb",
    "_get_user_task": "56362eef21bf98d33c398c9b4516256f2141f6df0c51d1f5183d5b950c0bd5b6",
    "_task_to_response": "ab915d3ef32ffa4415d762fe25a905b9afedb03d816b03db96e6b470b9edfa40",
    "_task_to_config": "b57edfe900414906efc91ebcbb7e1f14a064287f8f1cf8db1e66837213ac78ae",
    "_build_idempotency_key": "5756f68a77c155f454a76e885a3e7a7fda4bc57374c8d890e1f7cc0dc9bf1337",
    "_find_existing_task": "504cf77640106e2bc840d0198d455cd41d883ae6db816829afe2b90efe6d9066",
    "_resolve_local_path": "f395567b7e11267922391627b1355da184fdc1ec52d0c3d93a01d99ab77e4d34",
    "_sort_dict": "437f584ecdf2e601183261b567e74b51a336ed0a438d98f0046e3504a417c4dd",
    "_url_encode_filename": "0a4ef9bee79a08fedd52e7c3f17ed2b850d5229b913a9dcd520dd76bfd2890c8",
}
UNCHANGED = {
    "_wake_local_export_processor": "dd9b68c6605c21ff07efeb37386f5b72c8f683b77e1bdf74dbbb1ab1f9c905de",
    "export_health": "ed3f697f264d6787d72918976e150041da90788f9f9c22be169ab693498fec0e",
    "export_capabilities": "db1adee9018c5052a0d3e319edf193caafe4aab92ce6578adf190b261b1a5e9d",
}


def digest(node):
    return hashlib.sha256(ast.dump(node).encode()).hexdigest()


def validate_modules(sources):
    assert set(sources) == set(FUNCTIONS)
    for name, source in sources.items():
        assert len(source.splitlines()) <= 300, name
        tree = ast.parse(source)
        functions = [
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert [n.name for n in functions] == FUNCTIONS[name], name
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 50, node.name
                assert not node.decorator_list
                assert "ports" in [arg.arg for arg in node.args.kwonlyargs]
            elif isinstance(node, ast.ImportFrom):
                assert node.module == "__future__"
            else:
                assert isinstance(node, ast.Expr) and isinstance(
                    node.value, ast.Constant
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.api")
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("app.api") for alias in node.names)


def sources():
    return {
        name: (ROOT / "backend/app/services/export" / (name + ".py")).read_text()
        for name in FUNCTIONS
    }


def test_responsibility_modules_have_bounded_functions_and_one_way_imports():
    validate_modules(sources())


def test_original_route_declarations_and_thin_entrypoints_are_preserved():
    tree = ast.parse((ROOT / "backend/app/api/v1/exports.py").read_text())
    funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(funcs) == set(METADATA) | {"_export_api_port"}
    for name, expected in METADATA.items():
        node = funcs[name]
        meta = ast.Tuple(
            elts=[
                node.args,
                ast.List(elts=node.decorator_list, ctx=ast.Load()),
                node.returns or ast.Constant(None),
                ast.Constant(ast.get_docstring(node, clean=False)),
            ],
            ctx=ast.Load(),
        )
        assert digest(meta) == expected, name
        if name in UNCHANGED:
            assert digest(node) == UNCHANGED[name]
        else:
            body = node.body[1:] if ast.get_docstring(node) is not None else node.body
            assert len(body) == 1 and isinstance(body[0], ast.Return), name
            value = body[0].value
            if isinstance(node, ast.AsyncFunctionDef):
                assert isinstance(value, ast.Await), name
                value = value.value
            assert isinstance(value, ast.Call), name
            assert ast.unparse(value.func) == "_export_" + OWNERS[name] + "." + name
            assert [ast.unparse(arg) for arg in value.args] == [
                arg.arg for arg in node.args.args
            ]
            expected_kwargs = {arg.arg: arg.arg for arg in node.args.kwonlyargs}
            expected_kwargs["ports"] = "_export_api_port"
            assert {
                kw.arg: ast.unparse(kw.value) for kw in value.keywords
            } == expected_kwargs


def test_fresh_import_has_no_route_framework_database_or_config_side_effects():
    code = "import importlib, sys; modules = " + repr(list(FUNCTIONS)) + "; "
    code += (
        "[importlib.import_module('app.services.export.' + name) for name in modules]; "
    )
    code += "assert not any(name in sys.modules for name in "
    code += (
        repr(
            [
                "fastapi",
                "sqlalchemy",
                "app.core.database",
                "app.core.config",
                "app.api.v1.exports",
                "app.models.export_task",
            ]
        )
        + ")"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    ["runtime_import", "reverse_import", "unbounded_function", "extra_function"],
)
def test_module_gate_rejects_boundary_and_budget_drift(mutation):
    candidates = sources()
    name = "api_creation"
    if mutation == "runtime_import":
        candidates[name] = "import sqlalchemy\n" + candidates[name]
    elif mutation == "reverse_import":
        candidates[name] = candidates[name].replace(
            "async def create_export(req, db, current_user, *, ports):",
            "async def create_export(req, db, current_user, *, ports):\n    from app.api.v1 import exports",
        )
    elif mutation == "unbounded_function":
        candidates[name] = candidates[name].replace(
            "async def create_export(req, db, current_user, *, ports):",
            "async def create_export(req, db, current_user, *, ports):"
            + "\n    pass" * 51,
        )
    else:
        candidates[name] += "\n\ndef unexpected():\n    pass\n"
    with pytest.raises(AssertionError):
        validate_modules(candidates)
