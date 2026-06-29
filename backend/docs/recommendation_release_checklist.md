# 推荐系统发布前检查清单 (Phase 4.6)

本文档覆盖推荐系统（Phase 1-4.5）发布到生产环境前的逐项检查。
按顺序执行，每项标记 `[ ]` 为未通过、`[x]` 为已通过。

---

## A. 数据库迁移

### A.1 迁移链完整性

- [ ] `alembic heads` 输出唯一 head：`p4_6_release_hardening`
- [ ] `alembic history` 无断链、无分叉（除已合并的 merge head）
- [ ] 所有新增 migration 文件已提交到版本控制

### A.2 生产迁移可执行

- [ ] 在 staging 环境执行 `alembic upgrade head` 成功
- [ ] `p4_6_release_hardening` 创建了 5 张表：
  - `knowledge_points`
  - `question_knowledge_points`
  - `knowledge_edges`
  - `user_knowledge_states`
  - `recommendation_logs`
- [ ] `p4_6_release_hardening` 在 `recommendation_logs` 上创建了 3 个复合索引：
  - `ix_rl_user_scene_created`
  - `ix_rl_user_request`
  - `ix_rl_created_at`
- [ ] Phase 4.5 safety valve 6 个列已添加到 `recommendation_experiments`
- [ ] 迁移支持幂等重跑（`_has_table` / `_has_column` / `_has_index` guard）

### A.3 alembic/env.py 模型注册

- [ ] Phase 3 模型已导入：`KnowledgePoint`、`QuestionKnowledgePoint`、`KnowledgeEdge`、`UserKnowledgeState`
- [ ] Phase 4 模型已导入：`RecommendationLog`、`RecommendationStrategyConfig`、`RecommendationExperiment`、`RecommendationExperimentAssignment`、`RecommendationMetricsDaily`
- [ ] 其他遗漏模型已导入：`PomodoroSession`、`AppUserAdminBinding`、`ImportPipeline`、`ImportPipelineChunk`
- [ ] `alembic revision --autogenerate` 不会产生 DROP TABLE 语句

---

## B. 索引与约束

### B.1 唯一约束

- [ ] `knowledge_points`: `(subject, normalized_name)` — `uq_kp_subject_normalized_name`
- [ ] `question_knowledge_points`: `(question_id, knowledge_point_id)` — `uq_qkp_question_kp`
- [ ] `knowledge_edges`: `(source_kp_id, target_kp_id, relation_type)` — `uq_ke_source_target_relation`
- [ ] `user_knowledge_states`: `(user_id, knowledge_point_id)` — `uq_uks_user_kp`
- [ ] `recommendation_strategy_configs`: `name` — unique
- [ ] `recommendation_experiments`: `name` — unique
- [ ] `recommendation_experiment_assignments`: `(experiment_id, user_id)` — `uq_rea_experiment_user`
- [ ] `recommendation_metrics_daily`: `(date, subject, scene, strategy, variant_key)` — `uq_rmd_date_subject_scene_strategy_variant`

### B.2 外键级联

- [ ] `knowledge_edges.source_knowledge_point_id` → `knowledge_points.id` ON DELETE CASCADE
- [ ] `knowledge_edges.target_knowledge_point_id` → `knowledge_points.id` ON DELETE CASCADE
- [ ] `recommendation_experiment_assignments.experiment_id` → `recommendation_experiments.id` ON DELETE CASCADE
- [ ] `recommendation_experiment_assignments.user_id` → `users.id` ON DELETE CASCADE

### B.3 复合索引（Phase 4.6 新增）

- [ ] `recommendation_logs`: `(user_id, scene, created_at)` — 推荐引擎热路径
- [ ] `recommendation_logs`: `(user_id, request_id)` — 反馈匹配
- [ ] `recommendation_logs`: `(created_at)` — 指标聚合时间范围扫描

---

## C. API 安全

### C.1 Admin 端点权限

- [ ] 所有 admin 端点有 `require_permissions()` 或 `require_roles()` 保护
- [ ] `GET /api/admin/v1/health/live` — 无鉴权（K8s liveness probe，符合预期）
- [ ] `GET /api/admin/v1/health/ready` — 需要 `get_current_admin` 鉴权（Phase 4.6 修复）
- [ ] `admin_recommendation.py` 所有端点使用 `require_permissions("question:*")`
- [ ] `admin_knowledge.py` 所有端点使用 `require_permissions("question:*")`

### C.2 用户端点隔离

- [ ] `GET /api/v1/practice/questions?mode=smart` — 只访问推荐系统，不影响 random/sequential
- [ ] `GET /api/v1/practice/questions?mode=similar` — 只访问向量召回
- [ ] `GET /api/v1/practice/questions?mode=random` — 不依赖推荐系统
- [ ] `GET /api/v1/practice/questions?mode=sequential` — 不依赖推荐系统
- [ ] `GET /api/v1/review/*` — 独立 SM-2 调度，不读写推荐数据
- [ ] `GET /api/v1/wrong-questions/*` — 独立错题管理

---

## D. 配置与环境

### D.1 .env.example 完整性

- [ ] 向量搜索 4 项：`VECTOR_ENABLED`、`VECTOR_CACHE_TTL_SEC`、`VECTOR_TOP_K`、`VECTOR_SIMILARITY_THRESHOLD`
- [ ] Embedding 7 项：`EMBEDDING_PROVIDER`、`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIM`、`EMBEDDING_TIMEOUT`、`EMBEDDING_BATCH_SIZE`

### D.2 生产环境配置

- [ ] `APP_ENV=production` 时 `init_db()` 不执行 `create_all`（由迁移接管）
- [ ] `VECTOR_ENABLED` 在 staging 设为 `true`，确认 pgvector 扩展已安装
- [ ] `EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL` 已配置
- [ ] `EMBEDDING_DIM` 与 pgvector 列维度一致（默认 1024）
- [ ] `DATABASE_URL` 指向 PostgreSQL（非 SQLite）
- [ ] `REDIS_URL` 已配置（推荐缓存依赖）

---

## E. 功能回归验证

### E.1 不影响既有功能

- [ ] random 模式：`GET /api/v1/practice/questions?mode=random` 正常返回
- [ ] sequential 模式：`GET /api/v1/practice/questions?mode=sequential` 正常返回
- [ ] SM-2 复习：`GET /api/v1/review/today` 正常返回，不读写推荐表
- [ ] 错题本：`GET /api/v1/wrong-questions` 正常返回
- [ ] ReviewSchedule 表：SM-2 调度状态未被推荐系统修改
- [ ] WrongQuestion 表：单向同步 `ReviewSchedule → WrongQuestion`（仅 `last_review_at`, `mastered`）未被破坏

### E.2 新功能可用

- [ ] smart 模式：`GET /api/v1/practice/questions?mode=smart` 正常返回
- [ ] similar 模式：`GET /api/v1/practice/questions?mode=similar&question_id=X` 正常返回
- [ ] 知识路径：`GET /api/v1/knowledge-path?subject=X` 正常返回
- [ ] 推荐反馈：提交答案后 `recommendation_logs` 正确写入 `mastery_before/after/delta`

---

## F. 运维文档

- [ ] `backend/docs/recommendation_operations.md` 覆盖 12 个章节
- [ ] 章节 8：回填 Embedding — 包含触发场景、操作步骤、验证 SQL
- [ ] 章节 9：知识点 Backfill — 包含创建/关联/推断/验证流程
- [ ] 章节 10：A/B 实验启停 — 包含创建/启动/暂停/恢复/结束/状态转换规则
- [ ] 章节 11：质量扫描 — 包含每日/每周扫描命令和质量门禁标准
- [ ] 章节 12：系统边界 — 明确与 ReviewSchedule/SM-2/WrongQuestion 的关系

---

## G. 测试

### G.1 单元测试

- [ ] `pytest tests/test_services/ -v` — 全绿
- [ ] `pytest tests/test_api/ -v` — 全绿
- [ ] `pytest tests/test_features/ -v` — 全绿
- [ ] 无新增失败用例
- [ ] xfailed 数量未增加（基线 13 个）

### G.2 Staging Smoke Test

- [ ] 按 `recommendation_release_checklist.md` 中的 staging smoke test 逐项执行
- [ ] 所有接口返回预期状态码
- [ ] 数据库表正确创建
- [ ] 缓存正常读写

---

## H. 部署顺序

生产部署严格按以下顺序执行，不可跳步或调换：

1. **备份数据库** — `pg_dump` 全量备份或 RDS 快照，确保可回滚
2. **确认 pgvector 扩展可用** — `CREATE EXTENSION IF NOT EXISTS vector;` 验证
3. **执行 `alembic upgrade head`** — 创建 5 张新表 + 3 个复合索引 + 6 个 safety valve 列
4. **验证新增表和索引** — 执行 staging smoke test 中汇总检查 SQL（预期 9 张表）
5. **部署后端代码** — 合并代码到 main 分支并部署
6. **重启服务** — 确保新代码加载
7. **seed 默认推荐策略** — `POST /api/admin/v1/recommendation/strategies/seed`（`force=false`）
8. **VECTOR_ENABLED=false 下完成冒烟测试** — 按 staging smoke test 执行 11 项验证
9. **小流量开启 VECTOR_ENABLED=true** — 仅开放给内部用户或少量流量
10. **小批量执行 embedding backfill** — 限 100 题验证 embedding API 连通性和向量写入
11. **监控 30-60 分钟** — 观察健康报告、fallback_rate、vector_recall_failure_count、日志关键词
12. **确认无异常后扩大流量** — 逐步放开至全量

**关键约束：**
- 步骤 3 必须在步骤 5 之前（新表先创建，代码才能正常启动）
- 步骤 8 必须在步骤 9 之前（确认 fallback 路径正常再开启向量）
- 步骤 10 必须在步骤 11 之前（先验证 embedding 再监控）
- 任何步骤失败应立即执行回滚：`VECTOR_ENABLED=false` → 必要时 `alembic downgrade -1`

---

## 检查签字

| 检查人 | 日期 | 结果 |
|--------|------|------|
| | | |
