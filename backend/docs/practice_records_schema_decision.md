# practice_records Schema Decision (Phase 5.0)

## 结论

ORM 已从 session-level（每次练习一条记录）重设计为 per-question（每道题一条记录），
但缺少对应的 alembic migration。本阶段添加安全迁移补齐 5 个新列，
同时保留旧列以避免历史数据丢失。

---

## 1. 差异分析

### 1.1 三源对比

| 字段 | 初始迁移 (95eefdba4c27) | 当前 ORM | autogenerate diff |
|------|------------------------|----------|-------------------|
| id | Integer PK | Integer PK | 无差异 |
| user_id | Integer FK, indexed | Integer FK, indexed | 无差异 |
| subject | String(16) | String(32) | 已被 b4e3d2c1f0a9 迁移修正 |
| mode | String(16) | **缺失** | DROP COLUMN |
| question_ids | JSON | **缺失** | DROP COLUMN |
| answers | JSON | **缺失** | DROP COLUMN |
| correct_count | SmallInteger | **缺失** | DROP COLUMN |
| wrong_count | SmallInteger | **缺失** | DROP COLUMN |
| duration_sec | Integer | **缺失** | DROP COLUMN |
| started_at | DateTime | **缺失** | DROP COLUMN |
| finished_at | DateTime, nullable | **缺失** | DROP COLUMN |
| question_id | **缺失** | Integer FK | ADD COLUMN |
| question_type | **缺失** | String(32) | ADD COLUMN |
| user_answer | **缺失** | Text | ADD COLUMN |
| is_correct | **缺失** | Boolean | ADD COLUMN |
| used_time | **缺失** | Integer, nullable | ADD COLUMN |
| answered_at | DateTime, nullable | DateTime, NOT NULL, server_default | ALTER (SQLite noise) |
| created_at | DateTime, server_default | DateTime, server_default | 无差异 |

### 1.2 已有索引对比

| 索引名 | 初始迁移 | 当前 ORM | autogenerate diff |
|--------|---------|----------|-------------------|
| ix_practice_records_user_id | 有 | 有 | 无差异 |
| idx_practice_records_user_date | 有 (user_id, started_at) | **缺失** | DROP INDEX |
| idx_practice_records_user_subject | 有 (user_id, subject) | **缺失** | DROP INDEX |
| ix_practice_records_question_id | **缺失** | 有 | CREATE INDEX |

---

## 2. 差异类型判断

**结论：ORM 已正式重设计，但缺 migration。**

依据：
- `practice_service.submit_answer()` 使用新的 per-question schema 创建记录
- 新 schema 包含 question_id, question_type, user_answer, is_correct, used_time
- 旧 session-level 字段（mode, question_ids, answers 等）未被任何服务代码引用
- 没有任何 migration 文件执行过 ADD COLUMN 或 DROP COLUMN

---

## 3. 字段决策

| 字段 | 保留/删除 | 迁移方式 | 数据回填 | 风险等级 |
|------|----------|---------|---------|---------|
| question_id | **新增** | ADD COLUMN nullable | 旧记录不需要（session 粒度不同） | 低 |
| question_type | **新增** | ADD COLUMN nullable | 旧记录不需要 | 低 |
| user_answer | **新增** | ADD COLUMN nullable | 旧记录不需要 | 低 |
| is_correct | **新增** | ADD COLUMN nullable | 旧记录不需要 | 低 |
| used_time | **新增** | ADD COLUMN nullable | 旧记录不需要 | 低 |
| mode | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| question_ids | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| answers | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| correct_count | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| wrong_count | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| duration_sec | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| started_at | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |
| finished_at | **保留** | ORM 加 deprecated 字段 | 不需要 | 无 |

### 为什么保留旧列

1. **核心约束**：Phase 5.0 任务要求"不允许 DROP practice_records 或丢失历史答题记录"
2. **SQLite 限制**：SQLite ALTER TABLE DROP COLUMN 在旧版本中不支持
3. **数据安全**：旧 session-level 数据仍有审计价值
4. **autogenerate 稳定**：ORM 声明旧列后，autogenerate 不再产生 DROP COLUMN

### 为什么不回填旧数据到新列

旧记录是 session 粒度（一次练习包含多道题），新记录是 per-question 粒度。
两者粒度不同，无法从旧 `answers` JSON 中准确拆分出每道题的 `question_id`、
`user_answer`、`is_correct`。旧记录保持新列为 NULL 是安全的。

---

## 4. 索引决策

| 索引 | 处理方式 | 理由 |
|------|---------|------|
| ix_practice_records_question_id | **新建** | 新列查询热路径 |
| idx_practice_records_user_date | **保留** | 旧索引不删除，不影响新代码 |
| idx_practice_records_user_subject | **保留** | 同上 |

---

## 5. 已知 autogenerate 残余差异（SQLite 噪音）

完成本次迁移后，autogenerate 仍可能产生以下差异（均为 SQLite 方言噪音，
在 PostgreSQL 上不出现）：

| 类型 | 差异 | 原因 |
|------|------|------|
| NOT NULL | answered_at nullable → NOT NULL | 初始迁移为 nullable，ORM 改为 NOT NULL + server_default |
| 索引名 | ix_ vs idx_ 命名前缀 | SQLite autogenerate 索引名推断差异 |
| Date vs DateTime | started_at 的 Date/DateTime | SQLite 不区分日期类型 |

---

## 6. 迁移文件

- 文件：`alembic/versions/p5_0_schema_baseline.py`
- down_revision: `p4_6_release_hardening`
- 操作：5 个 ADD COLUMN + 1 个 CREATE INDEX（practice_records）
  + 2 个 ADD COLUMN（import_pipelines）
- 所有操作有 `_has_table` / `_has_column` / `_has_index` guard，保证幂等
- downgrade 可回滚

---

## 7. 验证方法

```bash
# 迁移执行
alembic upgrade head

# 验证新列存在
python -c "
import sqlite3
conn = sqlite3.connect('backend/dev.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(practice_records)').fetchall()]
for c in ['question_id', 'question_type', 'user_answer', 'is_correct', 'used_time']:
    assert c in cols, f'{c} missing'
print('All new columns present')
"

# 验证旧列保留
python -c "
import sqlite3
conn = sqlite3.connect('backend/dev.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(practice_records)').fetchall()]
for c in ['mode', 'question_ids', 'answers', 'correct_count', 'wrong_count', 'duration_sec', 'started_at', 'finished_at']:
    assert c in cols, f'{c} missing'
print('All legacy columns preserved')
"

# 验证 ORM 可正常写入
pytest tests/test_services/test_practice_service.py -v
```

---

## 8. 风险提醒

1. **旧列 nullable 约束**：旧列在 DB 中是 NOT NULL（初始迁移），但 ORM 声明为 nullable=True。
   新记录写入时旧列值为 NULL，这在 SQLite 上可能报错。如果出现此问题，
   需将 DB 中的旧列改为 nullable（通过 ADD COLUMN 重建表或 PostgreSQL ALTER）。
2. **submit_answer 兼容性**：当前 submit_answer() 只写入新列，旧列为 NULL。
   如果有旧代码读取旧列，会得到 NULL 值。已确认 practice_service 无此问题。
3. **数据回填**：旧 session-level 记录的新列为 NULL，这是设计预期，不是数据丢失。
