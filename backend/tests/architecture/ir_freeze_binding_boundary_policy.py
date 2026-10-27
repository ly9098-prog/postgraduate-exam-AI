"""Explicit pure-rule capabilities; source capture is confined to the builder."""

import ast

MODULES = {
    "freeze_source_binding": {
        "block_snapshot",
        "begin_source_capture",
        "_region_snapshot",
        "record_region_source",
        "finish_source_capture",
        "_option_snapshots",
        "binding_checksum",
        "source_binding_fields",
        "legacy_source_binding_fields",
        "bind_legacy_result",
    },
    "question_freeze_binding": {
        "reject_binding",
        "_source_options",
        "_valid_plan_envelope",
        "_region_sources",
        "_valid_options",
        "_source_spans",
        "_question_sources",
        "_merge_question_options",
        "resolve_question_bindings",
        "question_bound_options",
    },
    "pipeline_split_binding": {
        "_uses_ir_binding",
        "initialize_split_binding",
        "execute_split_questions",
        "finalize_split_binding",
    },
}
IMPORTS = {
    "freeze_source_binding": {
        "__future__": {"annotations"},
        "collections.abc": {"Mapping"},
        "typing": {"Any"},
        "hashlib": set(),
        "json": set(),
    },
    "question_freeze_binding": {
        "__future__": {"annotations"},
        "collections.abc": {"Mapping"},
        "bisect": {"bisect_left", "bisect_right"},
        "app.features.freeze_source_binding": {"binding_checksum", "block_snapshot"},
    },
    "pipeline_split_binding": {
        "__future__": {"annotations"},
        "collections.abc": {"Callable"},
        "typing": {"Any"},
        "app.features.pipeline_split_state": {"SplitState"},
    },
}
# Allowed calls, local stores, noncall attributes, subscript-store roots.
RULES = {
    "block_snapshot": (
        "block.get|hashlib.sha256|hashlib.sha256().hexdigest|isinstance|text.encode|type",
        "index page text",
        "",
        "",
    ),
    "begin_source_capture": (
        "all|block_snapshot|enumerate|id|len|set",
        "block coordinates index source sources",
        "document._freeze_source_capture|document.document_id",
        "",
    ),
    "_region_snapshot": (
        "'\\n'.join|'\\n'.join().encode|hashlib.sha256|hashlib.sha256().hexdigest",
        "line",
        "line.text|region.lines|region.region_id|region.revision",
        "",
    ),
    "record_region_source": (
        "_region_snapshot|capture['regions'].append|id",
        "capture",
        "document._freeze_source_capture",
        "",
    ),
    "finish_source_capture": (
        "document._freeze_source_capture.pop",
        "",
        "document._freeze_source_capture",
        "",
    ),
    "_option_snapshots": (
        "all|any|bool|dict|isinstance|options.items|registry.items|set",
        "key known_regions options region snapshots value",
        "",
        "snapshots",
    ),
    "binding_checksum": (
        "encoded.encode|hashlib.sha256|hashlib.sha256().hexdigest|json.dumps|plan.items",
        "encoded key payload value",
        "",
        "",
    ),
    "source_binding_fields": (
        "_option_snapshots|_region_snapshot|binding_checksum|capture.get|dict|getattr|"
        "isinstance|len|options.get|set",
        "capture current ids item options page plan recorded region regions source",
        "document.document_id|document.pages|page.page_index|page.regions",
        "plan",
    ),
    "legacy_source_binding_fields": (
        "getattr|isinstance|any|capture.get|registry.items|source_binding_fields",
        "capture coordinates item source key by_region value",
        "",
        "coordinates",
    ),
    "bind_legacy_result": (
        "getattr|legacy_source_binding_fields|result.get|result.update",
        "fields",
        "",
        "",
    ),
    "reject_binding": (
        "binding.setdefault|binding.setdefault().setdefault|reasons.append",
        "reasons",
        "",
        "",
    ),
    "_source_options": (
        "_region_sources|_valid_options|_valid_plan_envelope|binding.get|block_snapshot|dict|"
        "entry.get|isinstance|len|plan.get|reject_binding",
        "block entry options plan regions result snapshots sources",
        "",
        "result",
    ),
    "_valid_plan_envelope": ("binding_checksum|isinstance|set|type", "", "", ""),
    "_region_sources": (
        "entry.get|indices.add|isinstance|set|type",
        "entry index indices region result",
        "",
        "result",
    ),
    "_valid_options": ("all|bool|isinstance|options.items", "key value", "", ""),
    "_source_spans": (
        "block.get|enumerate|len|spans.append|text.lstrip|text.rstrip",
        "block block_index by_coordinate coordinate end index offset page spans start text",
        "",
        "by_coordinate",
    ),
    "_question_sources": (
        "bisect_left|bisect_right|len|max|range|set|touched[question].append|unsafe.add",
        "_ first index limit owner owners position question source start starts stop touched unsafe",
        "",
        "owners",
    ),
    "_merge_question_options": (
        "options.get|options.get().items",
        "key merged source value",
        "",
        "merged",
    ),
    "resolve_question_bindings": (
        "'\\n'.join|_merge_question_options|_question_sources|_source_options|_source_spans|"
        "binding.get|block.get|len|reject_binding|touched.items",
        "_ block included index merged options original_text page question resolved sources "
        "spans touched unsafe",
        "",
        "resolved",
    ),
    "question_bound_options": (
        "binding.setdefault|diagnostics.get|dict|reject_binding|resolved.get",
        "diagnostics options",
        "",
        "diagnostics",
    ),
    "_uses_ir_binding": ("arguments.get", "", "", ""),
    "initialize_split_binding": (
        "_uses_ir_binding|state.keyword_arguments.get",
        "binding diagnostics",
        "state.extra_data|state.frozen_option_registry|state.ir_freeze_binding|"
        "state.keyword_arguments",
        "state.extra_data",
    ),
    "execute_split_questions": (
        "ports|ports()|state.layout_result.get",
        "arguments",
        "state.freeze_input_changed|state.frozen_option_registry|state.gap_tolerance|"
        "state.import_mode_str|state.ir_freeze_binding|state.layout_result|state.raw_questions|"
        "state.split_blocks|state.split_mode|state.structure",
        "state.ir_freeze_binding",
    ),
    "finalize_split_binding": (
        "question.get|sum",
        "diagnostics question",
        "state.ir_freeze_binding|state.raw_questions",
        "diagnostics",
    ),
}
ATTRIBUTE_WRITES = {
    "begin_source_capture": {"document._freeze_source_capture"},
    "initialize_split_binding": {"state.frozen_option_registry", "state.ir_freeze_binding"},
    "execute_split_questions": {"state.raw_questions"},
}
BUILTINS = {
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "getattr",
    "id",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "object",
    "range",
    "set",
    "sum",
    "str",
    "tuple",
    "type",
    "TypeError",
    "ValueError",
    "OverflowError",
    "RecursionError",
}


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return call_name(node.value) + "." + node.attr
    if isinstance(node, ast.Call):
        return call_name(node.func) + "()"
    return ast.unparse(node)


def inspect_capture(tree):
    function = next(n for n in tree.body if getattr(n, "name", "") == "blocks_to_document_ir")
    parents = {c: n for n in ast.walk(function) for c in ast.iter_child_nodes(n)}
    calls = {}
    expected = {
        "begin_source_capture": "begin_source_capture(doc, blocks)",
        "record_region_source": "record_region_source(doc, b, zero_based_idx, region)",
        "finish_source_capture": "finish_source_capture(doc)",
    }
    for name, expression in expected.items():
        found = [
            n
            for n in ast.walk(function)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
        ]
        assert len(found) == 1 and ast.unparse(found[0]) == expression
        calls[name] = found[0]
    begin, record, finish = (calls[name] for name in expected)
    assert parents[parents[begin]] is function and parents[parents[finish]] is function
    loop = parents[parents[record]]
    assert isinstance(loop, ast.For) and ast.unparse(loop.target) == "(bi, b)"
    assert ast.unparse(loop.iter) == "enumerate(page_b)"
    before = loop.body[: loop.body.index(parents[record])]
    assert any(
        isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "region"
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func) == "RegionIR"
        for n in before
    )
    assert any(
        isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value) == "regions.append(region)"
        for n in before
    )
    assert begin.lineno < record.lineno < finish.lineno
    assert isinstance(function.body[-1], ast.Return)
    assert ast.unparse(function.body[-1].value) == "doc"
    assert function.body.index(parents[finish]) == len(function.body) - 2


def inspect_split_wiring(tree):
    function = next(n for n in tree.body if getattr(n, "name", "") == "run_split_stage")
    calls = [
        call_name(n.value.func)
        for n in function.body
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
    ]
    assert calls.count("initialize_split_binding") == calls.count("execute_split_questions") == 1
    assert calls.index("resolve_split_options") < calls.index("initialize_split_binding")
    assert calls.index("initialize_split_binding") < calls.index("rebuild_split_input")
    assert calls.index("rebuild_split_input") < calls.index("execute_split_questions")
    assert calls.index("execute_split_questions") < calls.index("initialize_split_diagnostics")
