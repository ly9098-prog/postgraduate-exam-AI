"""验证迁移文件中的 CANONICAL_TYPES 与实际 QuestionType 枚举一致。"""

import importlib.util


def _load_migration_module():
    """从文件中加载迁移模块（alembic.versions 不是常规包，无法直接 import）。"""
    import os
    import sys

    # 定位迁移文件
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    """验证 v10 迁移文件中的 CANONICAL_TYPES 值与 QuestionType 枚举一致。

    如果 QuestionType 枚举有增减，v10 迁移中的 CANONICAL_TYPES 也必须同步更新。
    本测试在编译期捕获不一致，防止忘记更新迁移文件。
    """
    from app.features.question_type import QuestionType

    migration = _load_migration_module()
    migration_types = sorted(migration.CANONICAL_TYPES)

    enum_values = sorted(member.value for member in QuestionType)

    assert migration_types == enum_values, (
        f"迁移文件中的 CANONICAL_TYPES 与 QuestionType 枚举不一致。\n"
        f"迁移文件: {migration_types}\n"
        f"枚举定义: {enum_values}\n"
        f"如已修改 QuestionType 枚举，请同步更新 "
        f"alembic/versions/v10_question_type_check_constraints.py 中的 "
        f"CANONICAL_TYPES 列表。"
    )
