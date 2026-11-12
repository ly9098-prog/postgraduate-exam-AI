# 生产数据库导出

本目录包含 2026-11-13 从生产 PostgreSQL 导出的数据库 SQL：

| 文件 | 内容 |
| --- | --- |
| [`schema.sql`](schema.sql) | 全部业务表的结构、约束、索引和注释，不包含业务数据 |
| [`questions_formulas_data.sql`](questions_formulas_data.sql) | 题库与公式相关表的结构无关数据导出，仅包含 `INSERT` 语句 |

题库/公式数据覆盖 `questions`、`question_versions`、`question_imports`、`question_embeddings`、题目知识点映射，以及 `formula_*` 相关表和 `user_formula_favorites`。空表也会出现在数据文件元信息中。

恢复顺序：先恢复 `schema.sql`，再执行 `questions_formulas_data.sql`。该数据文件使用 `ON CONFLICT DO NOTHING`，包含向量扩展类型，恢复目标必须已安装 PostgreSQL 15 与 pgvector，并保持兼容的扩展和 schema。`formula_categories` 与 `formula_import_jobs` 存在环形外键，恢复前可能需要临时禁用触发器。

导出命令要点：结构使用 `pg_dump --schema-only`；题库/公式数据使用 `pg_dump --data-only --inserts --on-conflict-do-nothing`，并显式指定相关 `--table`。导出过程为只读查询，不修改生产数据。

除上述 README 和 SQL 文件外，不要向本目录提交数据库、备份、日志或任何运行时产物。
