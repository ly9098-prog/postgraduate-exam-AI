## Phase 5.2.1 部署报告

生成时间：2026-06-29

### 结论

**CONDITIONAL PASS** — 代码与脚本全部就绪，需要在远端 PostgreSQL + pgvector 环境中执行部署脚本完成实际验收。

### 环境说明

当前开发环境无 Docker、无 PostgreSQL 客户端、无 .env 配置。Docker 配置在远端服务器。
所有自动化脚本已准备完毕，在有 PostgreSQL 环境时可一键执行。

### 已完成工作

#### 1. Docker Compose 更新（4 个文件）

所有 docker-compose 文件的 PostgreSQL 镜像从 `postgres:15-alpine` 替换为 `pgvector/pgvector:pg15`：

| 文件 | 状态 |
|------|------|
| docker-compose.yml（根目录） | 已更新 |
| deploy/docker-compose.prod.yml | 已更新 |
| deploy/docker-compose.dev.yml | 已更新 |
| backend/docker/docker-compose.yml | 已更新 |

#### 2. 环境变量补齐

| 文件 | 新增变量 |
|------|----------|
| backend/.env.example | VECTOR_MODE, VECTOR_ALLOWLIST |
| deploy/.env.example | VECTOR_ENABLED, VECTOR_MODE, VECTOR_ALLOWLIST, VECTOR_CACHE_TTL_SEC, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD, EMBEDDING_* 全部 |
| deploy/docker-compose.prod.yml | 所有 VECTOR_* 和 EMBEDDING_* 环境变量透传 |

#### 3. practice_records 外键迁移

新建 `alembic/versions/p5_2_1_practice_records_fk.py`：

| 特性 | 说明 |
|------|------|
| down_revision | p5_0_schema_baseline |
| 幂等 | FK 已存在时跳过 |
| 孤儿检测 | 有孤儿数据时跳过 FK 添加并警告 |
| SQLite 安全 | SQLite 不支持 ADD FK，自动跳过 |
| downgrade | 可回滚（drop_constraint） |

Alembic head 已验证：`p5_2_1_practice_records_fk (head)`

#### 4. 自动化部署脚本

`scripts/phase_5_2_1_deploy.py` 包含 6 个任务函数：

| 任务 | 功能 |
|------|------|
| task1_pg_check | PostgreSQL 版本、pgvector 扩展、维度一致性、HNSW 索引 |
| task2_fk_check | 孤儿数据检测、FK 状态 |
| task3_embedding_check | Embedding API 连通性、维度验证、超时 fallback |
| task4_backfill | 小批量回填（默认 200 题，支持 --dry-run） |
| task5_offline_eval | 离线评估（≥30 seed，自返回/跨 subject/重复/答案泄漏/P50/P95/fallback） |
| task6_shadow_mode | Shadow 模式验证 |

输出：
- `artifacts/phase_5_2_1_metrics.json`
- `docs/phase_5_2_1_deployment_report.md`

#### 5. 验收测试套件

`tests/test_services/test_phase_5_2_1_deployment.py` — 65 个测试全部通过。

覆盖：
- 任务一：PostgreSQL + pgvector 检查逻辑（4 个测试）
- 任务二：FK 迁移文件验证（6 个测试）
- 任务三：Embedding 配置检查（6 个测试）
- 任务四：回填逻辑验证（4 个测试）
- 任务五：离线评估门禁（12 个测试）
- 任务六：Shadow 模式验证（3 个测试）
- 任务七：Allowlist 配置（9 个测试）
- 任务八：全用户启用建议（5 个测试）
- Docker Compose 配置验证（6 个测试）
- 部署脚本验证（4 个测试）
- 主链路完整性回归（6 个测试）

#### 6. 全量测试

2540 passed / 6 skipped / 18 xfailed / 0 failed — 无回归。

### 远端服务器待做步骤

1. 拉取代码更新，切换到 pgvector 镜像（docker compose 已改好镜像名）
2. 运行 alembic 迁移（含 FK 补齐）
3. 在 .env 中配置 EMBEDDING_API_KEY 和 EMBEDDING_BASEURL（必须通过 Secret 注入，不得写入仓库或日志）
4. 运行部署验证脚本，先用 dry-run 模式确认环境正常
5. 正式执行部署脚本（自动完成回填 + 离线评估 + 报告生成）
6. 确认无问题后切换 shadow 模式观察一段时间
7. shadow 通过后切换 allowlist，仅开放项目所有者 user_id

### 门禁条件

自动门禁：
- 无答案泄漏
- 跨 subject 数量为 0
- 重复结果数量为 0
- 查询成功率不低于 95%
- fallback 测试全部通过
- 无 P0/P1

若门禁未通过，保持 VECTOR_MODE=off 并给出失败原因。

### 全用户启用建议

只有满足以下条件才建议 VECTOR_MODE=all：

1. Shadow 自动报告通过
2. Allowlist 正常使用期间无 P0/P1
3. 无答案泄漏
4. 无持续跨 subject 错召回
5. fallback 始终有效
6. 延迟可接受
7. Embedding 成本处于限制内

由于总用户不足 10 人，不做百分比灰度。建议路径：
off → shadow → allowlist（仅所有者）→ all（全部现有用户）

### 修改文件列表

| 文件 | 操作 |
|------|------|
| docker-compose.yml | 修改：postgres 镜像改为 pgvector/pgvector:pg15 |
| deploy/docker-compose.prod.yml | 修改：postgres 镜像 + 新增 VECTOR_*/EMBEDDING_* 环境变量 |
| deploy/docker-compose.dev.yml | 修改：postgres 镜像改为 pgvector/pgvector:pg15 |
| backend/docker/docker-compose.yml | 修改：postgres 镜像改为 pgvector/pgvector:pg15 |
| backend/.env.example | 修改：新增 VECTOR_MODE, VECTOR_ALLOWLIST |
| deploy/.env.example | 修改：新增全部 VECTOR_* 和 EMBEDDING_* 变量 |
| alembic/versions/p5_2_1_practice_records_fk.py | 新建：practice_records FK 迁移 |
| scripts/phase_5_2_1_deploy.py | 新建：自动化部署验证脚本 |
| tests/test_services/test_phase_5_2_1_deployment.py | 新建：65 个验收测试 |
