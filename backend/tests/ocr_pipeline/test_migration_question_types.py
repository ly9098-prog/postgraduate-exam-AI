"""验证迁移文件中的 CANONICAL_TYPES 与实际 QuestionType 枚举一致。"""

import importlib.util


def _load_migration_module():
    """从文件中加载迁移模块（alembic.versions 不是常规包，无法直接 import）。"""
    import os
    import sys

    # 定位迁移文件（tests/ocr_pipeline → backend 根目录需上溯两级）
    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    migration_path = os.path.join(
        backend_dir,
        "alembic",
        "versions",
        "v10_question_type_check_constraints.py",
    )

    spec = importlib.util.spec_from_file_location(
        "v10_question_type_check_constraints", migration_path
    )
    mod = importlib.util.module_from_spec(spec)
    # 避免加载模块时的 Alembic 环境依赖
    sys.modules["v10_question_type_check_constraints"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_migration_canonical_types_match_enum():
    """验证迁移链中所有 question_type CHECK 约束的并集与 QuestionType 枚举一致。

    v10 迁移记录了当时的 6 个题型快照；后续新增题型（如 v13 的
    multi_blank_multiple_choice）通过新迁移扩展 CHECK 约束。因此校验规则是：
    各迁移文件 CANONICAL_TYPES 的并集 == 当前 QuestionType 枚举。
    """
    from app.features.question_type import QuestionType

    migration = _load_migration_module()
    migration_types = set(migration.CANONICAL_TYPES)

    # 后续扩展题型约束的迁移文件（revision → CANONICAL_TYPES）
    import os
    import sys as _sys

    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    versions_dir = os.path.join(backend_dir, "alembic", "versions")
    v13_path = os.path.join(
        versions_dir, "v13_multi_blank_multiple_choice.py"
    )
    if os.path.exists(v13_path):
        spec13 = importlib.util.spec_from_file_location(
            "v13_multi_blank_multiple_choice", v13_path
        )
        mod13 = importlib.util.module_from_spec(spec13)
        _sys.modules["v13_multi_blank_multiple_choice"] = mod13
        spec13.loader.exec_module(mod13)
        migration_types |= set(mod13.CANONICAL_TYPES)

    enum_values = set(member.value for member in QuestionType)

    assert migration_types == enum_values, (
        f"迁移文件中的 CANONICAL_TYPES 并集与 QuestionType 枚举不一致。\n"
        f"迁移并集: {sorted(migration_types)}\n"
        f"枚举定义: {sorted(enum_values)}\n"
        f"如已修改 QuestionType 枚举，请新增迁移刷新 CHECK 约束并同步 "
        f"迁移中的 CANONICAL_TYPES 列表。"
    )
