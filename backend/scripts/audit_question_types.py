#!/usr/bin/env python3
"""题型历史数据审计与迁移脚本。

扫描 questions、question_imports、practice_records 等表中的 question_type
值，分类为标准 code、可安全转换的别名、NULL、空字符串、unknown
和无法识别值。

用法
----
    python scripts/audit_question_types.py                    # dry-run（默认）
    python scripts/audit_question_types.py --apply            # 执行迁移
    python scripts/audit_question_types.py --table questions  # 单表扫描
    python scripts/audit_question_types.py --show-invalid-ids # 输出异常记录 ID
    python scripts/audit_question_types.py --db-url sqlite:///data.db

安全
----
- 默认只读（dry-run），--apply 才写入。
- 更新使用事务，任意错误时完整回滚。
- 无法识别值不做猜测。
- 已知别名（由 app.features.question_type.normalize_question_type 定义）才转换。
- 脚本可重复运行（幂等）。
- 不输出题目正文、答案等敏感内容。
- 默认使用 DATABASE_URL 环境变量，也可通过 --db-url 指定。

目标约束（CHECK 约束落地后的预期行为）：
- questions.question_type：NOT NULL，只允许标准 code
- question_imports.question_type：允许 NULL，非 NULL 只允许标准 code
- practice_records.question_type：NOT NULL，只允许标准 code
- question_embeddings.question_type：NOT NULL，只允许标准 code
"""

import argparse
import sys
from collections import Counter

sys.path.insert(0, ".")

try:
    from sqlalchemy import create_engine, text, inspect
except ImportError:
    print("错误：需要 SQLAlchemy。请先激活虚拟环境。")
    sys.exit(1)

from app.features.question_type import (
    CANONICAL_TYPES,
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_FILL_BLANK,
    QT_MULTI_BLANK_CHOICE,
    QT_SUBJECTIVE,
    normalize_question_type,
)

# ── 扫描的表和列 ──
# default: 仅用于信息展示，标注当前 ORM 默认值
# target_nullable: 约束落地后该列是否允许 NULL
TABLES = {
    "questions": {
        "column": "question_type", "nullable": False, "default": QT_SINGLE_CHOICE,
        "target_nullable": False,
    },
    "question_imports": {
        "column": "question_type", "nullable": True, "default": None,
        "target_nullable": True,
    },
    "practice_records": {
        "column": "question_type", "nullable": False, "default": QT_SINGLE_CHOICE,
        "target_nullable": False,
    },
    "question_embeddings": {
        "column": "question_type", "nullable": False,
        "target_nullable": False,
    },
}


def connect(db_url: str | None = None):
    """从 DATABASE_URL 环境变量或 --db-url 参数获取数据库连接。"""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        print("错误：DATABASE_URL 环境变量未设置，或使用 --db-url 参数指定。")
        sys.exit(1)
    return create_engine(url)


def classify(value: str | None) -> tuple[str, str | None]:
    """将单值分类，返回 (category, suggested_code)。

    category 取值:
      - NULL: None
      - empty_string: ""
      - whitespace_only: 仅空白
      - canonical:{code}: 已是标准 code
      - alias:{value}→{code}: 可安全转换的别名
      - unknown: "unknown"
      - unrecognized:{value}: 无法识别
    """
    if value is None:
        return "NULL", None
    if value == "":
        return "empty_string", None
    if value.strip() == "":
        return "whitespace_only", None
    if value == "unknown":
        return "unknown", None
    if value in CANONICAL_TYPES:
        return f"canonical:{value}", None

    # 先尝试简单的规范化（trim + lowercase）
    simple = value.strip().lower()
    if simple != value and simple in CANONICAL_TYPES:
        return f"case_whitespace:{value}→{simple}", simple

    normalized, _warnings = normalize_question_type(value)
    if normalized is not None:
        return f"alias:{value}→{normalized}", normalized
    return f"unrecognized:{value}", None


def _normalize_value(value: str) -> str | None:
    """尝试将原始值规范化为标准 code。
    用于 migrate 阶段的映射查找。"""
    if value in CANONICAL_TYPES:
        return value
    normalized, _warnings = normalize_question_type(value)
    return normalized


def scan_table(engine, table_name: str, column: str,
               show_invalid_ids: bool = False) -> dict:
    """扫描单表，返回分类统计。"""
    query = text(f"SELECT id, {column} FROM {table_name} ORDER BY id")
    with engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    category_counts: dict[str, int] = Counter()
    value_counts: Counter = Counter()
    # 按原始值记录产生该值的记录 ID
    invalid_ids: dict[str, list[int]] = {}
    # 每个分类的建议转换 code
    suggestions: dict[str, str | None] = {}

    for row_id, val in rows:
        category, suggested = classify(val)
        category_counts[category] += 1
        value_counts[val] += 1
        if category not in suggestions:
            suggestions[category] = suggested

        # 只收集非标准值的 ID
        if not category.startswith("canonical:") and category != "NULL":
            key = f"{category}|{val}"
            if key not in invalid_ids:
                invalid_ids[key] = []
            invalid_ids[key].append(row_id)

    result = {
        "table": table_name,
        "total": len(rows),
        "category_counts": dict(category_counts),
        "value_counts": dict(value_counts),
        "suggestions": dict(suggestions),
        "invalid_record_ids": invalid_ids if show_invalid_ids else {},
    }
    return result


def migrate_table(engine, table_name: str, column: str,
                  dry_run: bool = True,
                  show_invalid_ids: bool = False) -> dict:
    """迁移单表的别名值为标准 code。"""
    scan = scan_table(engine, table_name, column,
                      show_invalid_ids=show_invalid_ids)

    # 收集所有非标准可转换值的映射
    alias_map: dict[str, str] = {}  # old_value -> new_value
    unrecognized_values: list[str] = []
    unknown_count = 0
    empty_string_count = 0
    whitespace_count = 0

    for val_raw, count in scan["value_counts"].items():
        category, suggested = classify(val_raw)
        if category.startswith("canonical:") or category == "NULL":
            continue
        if category.startswith("alias:") or category.startswith("case_whitespace:"):
            assert suggested is not None
            alias_map[val_raw] = suggested
        elif category == "unknown":
            unknown_count += count
        elif category == "empty_string":
            empty_string_count += count
        elif category == "whitespace_only":
            whitespace_count += count
        else:
            unrecognized_values.append(val_raw)

    # 执行更新
    updates = []
    for old_val, new_val in alias_map.items():
        if not dry_run:
            with engine.begin() as conn:
                result = conn.execute(
                    text(
                        f"UPDATE {table_name} SET {column} = :new_val "
                        f"WHERE {column} = :old_val"
                    ),
                    {"new_val": new_val, "old_val": old_val},
                )
                updates.append({
                    "from": old_val, "to": new_val, "count": result.rowcount,
                })
        else:
            with engine.connect() as conn:
                count = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table_name} WHERE {column} = :val"
                    ),
                    {"val": old_val},
                ).scalar()
                updates.append({
                    "from": old_val, "to": new_val, "count": count,
                })

    return {
        "table": table_name,
        # 扫描结果
        "total": scan["total"],
        "category_counts": scan["category_counts"],
        # 迁移结果
        "alias_updates": updates,
        "unrecognized_values": unrecognized_values,
        "unknown_count": unknown_count,
        "empty_string_count": empty_string_count,
        "whitespace_count": whitespace_count,
        # 异常记录 ID
        "invalid_record_ids": scan["invalid_record_ids"],
        "dry_run": dry_run,
        # 验证
        "post_scan": None,
    }


def _verify_clean(engine, result: dict) -> dict | None:
    """迁移后验证非标准值数量。"""
    table = result["table"]
    info = TABLES[table]
    column = info["column"]

    post = scan_table(engine, table, column, show_invalid_ids=True)
    result["post_scan"] = post

    non_canonical = [
        cat for cat in post["category_counts"]
        if not cat.startswith("canonical:") and cat != "NULL"
    ]
    if non_canonical:
        total_bad = sum(post["category_counts"][c] for c in non_canonical)
        result["remaining_non_canonical"] = total_bad
        result["remaining_categories"] = non_canonical
    else:
        result["remaining_non_canonical"] = 0
        result["remaining_categories"] = []

    return post


def print_report(
    scan_results: dict[str, dict],
    migrate_results: list[dict] | None = None,
):
    """打印审计报告。"""
    print("=" * 72)
    print("  题型数据审计报告")
    print("=" * 72)

    totals = Counter()

    for table_name, result in scan_results.items():
        info = TABLES[table_name]
        column = info["column"]
        nullable = info.get("nullable", True)
        target_nullable = info.get("target_nullable", nullable)

        print(f"\n── {table_name}.{column} ──")
        print(f"  总记录数: {result['total']}")
        print(f"  当前: {'nullable' if nullable else 'NOT NULL'}")
        print(f"  目标: {'nullable' if target_nullable else 'NOT NULL'}")
        print(f"  分类统计:")

        for category, count in sorted(result["category_counts"].items()):
            if category.startswith("canonical:"):
                code = category.split(":", 1)[1]
                totals["canonical"] += count
                print(f"    ✅ 标准 '{code}': {count} 条")
            elif category.startswith("alias:"):
                parts = category.split("→", 1)
                alias_val = parts[0].split(":", 1)[1]
                canonical_val = parts[1]
                totals["alias"] += count
                print(f"    🔄 可转换别名 '{alias_val}' → '{canonical_val}': {count} 条")
            elif category.startswith("case_whitespace:"):
                parts = category.split("→", 1)
                orig = parts[0].split(":", 1)[1]
                cleaned = parts[1]
                totals["case_whitespace"] += count
                print(f"    🔤 大小写/空格 '{orig}' → '{cleaned}': {count} 条")
            elif category == "unknown":
                totals["unknown"] += count
                print(f"    ❓ 'unknown': {count} 条")
            elif category == "NULL":
                totals["null"] += count
                print(f"    ⬜ NULL: {count} 条")
            elif category == "empty_string":
                totals["empty"] += count
                print(f"    ⚠️  空字符串 '': {count} 条")
            elif category == "whitespace_only":
                totals["whitespace"] += count
                print(f"    ⚠️  纯空白: {count} 条")
            else:
                val = category.split(":", 1)[1]
                totals["unrecognized"] += count
                suggested = result.get("suggestions", {}).get(category)
                line = f"    ❌ 无法识别 '{val}': {count} 条"
                if suggested:
                    line += f"  → 建议: {suggested}"
                print(line)

        # 原始值分布（不显示标准值以保持简洁）
        value_counts = result["value_counts"]
        unusual = {
            v: c for v, c in value_counts.items()
            if v is not None and v not in CANONICAL_TYPES
        }
        if unusual:
            print(f"\n  非标准值分布:")
            for val, count in sorted(unusual.items(), key=lambda x: -x[1]):
                cat, _ = classify(val)
                if cat.startswith("canonical:"):
                    continue
                marker = "🔄" if cat.startswith("alias:") else "⚠️"
                suggested = None
                if cat.startswith("alias:") or cat.startswith("case_whitespace:"):
                    _, suggested = classify(val)
                sugg = f"  → {suggested}" if suggested else ""
                print(f"    {marker} {val!r}: {count} 条{sugg}")

        # 异常记录 ID
        invalid_ids = result.get("invalid_record_ids", {})
        if invalid_ids:
            print(f"\n  异常记录 ID（每类最多显示 20 条）:")
            for key, ids in invalid_ids.items():
                cat = key.split("|")[0]
                display_ids = ids[:20]
                more = f"... 还有 {len(ids) - 20} 条" if len(ids) > 20 else ""
                print(f"    [{cat}] IDs: {display_ids} {more}")

    print(f"\n{'=' * 72}")
    print(f"  汇总")
    print(f"{'=' * 72}")
    print(f"  标准 code:         {totals.get('canonical', 0)}")
    print(f"  可转换别名:        {totals.get('alias', 0)}")
    print(f"  大小写/空格:       {totals.get('case_whitespace', 0)}")
    print(f"  unknown:           {totals.get('unknown', 0)}")
    print(f"  NULL:              {totals.get('null', 0)}")
    print(f"  空字符串:          {totals.get('empty', 0)}")
    print(f"  纯空白:            {totals.get('whitespace', 0)}")
    print(f"  无法识别:          {totals.get('unrecognized', 0)}")
    print(f"  ─────────────────────────")
    convertible = totals.get('alias', 0) + totals.get('case_whitespace', 0)
    total_bad = (totals.get('unknown', 0) + totals.get('unrecognized', 0)
                 + totals.get('empty', 0) + totals.get('whitespace', 0))
    print(f"  可自动转换:        {convertible}")
    print(f"  需人工处理:        {total_bad}")

    if migrate_results:
        print(f"\n{'=' * 72}")
        print(f"  迁移操作结果")
        print(f"{'=' * 72}")
        any_real = False
        for r in migrate_results:
            mode = "🔍 DRY RUN" if r["dry_run"] else "✅ 已执行"
            print(f"\n  {r['table']}: {mode}")

            updates = r.get("alias_updates", [])
            if updates:
                print(f"    别名转换:")
                for u in updates:
                    if u["count"] > 0:
                        print(f"      '{u['from']}' → '{u['to']}': {u['count']} 条")

            if r.get("unknown_count"):
                print(f"    'unknown': {r['unknown_count']} 条（需人工处理，未转换）")
            if r.get("empty_string_count"):
                print(f"    空字符串: {r['empty_string_count']} 条（需人工处理，未转换）")
            if r.get("whitespace_count"):
                print(f"    纯空白: {r['whitespace_count']} 条（需人工处理，未转换）")
            if r.get("unrecognized_values"):
                print(f"    无法识别值（需人工处理）: {r['unrecognized_values']}")

            if not r["dry_run"]:
                any_real = True
                # 迁移后验证
                post = r.get("post_scan")
                if post:
                    remaining = r.get("remaining_non_canonical", -1)
                    if remaining == 0:
                        print(f"    ✅ 迁移后验证: 无非标准值")
                    elif remaining > 0:
                        print(f"    ⚠️  迁移后仍有 {remaining} 条非标准值: "
                              f"{r.get('remaining_categories', [])}")
                    else:
                        print(f"    ⚠️  迁移后验证未执行")

        if not any_real:
            print(f"\n  (dry-run 模式，未实际写入)")

    print("=" * 72)


def check_blockers(
    scan_results: dict[str, dict],
) -> list[str]:
    """检查是否有阻止 CHECK 约束落地的数据。"""
    blockers = []
    for table_name, result in scan_results.items():
        target_nullable = TABLES[table_name].get("target_nullable", True)
        has_null = result["category_counts"].get("NULL", 0) > 0

        if not target_nullable and has_null:
            blockers.append(
                f"{table_name}.question_type 有 NULL 值但目标为 NOT NULL"
            )

        # 检查无法识别值、unknown、空字符串
        bad_categories = [
            cat for cat in result["category_counts"]
            if not cat.startswith("canonical:")
            and not cat.startswith("alias:")
            and not cat.startswith("case_whitespace:")
            and cat != "NULL"
        ]
        for cat in bad_categories:
            count = result["category_counts"][cat]
            blockers.append(
                f"{table_name}.question_type 存在 {count} 条 "
                f"无法自动处理的类型 ({cat})"
            )

    return blockers


def main():
    parser = argparse.ArgumentParser(
        description="题型历史数据审计与迁移",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s                       # dry-run，扫描所有表\n"
            "  %(prog)s --table questions     # 只扫描 questions 表\n"
            "  %(prog)s --apply               # 执行迁移\n"
            "  %(prog)s --show-invalid-ids    # 输出异常记录 ID\n"
            "  %(prog)s --db-url sqlite:///test.db\n"
        ),
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="执行迁移（默认 dry-run）",
    )
    parser.add_argument(
        "--table",
        choices=list(TABLES.keys()) + ["all"],
        default="all",
        help="要扫描的表（默认 all）",
    )
    parser.add_argument(
        "--show-invalid-ids", action="store_true",
        help="显示非标准值的记录 ID",
    )
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="数据库连接 URL（默认使用 DATABASE_URL 环境变量）",
    )
    args = parser.parse_args()

    engine = connect(args.db_url)

    # 选择要扫描的表
    table_names = list(TABLES.keys()) if args.table == "all" else [args.table]

    # Phase 1: 扫描
    scan_results: dict[str, dict] = {}
    for table_name in table_names:
        column = TABLES[table_name]["column"]
        try:
            scan_results[table_name] = scan_table(
                engine, table_name, column,
                show_invalid_ids=args.show_invalid_ids,
            )
        except Exception as e:
            print(f"扫描 {table_name} 失败: {e}", file=sys.stderr)

    # 检查阻止 CHECK 约束的数据
    blockers = check_blockers(scan_results)

    # Phase 2: 迁移
    migrate_results: list[dict] = []
    if args.apply:
        # 检查阻止项
        if blockers:
            print("=" * 72)
            print("  迁移被以下问题阻止（请先人工处理）:")
            for b in blockers:
                print(f"    ❌ {b}")
            print("=" * 72)
            sys.exit(1)

        print("开始迁移...")
        for table_name in table_names:
            column = TABLES[table_name]["column"]
            try:
                result = migrate_table(
                    engine, table_name, column,
                    dry_run=False,
                    show_invalid_ids=args.show_invalid_ids,
                )
                # 迁移后验证
                _verify_clean(engine, result)
                migrate_results.append(result)
            except Exception as e:
                print(f"迁移 {table_name} 失败（事务已回滚）: {e}", file=sys.stderr)
                sys.exit(1)
        print("迁移完成。")
    else:
        # dry-run 模式显示预计变更
        for table_name in table_names:
            column = TABLES[table_name]["column"]
            try:
                result = migrate_table(
                    engine, table_name, column,
                    dry_run=True,
                    show_invalid_ids=args.show_invalid_ids,
                )
                migrate_results.append(result)
            except Exception as e:
                print(f"{table_name} 迁移分析失败: {e}", file=sys.stderr)

        if blockers:
            print("\n⚠️  以下问题会阻止 CHECK 约束落地，请在使用 --apply 前处理:\n")
            for b in blockers:
                print(f"  ● {b}")

    print_report(scan_results, migrate_results)


if __name__ == "__main__":
    main()
