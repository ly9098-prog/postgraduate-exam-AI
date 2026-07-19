#!/usr/bin/env python3
"""Audit AI OCR Config Sources — Map admin_ai_model_configs / admin_ai_configs fields, relationships, and usage.

Output:
  reports/sprint4d/ai_config_schema_map.json
  reports/sprint4d/ai_config_call_graph.json
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

REPORTS_DIR = "reports/sprint4d"
os.makedirs(REPORTS_DIR, exist_ok=True)

BACKEND = Path(__file__).resolve().parent.parent / "app"


def audit_model_config_schema() -> dict:
    """Extract AdminAiModelConfig field definitions from the ORM model."""
    model_file = BACKEND / "models" / "admin_ai_config.py"
    source = model_file.read_text()
    tree = ast.parse(source)

    fields: dict[str, dict] = {}
    table_name = "admin_ai_model_configs"
    in_class = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AdminAiModelConfig":
            in_class = True
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                            if target.value.id == "Mapped":
                                col_name = target.attr
                                col_type = _extract_col_type(item.value)
                                fields[col_name] = {
                                    "column": col_name,
                                    "type": col_type,
                                    "nullable": "nullable=True" in source or "Optional" in source,
                                }

            # Get tablename from __tablename__
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__":
                            if isinstance(item.value, ast.Constant):
                                table_name = item.value.value

    return {
        "table_name": table_name,
        "model_class": "AdminAiModelConfig",
        "fields": [
            {
                "name": k,
                "type": v["type"],
            }
            for k, v in sorted(fields.items())
        ],
    }


def audit_config_schema() -> dict:
    """Extract AdminAiConfig field definitions."""
    model_file = BACKEND / "models" / "admin_ai_config.py"
    source = model_file.read_text()
    tree = ast.parse(source)

    fields: list[dict] = []
    table_name = "admin_ai_configs"

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AdminAiConfig":
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                            col_name = target.attr
                            col_type = _extract_col_type(item.value)
                            fields.append({
                                "name": col_name,
                                "type": col_type,
                            })
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__":
                            if isinstance(item.value, ast.Constant):
                                table_name = item.value.value

    return {
        "table_name": table_name,
        "model_class": "AdminAiConfig",
        "fields": fields,
    }


def _extract_col_type(node: ast.AST) -> str:
    """Extract column type string from mapped_column call or Column call."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "mapped_column":
                for kw in node.keywords:
                    if kw.arg is None and isinstance(kw.value, ast.Call):
                        inner = kw.value
                        if isinstance(inner.func, ast.Name):
                            return inner.func.id
                        if isinstance(inner.func, ast.Attribute):
                            return f"{inner.func.attr}"
                # Check positional args
                for arg in node.args:
                    if isinstance(arg, ast.Call) and hasattr(arg.func, "id"):
                        return arg.func.id
                return "unknown"
    return "unknown"


def audit_call_graph() -> dict:
    """Audit which files import from the model or service modules."""
    results: dict[str, list[str]] = {}
    pattern_modules = [
        "app.models.admin_ai_config",
        "app.services.admin_ai_config_service",
        "app.services.model_config_resolver",
    ]

    for py_file in sorted(BACKEND.rglob("*.py")):
        try:
            source = py_file.read_text()
        except Exception:
            continue
        rel = py_file.relative_to(BACKEND.parent.parent)
        for mod in pattern_modules:
            if mod.replace(".", "/") in source or f"from {mod}" in source or f"import {mod}" in source:
                results.setdefault(mod, []).append(str(rel))
                break  # count file once per module

    return results


def main():
    schema_map = {
        "admin_ai_model_configs": audit_model_config_schema(),
        "admin_ai_configs": audit_config_schema(),
        "relationship": (
            "admin_ai_configs is a flat key-value store config_key→config_value. "
            "admin_ai_model_configs stores per-model config with provider, endpoint, keys. "
            "There is NO foreign key relationship between the two tables — they are independent. "
            "admin_ai_configs keys (ocr_strategy_*, completion_*) are loaded by pipeline_orchestrator "
            "and question_ai_complete via get_all_configs(). "
            "admin_ai_model_configs is queried by model_config_resolver.resolve_active_model() "
            "for per-feature model resolution."
        ),
    }

    out = os.path.join(REPORTS_DIR, "ai_config_schema_map.json")
    with open(out, "w") as f:
        json.dump(schema_map, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    call_graph = audit_call_graph()
    out = os.path.join(REPORTS_DIR, "ai_config_call_graph.json")
    with open(out, "w") as f:
        json.dump(call_graph, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    print("Audit complete.")


if __name__ == "__main__":
    main()
