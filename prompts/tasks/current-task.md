# 数据库 Schema 一致性修复与生产上线任务

**状态：进行中。** 本任务覆盖 ORM、Alembic、本地 SQLite、生产 PostgreSQL、CI 与权威数据库文档。不得删除业务数据，不改变公开 API/小程序协议，不合并语义相近但职责不同的业务表。

## 一、目标与边界

1. 恢复生产缺失的 `ai_feedback_logs`、`worker_credentials`。
2. 补齐 `formula_graph_specs` 主键、两组 adaptive 唯一约束和 `formula_graph_assets.reviewed_by` 外键。
3. 统一完整 ORM 注册，保护 PostgreSQL 专用 `question_embeddings`，使 `alembic check` 成为零漂移硬门禁。
4. 对齐 ORM 与数据库的 nullable、类型、注释、索引与约束。
5. 清理审计确认的 16 组、17 个完全冗余索引，不删除非等价性能索引。
6. 补全 `docs/backend/DB_SCHEMA.md`，并完成 SQLite/PostgreSQL 迁移回归与生产上线。

不在本任务中合并 `user_question_state` / `user_question_difficulty_state`、`practice_sessions` / `review_sessions` 或当前/版本知识点关联表。重复计数只明确口径并监控，不互相覆盖。

## 二、实施阶段

### Phase 1：核心结构完整性

新增 `v15_schema_integrity_core`（父版本 `v14_add_review_sessions`）：

- 幂等创建 `ai_feedback_logs`、`worker_credentials`；已有表必须校验结构并保留数据。
- 给 `formula_graph_specs.id` 增加 `pk_formula_graph_specs`。迁移前验证无 NULL、无重复；PostgreSQL 直接加约束，SQLite 用 batch recreate 保留数据、外键和索引。
- 增加 `uq_ukas_user_kp(user_id, knowledge_point_id)`、`uq_uqds_user_question(user_id, question_id)`、`fk_formula_graph_assets_reviewed_by_admin_users`。
- 重复行或外键孤儿存在时中止，不自动去重或删除。
- 将 `task_outbox.id` 映射改为 PostgreSQL BigInteger、SQLite Integer。
- downgrade 只撤销可安全撤销的约束，不删除可能已有数据的两张表。

### Phase 2：元数据与结构契约

- `app.models` 成为 78 张 ORM 表的完整显式注册入口；Alembic 与 `init_db()` 复用该入口。
- Alembic 只对 PostgreSQL 专用 `question_embeddings` 及其子对象设置精确排除，禁止 autogenerate 删除该表。
- 保留的数据库性能索引、部分索引、FK 删除策略和名称同步回 ORM metadata。
- 新增 `v16_schema_contract_alignment`：按当前业务默认值回填审计发现的 nullable 字段后设为 NOT NULL；补齐 `task_outbox` 字段注释。
- nullable 回填：时间用现有 `created_at`，仍为空则用迁移时间；计数为 0；`difficulty_level=3`、`is_active=true`、`role=main`、`weight=1.0`、`source=imported`。
- CI 的 `alembic check` 攓为硬门禁。

### Phase 3：冗余索引

新增 `v17_redundant_index_cleanup`：

- UNIQUE 与普通索引键相同时保留 UNIQUE，删除普通索引。
- `user_question_state(user_id, next_review_at)` 仅保留 `ix_user_question_state_user_next_review`。
- ORM 索引声明同步到最终结构，后续 autogenerate 不得重建已删除索引。
- 不删除非完全等价的前缀、部分、排序或运算符索引。

### Phase 4：语义与文档

- `user_question_state` 定义为 Leitner/复习调度投影；`user_question_difficulty_state` 定义为自适应难度观测，重复计数不可跨表替换。
- `practice_sessions/review_sessions`、当前/版本知识点关联、自适应状态/掌握状态保持独立。
- 补齐权威 `docs/backend/DB_SCHEMA.md` 中遗漏的 ORM 表、`review_sessions`、pgvector 表说明、关键主键/唯一约束/外键/索引和事实源。
- 根级 `docs/DB_SCHEMA.md` 继续仅作入口。
- 本地 SQLite 备份后升级到 head；仅在旧 PK 备份表为 0 行且正式表完整时清理它们。

## 三、兼容性

- 不改变公开 API、Pydantic schema 或小程序协议。
- `/api/v1/ai/feedback` 恢复生产持久化；`/api/internal/ocr-worker/*` 恢复数据库凭据认证并保留显式 legacy fallback。
- 迁移支持 PostgreSQL 15 与 SQLite；生产不执行 downgrade。
- 不删除或重建 `question_embeddings`，迁移前后记录数必须一致。

## 四、测试与验收

- 覆盖空库→head、v14→head、downgrade -1→upgrade head，均测试 SQLite 与 PostgreSQL。
- 验证已有 feedback、worker credential、formula graph spec、adaptive 状态无损升级。
- 验证主键、唯一约束和外键生效，重复/孤儿数据会阻止迁移。
- 回归 AI feedback 与 Worker credential 创建、验证、轮换。
- 执行 compileall、Ruff、相关 pytest、完整 migration matrix、`alembic check`。
- 最终要求：单 head、数据库在 head、78 张 ORM 表齐全、生产另有 `question_embeddings` 和 `alembic_version`、零 Alembic 漂移、零完全重复索引、零无效索引、零未验证约束、目标字段无 NULL、受影响表行数不变。

## 五、生产发布

分两个检查点：Release A 部署 Phase 1 与完整模型注册；验收后 Release B 部署 nullable 对齐、索引清理、CI 和文档。

每次发布必须：检查磁盘/服务/revision；完成 PostgreSQL 备份校验和 Redis SAVE；运行重复、NULL、孤儿、主键预检；同步代码并构建新镜像；用新镜像迁移；替换 app/scheduler 并 reload Nginx；验证容器、HTTPS health、head 和约束；用回滚事务验证 feedback/credential 写入；观察 app/scheduler/worker 日志至少 10 分钟。

正常回滚只回滚应用代码并保留新增 schema；约束或索引问题以前向迁移修复，只有确认数据损坏时才恢复备份。
