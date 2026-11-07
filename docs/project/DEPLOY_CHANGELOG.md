# Deploy Changelog — 生产发布与部署变更记录

> 2026-11-08 自 `docs/project/DEPLOY_PLAN.md` 拆分（原 §0.1–0.3、§6–§8），章节编号沿用原文件，外部引用按号检索仍有效。
> 现行部署架构、流程与环境变量见 `docs/project/DEPLOY_PLAN.md`；部署问题与修复记录见 `docs/project/DEPLOY_BUGS_HISTORY.md`。
> 2026-10-23 变更：移除原 §9.6/§9.7 两条生产补录番茄钟记录（一次性运维操作，留痕移至 docs/project/CHANGELOG.md）。

---

## 0. 生产发布记录

> 服务器迁移状态与当前生产入口见 `docs/project/DEPLOY_PLAN.md` §0。

### 0.1 科目目录匿名读取修复发布（2026-11-06）

北京时间 2026-11-06 01:07，用户单独授权后完成：仅将 `backend/app/api/v1/practice.py` 的 `/practice/subjects` 依赖改为可选身份；此前游客匿名请求生产仍返回 403。以旧运行 app 镜像为基底离线叠加该文件，无依赖、迁移或配置变更；仅重建 app 并校验/重载 Nginx，Admin、scheduler、worker、PostgreSQL、Redis 均未重建。

- 备份：`/data/backups/subject-auth-20261106/`，含主机/容器原文件、前后容器清单、构建与验收日志；旧镜像 `deploy-app:before-subject-auth-20261106`（`sha256:4363193b71d4e3e65672caf59d76f96c2ed72c97970d712732f231dd39b8e347`）。
- 新镜像：`deploy-app:subject-auth-20261106`，亦标记为 `deploy-app:latest`，ID `sha256:86fc21843df44840f2f1bad1c735dda81c282df9d47182b1c4b30cbc46d7d4b5`。发布文件 SHA256 `e527f2473516075299328af90816f6b822e3f46134f7ad491b1f287ee2ba5613`。
- 验证：发布前 pytest 54 项、严格 Ruff、compileall 通过；app healthy、0 次重启、内部 live/ready 200；两个生产域名匿名科目目录 200，包含高数、线性代数、英语和政治，错误凭据 401，正式出题/提交/收藏仍拒绝匿名访问，游客科目接口 200。具体结果 `acceptance.json`。
- 回退：服务器执行 `bash /data/backups/subject-auth-20261106/rollback.sh`，恢复备份源文件与旧镜像、重建 app、重载 Nginx，随后复验内部健康；本次检查通过，未实际触发回滚。没有数据库 schema/data 变更，不需要数据库回滚。
- 边界：未部署小程序或 Admin，未提交/推送，未开展模拟器/真机及审核验收。后续常规构建使用已同步的服务器源码，勿误回退此可选身份修复。

### 0.2 共享 AI 健康与预热重试发布（2026-11-06）

北京时间 2026-11-06 02:57—03:03，用户授权“部署更新”后完成后端发布。仅更新 AI 健康缓存、真实调用健康反馈、预热失败分类与队列重试预算相关的 8 个文件；分别以 app、worker 原运行镜像为基底离线叠加，不升级依赖、不迁移数据库。先替换 worker，再替换 app，随后检查并重载 Nginx。Admin、scheduler、PostgreSQL、Redis 和 Nginx 容器 ID 均保持原值。

- 备份与证据：`/data/backups/ai-health-20261106/`，含原主机/容器文件、镜像标签、前后容器清单、文件 SHA256 清单、构建/验证日志和 `acceptance.json`。旧镜像保留为 `deploy-app:before-ai-health-20261106`、`deploy-worker:before-ai-health-20261106`。
- 新 app：`deploy-app:ai-health-20261106`（同时标记 `latest`），ID `sha256:fadb5f8f6b7ce40633f0b6a2303806415241f8aeb9b5f10735377d8e9acceb31`；新 worker：`deploy-worker:ai-health-20261106`（同时标记 `latest`），ID `sha256:6ca2618b7452578d749afe6b00d32baeb55640e60468270bb7e83709179d74f0`。两容器及主机上的 8 个文件均匹配发布清单。
- 发布前定向 pytest **122 passed**；镜像预检验证成功租期 1800 秒、刷新间隔 300 秒、检查中重试至少 65 秒、历史可用性死信重试预算至少 3 次。预检曾因工件目录权限和旧 COPY 缓存失败，均发生在生产替换前；改为逐文件 COPY 并显式设置 0644 后，通过非 root 用户预检才执行切换。
- 运行验收：app `healthy`、角色 `web`；worker 运行、角色 `worker`；均 0 次重启、启动日志无 traceback。带生产 Host 的内部 live/ready 均 200；两个生产域名 live、公开科目目录和游客科目均 200，科目树共 10 个节点、包含高数和线性代数；无效身份仍为 401。
- 真实模型共享状态：仅按正常准入触发一次健康探测，完成后模型 69 为 `available / enabled=true`，成功租期 1800 秒。随后从 worker 独立进程只读检查，读到同一 `updated_at` / `healthy_until`，确认跨容器共用 Redis 状态；未清空缓存或修改模型配置。证据 `health-smoke-app.log`、`health-smoke-worker.log`。这是连接探测，不等同于真实题目的复盘生成或预热成功。
- 历史任务：验收时 V2 `prewarm_analysis` 死信 3 条；本轮未手动或批量重放，也未以真实用户数据创建测试任务。历史死信需后续从 Admin 审计入口逐条重试并检查最终缓存。
- 回退入口：服务器执行 `bash /data/backups/ai-health-20261106/release/rollback.sh`，恢复原主机文件和旧镜像、重建 app/worker、复验存活并重载 Nginx。本次未触发生产回退；无数据库变更。
- 客户端边界：错题详情目录与 Windows 项目镜像核对一致，本轮未复制镜像文件。官方 WCC 与编译模板回归已通过；原 `cli.bat` 出现递归错误，直接使用 Windows Node 可读取 CLI 帮助，但预览初始化因预期用户配置目录的 `Default/.cli` 不存在而失败。未上传、发布或提审小程序；模拟器、真机及真实复盘生成仍待验证。未提交、推送。

### 0.3 AI 审查后修复与策略收敛发布（2026-11-06）

北京时间 2026-11-06 03:34 完成发布验收。本轮仅在 §0.2 镜像上叠加三个文件：`app/services/ai/prewarm_transition.py`、`app/services/worker_task_types.py`、`app/services/task_queue_v2_dead_retry_contract.py`。预热模块负责恢复历史可用性死信预算，worker 任务类型模块选择策略，通用队列不再解析 AI 错误文本；既有预算、重试次数重置、任务版本与 fencing 行为保留。没有新增模块、依赖或迁移。

- 备份：`/data/backups/ai-cohesion-20261106/`，保留主机/容器原文件、前后容器清单、原镜像及验收日志；旧镜像标签为 `deploy-app:before-ai-cohesion-20261106`、`deploy-worker:before-ai-cohesion-20261106`。
- 新 app：`deploy-app:ai-cohesion-20261106`（亦标记 `latest`），ID `sha256:f1749399f334179b8c0fe4634c5a1870192975bbbe588c33f2a7dc95cff88a14`；新 worker：`deploy-worker:ai-cohesion-20261106`（亦标记 `latest`），ID `sha256:2dff20ce51bbf074fbbb08cd6e992bfbc7cfe4cf09146cb47ef6365ece8b405b`。
- 发布前后端相关回归 **596 passed**，本轮三个业务文件及两份测试严格 Ruff、app compileall 通过；镜像用原非 root 用户离线验证三个文件 SHA256、历史预算恢复、其他任务隔离及此前 1800 秒成功租期/300 秒刷新间隔。
- 线上三个文件在主机、app、worker 均匹配清单；app healthy、worker running，分别为 web/worker，0 次重启、启动日志无 traceback。内部 live/ready 200；两个生产域名 live、科目/游客科目均 200，科目树仍有 10 个节点；无效身份 401。其余容器 ID 不变，未重建 Admin/scheduler/数据库/Redis，Nginx 仅检查并 reload。证据 `acceptance.json`。
- 回退：`bash /data/backups/ai-cohesion-20261106/release/rollback.sh`，恢复三个源文件与 §0.2 运行镜像，重建 app/worker 后复验存活并 reload Nginx。本轮未触发回退，未迁移或手动重放历史任务；队列计数仅作验收时快照，不能推断历史任务已生成成功。
- 小程序：修复隐藏时清掉重试计时器、返回命中失败缓存却不恢复检查的问题，并隔离隐藏前在途响应；暂停/恢复及剩余冷却计算归既有可用性模块。相关 Node 定向 **66 passed**，全量 **2703 passed**，渲染 **31/31**；页面 502 行、20 个模块及架构守卫保持通过。
- 客户端交付：三个运行文件先备份到 `D:\tmp\ai-cohesion-20261106\client-backup`，再定向同步 Windows 工程；错题详情 25 个源码文件与 WSL 核对一致。CLI 调用按实际开发者工具路径识别已有用户配置，凭据仅传入当前进程环境，未修改工具安装文件或持久配置；官方 CLI 预览编译成功，总包 4,576,419 字节、主包 441,331 字节。二维码 `D:\tmp\ai-cohesion-20261106\preview.png`。未上传正式开发版本、发布或提审，真机操作与真实题目生成仍待复验。无 Git 提交/推送。


---

## 6. 数据库迁移审计

> 审计日期：2026-06-28
> 目的：确认本地 SQLite（开发/OCR 导入）数据能否安全迁移到生产 PostgreSQL

### 6.1 环境对比

| 项目 | 本地开发 | 生产服务器 |
|------|---------|-----------|
| 数据库引擎 | SQLite | PostgreSQL 15 |
| 数据库文件 | `backend/postgraduate.db` | `postgres` 容器持久卷 |
| Alembic 版本 | `u9v8w7x6y5z4` | `u9v8w7x6y5z4` |
| question_imports 行数 | 65 | 132 |
| questions 行数 | 22 | 24 |
| subjects 行数 | 5 | **0（未初始化）** |
| 用户数 | 68（dev 测试用户） | 1（真实微信用户） |

### 6.2 Schema 兼容性

| 表 | 结论 |
|----|------|
| `question_imports` | ✅ 列完全匹配 |
| `questions` | ✅ 列完全匹配 |
| `subjects` | ✅ 列完全匹配（但生产未初始化） |

本地 SQLite 虽然 Alembic 版本落后，但实际 Schema 已通过 SQLAlchemy 模型自动同步，与生产 PostgreSQL 一致。

### 6.3 迁移注意事项

| 注意点 | 说明 |
|--------|------|
| **ID 偏移** | 生产 `question_imports` 最大 ID=132，`questions` 最大 ID=24；导入数据需从之后开始 |
| **subjects 表** | 生产 subjects 为空，需先插入种子数据（math2, exam408, english 等 5 条） |
| **布尔类型** | SQLite 存 `0/1`（INTEGER），PostgreSQL 需转 `false/true`（boolean） |
| **JSON 字段** | SQLite 存 JSON 为 TEXT，写入 PostgreSQL `json` 列时需确保已是合法 JSON |
| **时间戳** | 两边均用无时区时间戳，格式兼容 |
| **用户关联** | `question_imports` 不直接关联 `user_id`，无需处理用户映射 |

### 6.4 推荐迁移策略

```
本地 OCR 导入（快） → 导出 question_imports（JSON 序列化）
  → 调整 ID（从生产 max_id+1 开始）
  → 转换类型（0/1 → boolean，TEXT → JSON）
  → 写入生产 PostgreSQL
  → 初始化 subjects 种子数据
  → 已验证：生产 question_imports 和 questions 表结构 100% 兼容
```

---

## 7. 本次生产强化部署说明（2026-07-25）

> 本节记录 2026-07 的历史生产强化部署事项；服务器已停用，以下内容仅供技术背景参考，不作为当前服务器操作步骤。

### 7.1 新增环境变量

| 变量名 | 类型 | 必填 | 默认值 | 生产推荐值 | 敏感 | 非法启动行为 |
|--------|------|------|--------|-----------|------|------------|
| `PROCESS_ROLE` | 字符串 | 否 | `web` | `web` / `worker` / `scheduler` | 否 | 生产禁止 `all`，否则启动失败 |
| `PDF_MAX_FILE_SIZE_BYTES` | 整数 | 否 | 200MB | 5MB (5242880) | 否 | — |
| `PDF_MAX_PAGES` | 整数 | 否 | 600 | 30 | 否 | 超过 cloud 上限 30 导致启动失败 |
| `PDF_MAX_PAGE_PIXELS` | 整数 | 否 | 4096×4096 | 4096×4096 | 否 | — |
| `PDF_MAX_DECODED_BYTES` | 整数 | 否 | 50MB | 50MB | 否 | — |
| `PDF_RENDER_DPI` | 整数 | 否 | 150 | 150 | 否 | — |
| `PDF_MAX_RENDER_PAGES_CONCURRENT` | 整数 | 否 | 5 | 1 | 否 | cloud 超过 1 导致启动失败 |
| `PDF_RENDER_PAGE_WINDOW` | 整数 | 否 | 0（全部） | 1 | 否 | cloud 为 0 导致启动失败 |
| `DB_POOL_SIZE_WEB` | 整数 | 否 | 3 | 3 | 否 | 总预算超过 MAX_CONNECTIONS 导致启动失败 |
| `DB_MAX_OVERFLOW_WEB` | 整数 | 否 | 5 | 5 | 否 | 同上 |
| `DB_POOL_SIZE_WORKER` | 整数 | 否 | 2 | 2 | 否 | 同上 |
| `DB_MAX_OVERFLOW_WORKER` | 整数 | 否 | 3 | 3 | 否 | 同上 |
| `DB_POOL_SIZE_SCHEDULER` | 整数 | 否 | 1 | 1 | 否 | 同上 |
| `DB_MAX_OVERFLOW_SCHEDULER` | 整数 | 否 | 2 | 2 | 否 | 同上 |

> **总预算计算**：`(DB_POOL_SIZE_WEB + DB_MAX_OVERFLOW_WEB) × GUNICORN_WORKERS + DB_POOL_SIZE_WORKER + DB_MAX_OVERFLOW_WORKER + DB_POOL_SIZE_SCHEDULER + DB_MAX_OVERFLOW_SCHEDULER ≤ MAX_CONNECTIONS`（默认 50）

### 7.2 部署顺序（含角色隔离）

本次引入 `PROCESS_ROLE` 和 `BoundedExecutor`，推荐按以下顺序部署：

1. **停止新导入** — 前端灰度停止或 API 返回 503（可选，非必需）
2. **备份** — `bash deploy/scripts/deploy.sh backup`（PostgreSQL + Redis RDB）
3. **数据库迁移**：
   ```bash
   cd /opt/22408-ai
   bash deploy/scripts/deploy.sh migrate
   ```
   v10 迁移创建 5 个复合索引（带 `CONCURRENTLY`），不阻塞生产读写。
4. **部署 scheduler** — `PROCESS_ROLE=scheduler` 容器，启动后验证 /health
5. **部署 worker** — `PROCESS_ROLE=worker` 容器，启动后验证 readiness
6. **部署 web** — `PROCESS_ROLE=web` 容器，启动后验证 readiness
7. **恢复流量** — 验证 SSE、导入、OCR 核心链路功能正常

### 7.3 回滚方案

| 组件 | 回滚操作 | 说明 |
|------|---------|------|
| 应用代码 | 回滚代码 → 重新 `deploy.sh update` | 不执行 `down` 或删除 volume |
| 数据库 | `alembic downgrade v9`（仅临时数据库） | **生产禁止 downgrade**，v10 索引非破坏性变更，保留无害 |
| Redis 队列 | 新旧 enqueue payload 兼容 | 新 worker 可读旧 payload，旧 worker 忽略新字段 |
| Fencing generation | 新 worker 写新 generation，旧 worker 隔离 | `execution_generation` 递增后旧 worker 写操作被 fencing |
| SSE | 平滑降级 | Web 端无 SSE 时轮询 /batch-image/{job_id} 终态 |
| OCR | 禁止回滚到 legacy OCR | 旧 OCR 代码（本地 PaddleOCR 进程）已删除 |

### 7.4 启动自检清单

生产启动时 `production_config_validator` 自动执行以下检查，失败则拒绝启动：

| 检查项 | 条件 | 失败后果 |
|--------|------|---------|
| APP_SECRET 强度 | 长度≥32 且非默认值 | 启动失败 |
| DATABASE_URL | postgresql+asyncpg | 启动失败 |
| CORS_ORIGINS | 非通配符 / 非 localhost | 启动失败 |
| REDIS_URL | 设置且 PING 可达（异步） | 启动失败 |
| PROCESS_ROLE | web/worker/scheduler 之一，非 all | 启动失败 |
| 部署 profile | cloud_api（生产必须） | 启动失败 |
| PDF 规则 | window>0, concurrency=1, pages≤30 | 启动失败（cloud） |
| DB 连接预算 | ≤ MAX_CONNECTIONS | 启动失败 |
| OCR 规则 | GPU=false, backend=paddlex_http/disabled | 启动失败 |
| 迁移版本 | alembic at head（异步） | 启动失败 |
| 目录可写 | staging, static 目录 | 启动失败 |

> 自检在 `lifespan` startup 阶段执行，约 3-5 秒完成（含 Redis PING 和 DB 查询）。
> 失败日志格式：`Production configuration validation failed:` 后逐行列明原因。

---

## 8. 生产强化 Batch 8–11 更新事项（2026-07-26）

> 本节记录 2026-07 的历史生产强化部署事项；服务器已停用，以下内容仅供技术背景参考，不作为当前服务器操作步骤。

### 8.1 新增环境变量

| 变量名 | 类型 | 必填 | 默认值 | 生产推荐值 | 敏感 | 说明 |
|--------|------|------|--------|-----------|------|------|
| `SLOW_QUERY_MS` | 整数 | 否 | 500 | 500 | 否 | 慢查询阈值（毫秒），超过后记录 `app.db.slow_query` |
| `STAGING_DISK_QUOTA` | 整数 | 否 | 2GB | 2GB | 否 | Staging 目录磁盘配额，启动时校验剩余空间 |
| `AUDIT_LOG_CLEANUP_ENABLED` | 布尔 | 否 | true | true | 否 | 审计日志自动清理开关 |
| `AUDIT_LOG_RETENTION_DAYS` | 整数 | 否 | 180 | 180 | 否 | 审计日志保留天数 |
| `AUDIT_LOG_CLEANUP_BATCH_SIZE` | 整数 | 否 | 1000 | 1000 | 否 | 单次清理批大小 |

### 8.2 数据库变更

**Alembic 迁移**（合并两个 head）：
- `812ba6628ff1` — 合并 `v10_export_tasks` 和 `v14_execution_generation_fencing` 两个 head 为单链
- 合并仅限于版本历史修复，不产生 schema 变更

**连接预算验证**（`production_config_validator` 内置）：
```
预算 = (DB_POOL_SIZE_WEB + DB_MAX_OVERFLOW_WEB) × GUNICORN_WORKERS
     + DB_POOL_SIZE_WORKER + DB_MAX_OVERFLOW_WORKER
     + DB_POOL_SIZE_SCHEDULER + DB_MAX_OVERFLOW_SCHEDULER
     ≤ MAX_CONNECTIONS(default 50)
```
默认 2 worker 环境：`(3+5)×2 + (2+3) + (1+2) = 16+5+3 = 24` 连接

启动时打印到日志：`DB connection budget: web=8/worker x 2 workers=16 + worker=5 + scheduler=3 = 24 total`

### 8.3 指标端点新指标

`/health/metrics` 新增以下 Prometheus 指标：

| 指标名 | 标签 | 类型 | 说明 |
|--------|------|------|------|
| `scheduler_running` | name=pomodoro/audit_cleanup | gauge | 调度器运行状态 |
| `staging_orphan_count` | 无 | gauge | 孤立的 staging 对象数（有 .data 无 .meta.json） |

### 8.4 部署顺序

```
1. 备份: bash deploy/scripts/deploy.sh backup   # PostgreSQL + Redis RDB
2. 数据库迁移: bash deploy/scripts/deploy.sh migrate
3. 部署 app (任意 PROCESS_ROLE):
   - scheduler → 验证 /health/ready
   - worker → 验证 /health/ready (not draining, OCR backend 正确)
   - web → 验证 /health/ready
4. 验证核心链路: SSE, 导入, OCR, 刷题
```

### 8.5 回滚方案

| 场景 | 操作 | 说明 |
|------|------|------|
| 应用代码 | 回滚代码 → `deploy.sh update` | 不要 `down` 或删 volume |
| 数据库 | `alembic downgrade 812ba6628ff1` | 合并迁移无害，downgrade 为 no-op |
| 连接池配置 | 仅改环境变量后重启 | 无 schema 影响 |
| 指标端点新增 | 无害 — 旧 Prometheus 忽略未知指标 | 无依赖风险 |
| 调度器 LeaseHandle | 旧代码兼容（仍返回 bool） | 新旧 worker 可共存 |

### 8.6 启动自检：Schema 分歧检查

应用启动时自动检测已知的运行时 DDL 列是否缺失（仅 PostgreSQL）：

```
信息列检查:
  questions      → question_hash, sync_uuid, sync_version
  question_imports → question_hash, duplicate_status, duplicate_of_question_id, duplicate_of_import_id
  users          → is_banned, deleted_at
```

- 非阻塞：仅记录 `WARNING` 日志，不影响启动
- 仅运行在 PostgreSQL（SQLite 跳过）
- 诊断结果示例：
  ```
  Schema divergence (runtime DDL not in Alembic): question_imports.duplicate_of_question_id, users.is_banned
  ```

> 这些列由 `database.py` 中的 `_ensure_*` 运行时 DDL 函数创建。
> 生产迁移到 `cloud_api` profile 后 `init_db()` 被跳过，若 Alembic 迁移未覆盖则可能缺失。
> 当前生产库已在旧版本中由 `init_db()` 补全，新部署需确保 Alembic 覆盖。

### 8.7 性能审计：EXPLAIN ANALYZE

核心查询的 EXPLAIN ANALYZE SQL 脚本位于 `backend/docs/explain_analyze.sql`。
在生产 PostgreSQL 上运行以验证查询计划。

覆盖的查询：
1. Leitner 到期选择 — ORDER BY random() 成本
2. 错题列表 — 4 个标量子查询
3. 科目统计 — 双 OUTER JOIN + GROUP BY 表达式
4. 学习趋势 — 按天聚合索引使用
5. SM-2 到期复习 — partial index 使用
6. Dashboard v2 — 双列 JOIN

### 8.8 部署后验证清单

| 步骤 | 命令 | 预期 |
|------|------|------|
| 1. 检查单个 head | `alembic heads` | 仅 `812ba6628ff1 (head)` |
| 2. 验证 readiness | `curl /health/ready` | `status: ok` |

容器内 readiness 检查必须使用生产域名 Host 头，例如：

```bash
curl -H "Host: xzshub.top" http://127.0.0.1:8000/health/ready
```

若该探针失败，先用相同 Host 头请求保留的旧运行镜像。旧镜像也失败说明探针或配置有问题；只有新镜像失败而旧镜像通过，才按回滚流程处理。公网 `/health/ready` 受 nginx 保护，通常返回 403，不以它替代容器内探针。
| 3. 验证角色日志 | `docker compose logs app` | 显示当前角色及组件清单 |
| 4. 检查 schema 分歧 | `docker compose logs app` | 无 `Schema divergence` 警告 |
| 5. 检查指标 | `curl /health/metrics` | 包含 `scheduler_running`, `staging_orphan_count` |
| 6. EXPLAIN ANALYZE | 运行 `docs/explain_analyze.sql` | 查询计划使用索引 |
| 7. OCR 回退验证 | 触发 OCR 导入 | 日志无 forbidden backends 警告 |

### 8.6 服务器 .env 推荐值（完整版）

```bash
# 环境
APP_ENV=production
DEPLOYMENT_PROFILE=cloud_api
PROCESS_ROLE=web            # 按角色拆分为 web/worker/scheduler

# 密钥
APP_SECRET=...
AI_CONFIG_ENCRYPT_KEY=...                      # AI 模型凭据加密密钥（凭据存 DB admin_ai_model_configs）

# 数据库
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/postgraduate
DB_POOL_SIZE_WEB=3
DB_MAX_OVERFLOW_WEB=5
DB_POOL_SIZE_WORKER=2
DB_MAX_OVERFLOW_WORKER=3
DB_POOL_SIZE_SCHEDULER=1
DB_MAX_OVERFLOW_SCHEDULER=2

# Redis
REDIS_URL=redis://redis:6379/0

# 导出（export 功能）
EXPORT_FEATURE_ENABLED=true          # 导出功能全局开关
EXPORT_WEBSOCKET_ENABLED=true        # WebSocket 实时推送
EXPORT_ALLOW_ALL_USERS=true          # 允许所有用户导出（设为 false 需配置白名单）
EXPORT_ALLOWED_USER_IDS=             # 白名单用户 ID（逗号分隔，EXPORT_ALLOW_ALL_USERS=false 时生效）

# OCR
OCR_ENABLED=true
OCR_EXECUTION_BACKEND=paddlex_http
OCR_REMOTE_URL=https://paddleocr.aistudio-app.com/ocr
OCR_REMOTE_TOKEN=...

# 微信
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID=...

# 调度器
POMODORO_NOTIFY_ENABLED=true
POMODORO_NOTIFY_PAGE=pages/pomodoro/pomodoro
POMODORO_SCHEDULER_INTERVAL_SEC=60

# Gunicorn
GUNICORN_WORKERS=2
MAX_CONNECTIONS=50

# PDF（云环境）
PDF_RENDER_PAGE_WINDOW=1
PDF_MAX_RENDER_PAGES_CONCURRENT=1
PDF_MAX_PAGES=30
PDF_MAX_FILE_BYTES=5242880

# 日志
SQL_ECHO=false
SQL_LOG_LEVEL=WARNING
SLOW_QUERY_MS=500
```

---

---

## 相关链接

- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署架构、流程与环境变量（现行操作）
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/INDEX.md|INDEX]] — 文档总索引
