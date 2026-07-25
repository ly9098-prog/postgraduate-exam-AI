# 部署方案

> 更新时间：2026-07-25
> 生产入口：`deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`

---

## 1. 生产部署架构

### 服务组成

| 服务 | 容器名 | 说明 |
|------|--------|------|
| `app` | deploy-app-1 | FastAPI + Gunicorn，源码构建 |
| `nginx` | deploy-nginx-1 | nginx:1.25-alpine，HTTPS 反代 |
| `postgres` | deploy-postgres-1 | PostgreSQL 15，持久卷 pgdata_prod |
| `redis` | deploy-redis-1 | Redis 7，持久卷 redisdata_prod |
| `admin` | deploy-admin-1 | Next.js 管理前端（仅内网 3000） |

### 网络拓扑

```
用户 → nginx:443 (HTTPS) → app:8000 (HTTP)
                      → postgres:5432（仅 app 可访问）
                      → redis:6379（仅 app 可访问）
```

### 关键路径

| 路径 | 说明 |
|------|------|
| `deploy/docker-compose.prod.yml` | **当前生产 compose 入口** |
| `deploy/scripts/deploy.sh` | **当前推荐生产部署脚本** |
| `deploy/nginx/nginx.conf` | Nginx 配置 |
| `deploy/scripts/backup.sh` | 备份脚本 |
| `backend/docker/Dockerfile` | app 镜像 Dockerfile（含 PaddleOCR） |
| `backend/.env` | 服务器侧环境变量（独立维护） |

### 服务器信息

| 项目 | 值 |
|------|-----|
| 公网 IP | `8.163.56.109` |
| 内网 IP | `172.18.50.44` |
| 域名 | `xzshub.top` |
| 部署目录 | `/opt/2240ai-v2` |
| 服务器密钥 | 服务器侧 `/loginkey.pem` |
| 证书目录 | `/opt/2240ai-v2/cert` → 容器内 `/etc/nginx/ssl` |
| 证书文件 | `/opt/2240ai-v2/cert/www.xzshub.top.pem` + `.key` |

### 服务器规格

| 资源 | 值 |
|------|----|
| CPU | 2 核 |
| 内存 | 1.8 GB |
| 磁盘 | — |
| OS | Linux (Debian) |

---

## 2. 部署流程

### 2.1 同步代码到服务器

使用 `.deployignore` 排除敏感文件和本地产物：

```bash
rsync -az --exclude-from=".deployignore" \
  -e "ssh -i loginkey.pem -o BatchMode=yes" \
  ./ root@8.163.56.109:/opt/2240ai-v2/
```

排除范围：`.git/`、`.claude/`、`.venv/`、`node_modules/`、`__pycache__/`、`*.db`、`.env`、`*.pem`、`*.key`、`docs/`、`prompts/`、测试文件、日志、上传目录等。

> 当本地删除了前端页面文件时，需加 `--delete` 参数同步删除服务器上的对应文件，否则 Next.js build 会因死代码引用报错。示例：
> ```bash
> rsync -az --delete --exclude-from=".deployignore" \
>   -e "ssh -i loginkey.pem -o BatchMode=yes" \
>   ./ root@8.163.56.109:/opt/2240ai-v2/
> ```

### 2.2 日常更新（app + admin）

构建并替换服务，不重启 postgres/redis/nginx。

**更新 app 后端：**
```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh update
```

**更新 admin 前端：**
```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh update-admin
```

内部执行：
1. `docker compose build <service>`（保留 Docker layer cache）
2. `docker compose up -d --no-deps <service>`（只替换目标服务）
3. 健康检查：app 容器内 `/health` + nginx HTTPS `/health`

### 2.3 查看状态

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh status
```

输出各容器状态、健康检查和接口可达性。

### 2.4 显式迁移

仅在 schema 变更确认后执行：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh migrate
```

> **注意**：生产环境 PostgreSQL 与本地 SQLite 有差异。部分旧 migration 包含 SQLite 专用代码（`sqlite_master` 查询、`DROP INDEX` 无 `IF EXISTS`、未捕获的约束已存在异常）。遇到此类失败时，使用 `docker compose exec -T app alembic upgrade <target>` 逐条迁移，对 SQLite-only 操作可 `alembic stamp` 跳过（已验证：`c07a8112c2f2`、`d1e2f3a4b5c6`、`f2e3a4b5c6d7` 均已修复）。

### 2.5 回滚

若新 app 启动失败：
1. 查看日志 `docker compose logs --tail=80 app`
2. 不执行 `down` 或删除 volume
3. 回滚代码到上一版本 → 重新 `bash deploy/scripts/deploy.sh update`

### 2.6 低内存服务器构建注意事项

服务器规格为 2 核 / 1.8 GB 内存。Admin 前端 Next.js 构建是内存敏感操作：

| 措施 | 说明 |
|------|------|
| `NODE_OPTIONS=--max-old-space-size=1536` | Dockerfile 中限制 Node.js 堆上限，防止 OOM |
| `output: "standalone"` | 产物仅包含必要文件，减少磁盘占用 |
| 构建超时 | 首次构建约 1-3 分钟，峰值 RSS 约 800–1200 MB |
| 构建产物 | `.next/standalone` + `.next/static`，总计约 50–80 MB |
| layer cache | Docker layer cache 保留 `/app/.next/cache`（Next.js 缓存约 200 MB） |

**构建失败处理：**
- `compose build admin` 失败不影响当前运行的 admin 容器
- `compose up -d --no-deps admin` 仅在构建成功后执行
- 若构建耗时过长或 OOM，可临时增加 swap 或先在本机构建后推送镜像

**推荐流程（服务器外构建）：**
1. 在 CI 或本机执行 `docker build -t admin-frontend admin-frontend/`
2. `docker save admin-frontend | ssh ... docker load`
3. 服务器只执行启动，不执行构建

同步到服务器后：
```bash
# 仅构建 admin
bash deploy/scripts/deploy.sh build-admin

# 构建 + 替换
bash deploy/scripts/deploy.sh update-admin

# 全量（app + admin）
bash deploy/scripts/deploy.sh update-all
```

---

## 3. 环境变量管理

### 服务器 `.env`（`backend/.env`）

由服务器侧独立维护，**不能**从本地同步覆盖。关键变量：

```bash
APP_ENV=production
APP_SECRET=...
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/postgraduate
REDIS_URL=redis://redis:6379/0
DEEPSEEK_API_KEY=...
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID=...   # 番茄钟订阅消息模板 ID（未配置则跳过推送）
POMODORO_NOTIFY_ENABLED=true                # 后端调度器总开关
POMODORO_NOTIFY_PAGE=pages/pomodoro/pomodoro
POMODORO_SCHEDULER_INTERVAL_SEC=60
OCR_ENABLED=true
GUNICORN_WORKERS=1
POSTGRES_USER=postgraduate
POSTGRES_PASSWORD=...
POSTGRES_DB=postgraduate
CODE_DETECTOR_ENABLED=true   # 灰度开启
SQL_ECHO=false               # 默认关闭 SQL 全量日志
SQL_LOG_LEVEL=WARNING        # sqlalchemy.engine 日志级别
SLOW_QUERY_MS=500            # 慢查询阈值（毫秒）
```

> 番茄钟通知调度器在 `lifespan` 中通过 `AsyncIOScheduler` 启动，Redis 锁 `pomodoro:scheduler:tick` 防多实例重叠。详见 `docs/architecture/POMODORO_NOTIFICATION.md`。

### 生产 OCR Profile

由 `backend/app/core/ocr_profile.py` 定义，自动根据 `APP_ENV` 加载：

| 参数 | 值 | 说明 |
|------|----|------|
| `use_gpu` | `true` | GPU 加速（需服务器配置 GPU 驱动和 CUDA） |
| `max_workers` | `1` | OCR 并发线程数（与 Gunicorn workers 一致） |
| `max_pdf_pages` | `30` | 单次 PDF 最大页数 |
| `timeout_seconds` | `300` | 单次 OCR 超时 |
| `min_image_width` | `1200` | 图像最小宽度 |
| `allowed_source_types` | `pdf, image, txt` | 允许的上传类型 |
| `max_upload_bytes` | `5 MB` | 单文件大小限制 |

### pip 国内镜像源

Dockerfile 中 `pip install` 当前使用阿里云镜像加速：

```dockerfile
RUN pip install --no-cache-dir --user \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
```

服务器带宽有限（~20KB/s），不使用国内源时 PaddlePaddle（194MB）等大包下载需要数小时。阿里云源可将 build 时间从数小时缩短至 2-3 分钟。

如阿里云不可用，备选：
- 清华：`https://pypi.tuna.tsinghua.edu.cn/simple/`
- 中科大：`https://pypi.mirrors.ustc.edu.cn/simple/`

### Docker layer cache 保留

- `requirements.txt` → `pip install` 在 builder 前一阶段
- `requirements-ocr.txt` → `pip install` 在独立层（PaddleOCR ~500MB）
- PaddleOCR 模型预下载到 `/root/.paddleocr/`，构建时打包到镜像
- 日常 `update` 不使用 `--no-cache` 或默认 `--pull`
- 修改 `requirements.txt` 或 `requirements-ocr.txt` 会破坏对应 layer cache，触发完整重新下载

---

## 4. 禁止操作

以下动作**禁止**作为日常部署默认操作：

- ❌ `docker compose down` — 会停止 postgres/redis/nginx
- ❌ `docker compose build --no-cache` — 破坏 layer cache
- ❌ `docker compose pull` — 不需要每日检查基础镜像更新
- ❌ `docker system prune -a` — 清除所有未使用镜像
- ❌ 删除 Docker volumes — 会导致 PostgreSQL 数据丢失
- ❌ 从本地覆盖服务器 `backend/.env`、`cert/`、密钥
- ❌ 默认执行数据库迁移（迁移应为显式操作）

---

## 5. 历史入口说明

以下路径已降级为历史/备用，**不**作为当前生产推荐入口：

| 路径 | 状态 | 说明 |
|------|------|------|
| `deploy/docker-compose.yml` | 历史生产 | 已不推荐使用 |
| `deploy/docker-compose.dev.yml` | 开发入口 | 仅开发场景 |
| `deploy/deploy.sh` | 兼容转发 | 转发到 `deploy/scripts/deploy.sh` |
| `deploy/backup.sh` | 兼容转发 | 转发到 `deploy/scripts/backup.sh` |
| `deploy/scripts/init-db.sh` | 历史 | 使用 `deploy.sh migrate` 替代 |
| `backend/docker/docker-compose.yml` | 历史 | 已从服务器清理 |

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
2. **备份** — `bash deploy/scripts/backup.sh` + Redis RDB（`redis-cli SAVE`）
3. **数据库迁移**：
   ```bash
   cd /opt/2240ai-v2
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
