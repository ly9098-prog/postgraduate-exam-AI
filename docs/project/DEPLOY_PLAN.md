# 部署方案

> 更新时间：2026-10-23
> 2026-10-23 变更：Redis 备份/恢复路径与脚本默认值一致保留；移除 §9.6/§9.7 两条生产补录番茄钟记录（一次性运维操作，留痕移至 docs/project/CHANGELOG.md）。
> 生产入口：`deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`

> ✅ **Pomodoro V2 迁移已完成（2026-08-08）**：历史 Pomodoro 数据已规范化到 V2 canonical 模型，
> legacy compatibility 已删除，生产运行新 runtime（alembic `f6e7a8b9c0d1`）。执行记录见
> **[POMODORO_V2_MIGRATION.md](./POMODORO_V2_MIGRATION.md)** §8。

---

## 0. 服务器迁移状态

生产已迁移至 `101.33.231.186`，该服务器是当前唯一生产入口。旧服务器已停用，不再作为生产、冷备或回滚目标；本文不保留其连接信息。

迁移期间完成的事项：应用代码与镜像、PostgreSQL 数据、Redis 数据、Nginx 配置与 SSL 证书、服务器环境配置迁移，以及生产自检和核心链路验证（SSE / 导入 / OCR / 刷题）。

---

## 1. 生产部署架构

### 服务组成

| 服务 | 容器名 | 说明 |
|------|--------|------|
| `app` | deploy-app-1 | FastAPI + Gunicorn，源码构建 |
| `scheduler` | deploy-scheduler-1 | 后台调度器（定时任务 + export processor），与 app 共用镜像但无 HTTP |
| `nginx` | deploy-nginx-1 | nginx:1.25-alpine，HTTPS 反代 |
| `postgres` | deploy-postgres-1 | PostgreSQL 15，持久卷 pgdata_prod |
| `redis` | deploy-redis-1 | Redis 7，持久卷 redisdata_prod，AOF everysec + noeviction |
| `admin` | deploy-admin-1 | Next.js 管理前端（仅内网 3000） |

### 网络拓扑

```
用户 → nginx:443 (HTTPS) → app:8000 (HTTP)
                      → postgres:5432（仅 app/scheduler 可访问）
                      → redis:6379（仅 app/scheduler 可访问）
scheduler（无 HTTP）→ postgres + redis（后台任务 + export processor）
```

### 关键路径

| 路径 | 说明 |
|------|------|
| `deploy/docker-compose.prod.yml` | **当前生产 compose 入口**（含 app + scheduler + admin） |
| `deploy/scripts/deploy.sh` | **当前推荐生产部署脚本** |
| `deploy/nginx/nginx.conf` | Nginx 配置 |
| `deploy/scripts/backup.sh` | 备份脚本 |
| `backend/docker/Dockerfile` | app + scheduler 共用镜像 Dockerfile（含 PaddleOCR） |
| `backend/.env` | 服务器侧环境变量（独立维护） |

### 当前生产服务器

| 项目 | 当前生产服务器 |
|------|----------------|
| 公网 IP | `101.33.231.186` |
| 内网 IP | `10.1.0.13` |
| 部署目录 | `/opt/22408-ai` |
| 本地连接密钥 | `Linux_connect.pem` |
| 域名 | `xzshub.top` |
| 证书目录 | `/opt/22408-ai/cert` → 容器内 `/etc/nginx/ssl` |
| 证书文件 | `/opt/22408-ai/cert/www.xzshub.top.pem` + `.key` |

服务器规格：4 核 / 3.6 GiB 内存 / 40 GB 磁盘，OpenCloudOS 9.6（RPM 系）。构建前先 `df -h` 检查磁盘空间；主机级操作（包管理、firewalld、certbot）使用 RPM 系对应命令。

---

## 2. 部署流程

### 2.1 同步代码到服务器

使用 `.deployignore` 排除敏感文件和本地产物：

```bash
rsync -az --exclude-from=".deployignore" \
  -e "ssh -i Linux_connect.pem -o BatchMode=yes" \
  ./ root@101.33.231.186:/opt/22408-ai/
```

排除范围：`.git/`、`.claude/`、`.venv/`、`node_modules/`、`__pycache__/`、`*.db`、`.env`、`*.pem`、`*.key`、`docs/`、`prompts/`、测试文件、日志、上传目录等。

> 当本地删除了前端页面文件时，需加 `--delete` 参数同步删除服务器上的对应文件，否则 Next.js build 会因死代码引用报错。示例：
> ```bash
> rsync -az --delete --exclude-from=".deployignore" \
>   -e "ssh -i Linux_connect.pem -o BatchMode=yes" \
>   ./ root@101.33.231.186:/opt/22408-ai/
> ```

### 2.2 日常更新（app + admin）

构建并替换服务，不重启 postgres/redis/nginx。

**更新 app 后端：**
```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh update
```

**更新 admin 前端：**
```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh update-admin
```

内部执行：
1. `docker compose build <service>`（保留 Docker layer cache）
2. `docker compose up -d --no-deps <service>`（只替换目标服务）
3. 健康检查：app 容器内 `/health` + nginx HTTPS `/health`

> **⚠️ app/scheduler 容器重建后必须 reload nginx（2026-08-07 实测踩坑）。**
> `upstream backend { server app:8000; }` 在 nginx 启动时把 `app` 解析成当时的容器 IP；`up -d --no-deps app` 重建容器后 IP 变化，nginx 仍连旧 IP → `www.xzshub.top/api/*` 全部 502（`/` 走 admin 不受影响，因 admin 容器常未重建、IP 未变）。
>
> 诊断：`docker exec deploy-nginx-1 wget -qO- http://app:8000/health` 能通（新 IP）但 nginx 反代 502。
>
> **修复：**
> ```bash
> docker exec deploy-nginx-1 nginx -s reload   # graceful，重新解析 upstream，无连接中断
> ```
>
> 每次 `deploy.sh update`（或任何重建 app/scheduler 容器的操作）后都建议执行一次 reload；若更新后 `curl https://www.xzshub.top/api/v1/health` 非 200，先 reload nginx 再排查其它。

> **X-Forwarded-For 信任边界（2026-10-31 安全审计修复）：** `deploy/nginx/nginx.conf` 所有反代 location 一律 `proxy_set_header X-Forwarded-For $remote_addr;`（覆盖而非追加客户端自带的 XFF），否则攻击者可伪造 XFF 绕过按 IP 的登录限流。后端 Dockerfile 仍为 `--forwarded-allow-ips=*`，依赖 app 端口仅绑定 `127.0.0.1:8000`（同 compose 网络内的容器仍可直连 app，需自行保证其可信）；不要把 8000 暴露到公网。若日后在 nginx 前加 CDN/LB，必须同时配置 `set_real_ip_from <LB CIDR>` + `real_ip_header`，否则所有客户端共用同一限流桶。`nginx.conf` 是文件级 bind mount，上线需 `--force-recreate nginx`（见上文）。生产服务器尚未应用此改动，待授权后随部署同步。

### 2.3 查看状态

```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh status
```

输出各容器状态、健康检查和接口可达性。

### 2.4 显式迁移

仅在 schema 变更确认后执行：

```bash
cd /opt/22408-ai
bash deploy/scripts/deploy.sh migrate
```

> **注意**：生产环境 PostgreSQL 与本地 SQLite 有差异。部分旧 migration 包含 SQLite 专用代码（`sqlite_master` 查询、`DROP INDEX` 无 `IF EXISTS`、未捕获的约束已存在异常）。遇到此类失败时，使用 `docker compose exec -T app alembic upgrade <target>` 逐条迁移，对 SQLite-only 操作可 `alembic stamp` 跳过（已验证：`c07a8112c2f2`、`d1e2f3a4b5c6`、`f2e3a4b5c6d7` 均已修复）。

### 2.5 回滚

若新 app 启动失败：
1. 查看日志 `docker compose logs --tail=80 app`
2. 不执行 `down` 或删除 volume
3. 回滚代码到上一版本 → 重新 `bash deploy/scripts/deploy.sh update`

### 2.6 Admin 前端构建注意事项（内存）

生产服务器规格为 4 核 / 3.6 GB 内存。Admin 前端 Next.js 构建是内存敏感操作：

| 措施 | 说明 |
|------|------|
| `NODE_OPTIONS=--max-old-space-size=2048` | Dockerfile 中限制 Node.js 堆上限，防止 OOM（3.6G 环境使用 2048） |
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

### 2.7 生产后端镜像不安装本地 OCR 依赖

生产使用 PaddleOCR-VL 外部 HTTP API，`app`、`scheduler` 和 `worker` 不在容器内运行本地 PaddleOCR。生产 compose 为后端 Dockerfile 传入 `INSTALL_OCR=false`，因此构建会跳过 `paddlepaddle`、`paddleocr` 及其 OCR 专用依赖安装，显著减少构建时间、镜像体积和内存占用。

`python-docx`、Pillow 和 NumPy 虽被 OCR 流程复用，但也是导出、图片处理和公式渲染的运行时依赖，已放入 `requirements.txt`，不能随 OCR 依赖一起跳过。

`backend/docker/Dockerfile` 的默认值仍为 `INSTALL_OCR=true`，供本地 OCR 开发环境使用；不要把本地 OCR 依赖重新加入生产构建参数。生产 OCR 相关环境变量保持：

```yaml
OCR_USE_GPU: "false"
OCR_EXECUTION_BACKEND: "disabled"  # worker；web 使用外部 OCR 配置
```

生产更新 app、scheduler 或 worker 时，确认构建日志包含 `Skipping optional OCR dependencies`，并检查 app 启动日志无 `ModuleNotFoundError`。若服务器上已有旧 OCR 镜像，重建服务后旧镜像仍可能保留，按常规镜像清理流程处理，禁止影响运行中容器和数据卷。

### 2.8 admin-frontend 构建上下文污染防护（2026-08-07）

> 迁移到新服务器后实测：该问题曾 **4 次** 导致 admin 构建出损坏产物、全部业务路由丢失（只生成 /404）。

**问题现象：** `admin/` 前端构建异常，任一路由返回 500/404，`docker run --rm deploy-admin sh -c "wc -c < /app/.next/server/app-paths-manifest.json"` 只有 ~104B（正常 ~1546B）。

**根因：** 仓库根目录（含 FastAPI 后端包 `app/`、`backend/`、`alembic/`、`node_modules/`、几十个 `*.db` 等）被误 rsync 进 `/opt/22408-ai/admin-frontend/`。Next.js 16 Turbopack 将根级 `app/`（Python 后端包，无有效页面）误判为 App Router 目录并**优先于 `src/app/`** → 只生成默认 /404，全部业务路由缺失。污染文件还会占满 40G 磁盘。

**防护（已生效）：** `admin-frontend/.dockerignore` 增加根级锚定排除：

```dockerignore
/app/
/alembic/
/backend/
/docs/
/miniprogram/
/prompts/
/deploy/
/tools/
/utils/
/reports/
/fix/
/ocr_test/
/artifacts/
/rag/
/var/
```

> ⚠️ **必须带前导 `/`（锚定根级）**。若写成 `app/`（未锚定）会同时排除 `src/app/`，报 `Couldn't find any pages or app directory`，构建同样失败。

**预防与排查：**
- 部署 rsync 目标**必须**是 `/opt/22408-ai/`（仓库根）。**禁止**把仓库根目录 rsync 进 `admin-frontend/`（正确命令见 §2.1，目标路径不带子目录）。
- admin 构建异常（"no app directory" / 只生成 /404 / ChunkLoadError）→ **先检查** `/opt/22408-ai/admin-frontend/` 是否被仓库根目录污染，再考虑其他原因。
- 服务器 40G 磁盘易被 Docker 镜像/构建缓存占满。构建前 `df -h /` 检查；缓存过大时 `docker builder prune -af` 清理（曾一次释放 12.6G，安全，不影响运行中容器/镜像）。
- 新机 admin `NODE_OPTIONS` 已按 3.6G 内存由 1536 调整为 2048（`admin-frontend/Dockerfile`），在干净上下文下构建正常。

---

## 3. 环境变量管理

### 服务器 `.env`（`backend/.env`）

由服务器侧独立维护，**不能**从本地同步覆盖。关键变量：

```bash
APP_ENV=production
APP_SECRET=...
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/postgraduate
REDIS_URL=redis://redis:6379/0
AI_CONFIG_ENCRYPT_KEY=...                      # AI 模型凭据加密密钥（凭据存 DB admin_ai_model_configs）
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
| `use_gpu` | `false` | 生产不加载本地 PaddleOCR；OCR 通过外部 HTTP API 完成 |
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
    -r requirements.txt
```

2026-10-31 安全审计修复：已移除 `--trusted-host mirrors.aliyun.com`。该参数会让 pip 对该主机跳过 TLS 证书校验（即使地址是 `https://`），镜像源本身证书有效，无需该参数；`backend/tests/test_deploy_dockerfile_pip_tls.py` 防止回退。后端镜像（`backend/docker/Dockerfile`）现从 `backend/requirements.lock` 以 `pip install --require-hashes --no-deps` 安装，锁文件由 `uv pip compile requirements.txt -c <生产 pip freeze> --python-version 3.11 --python-platform linux --generate-hashes --index-url https://mirrors.aliyun.com/pypi/simple/ -o requirements.lock` 生成（以生产镜像版本为约束，针对构建实际使用的阿里云镜像解析；直接按 pypi.org 解析会选到镜像尚未同步的版本而构建失败）；修改 `requirements.txt` 后必须重新生成，`backend/tests/test_deploy_requirements_lock.py` 检查覆盖。可选的 `requirements-ocr.txt`（仅 `INSTALL_OCR=true` 的本地镜像）和 `deploy/Dockerfile.prod`、`backend/Dockerfile`（开发用）仍未锁定。

服务器带宽有限（~20KB/s），不使用国内源时运行时依赖下载可能需要较长时间。阿里云源可缩短后端镜像构建时间。

如阿里云不可用，备选：
- 清华：`https://pypi.tuna.tsinghua.edu.cn/simple/`
- 中科大：`https://pypi.mirrors.ustc.edu.cn/simple/`

### Redis 持久化、容量与备份

生产 Redis 显式配置（`deploy/docker-compose.prod.yml`）：

```yaml
command:
  - redis-server
  - --appendonly
  - "yes"
  - --appendfsync
  - everysec
  - --maxmemory
  - 192mb
  - --maxmemory-policy
  - noeviction
```

设计要点：

- **AOF everysec**：任务队列、JWT 黑名单/nbf、fencing 计数、暂存引用计数都是不可丢失状态；崩溃最多丢约 1 秒写入。
- **noeviction**：禁止因内存压力淘汰队列/锁/黑名单键。达到 `maxmemory` 时写入失败，由上层 fail-closed 并告警，而不是静默丢数据。
- **容器上限 256m / maxmemory 192mb**：差值留给 AOF 重写缓冲、分配器碎片。生产实测数据仅约 2.3MB，192MB 有充足余量。

备份与还原：

```bash
cd /opt/22408-ai

# 备份 PostgreSQL + Redis（推荐）
bash deploy/scripts/deploy.sh backup

# 仅备份 Redis
bash deploy/scripts/deploy.sh backup-redis
bash deploy/scripts/redis_backup.sh list

# 从 RDB 安全恢复（脚本会停止 Redis、快照旧数据、重建 AOF 后再启动）
bash deploy/scripts/deploy.sh redis-restore /opt/22408-ai/redis_backups/<backup>.rdb

# 也可通过 Makefile 调用
cd deploy && make redis-restore BACKUP=/opt/22408-ai/redis_backups/<backup>.rdb
```

> Redis 备份通过 `BGSAVE` 生成原生 RDB 快照；默认归档到宿主机 `/opt/22408-ai/redis_backups`，脚本校验文件头并以时间戳归档，默认保留 14 天（`REDIS_BACKUP_RETENTION_DAYS`）。备份文件不会写入 Redis 命名卷；如需改目录，可设置宿主机路径 `REDIS_BACKUP_DIR`。请将 Redis 备份纳入与 PostgreSQL 相同的异地/离线保留策略。
>
> **为什么需要专用恢复脚本**：生产已开启 AOF，直接替换 `/data/dump.rdb` 后 `docker restart` 会优先加载 `appendonlydir`，可能表现为恢复后 `DBSIZE=0`。`redis_restore.sh` 会先保留旧数据目录快照，清空旧 AOF/RDB，使用临时 Redis 从 RDB 加载并校验 `DBSIZE>0`，再触发 AOF 重写，最后恢复生产容器并校验 `PING`、`DBSIZE`、`INFO persistence`。
>
> 详细键空间、失败降级矩阵与遗留风险见 **[docs/architecture/REDIS_USAGE.md](../architecture/REDIS_USAGE.md)**。

### Docker layer cache 保留

- `requirements.txt` → `pip install` 在 builder 前一阶段
- 生产构建传入 `INSTALL_OCR=false`，不会安装 `requirements-ocr.txt` 或 `paddleocr`
- 本地 OCR 开发构建可保留默认 `INSTALL_OCR=true`，不作为生产镜像来源
- 日常 `update` 不使用 `--no-cache` 或默认 `--pull`
- 修改 `requirements.txt` 会破坏运行时依赖 layer cache，触发重新下载

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

## 9. 2026-08-15/16 部署问题与修复记录

> 本节记录本次全量部署过程中发现并修复的生产问题，供后续部署参考。

### 9.1 生产 Redis 任务队列无消费者（worker 服务缺失）— 重大

**现象：** 任务健康监控持续报 `ANSWER_PROJECTION_BACKLOG` + `QUEUE_STALLED`；practice_records 多条无 `answer_behaviors` 投影回执，对账器每小时重建修复任务但无人执行。

**根因：** 生产 compose 只有 web + scheduler，**没有 `worker` 服务**。`run_dispatcher_v2`（Redis `taskq:v2:*` 唯一消费方）仅在 `PROCESS_ROLE=worker` 时启动；scheduler 的 outbox dispatcher 只负责把 outbox 发布到 Redis，不消费。因此掌握度/Leitner/自适应/推荐反馈等派生状态从未更新。

**修复：** `deploy/docker-compose.prod.yml` 新增 `worker` 服务（与 scheduler 同镜像，`python -m app.worker_main`，mem_limit 384m，挂 `exports_data` 卷）。

**验证：** worker 启动后 `v2 Dispatcher started`，投影积压清零，健康监控 `Async task health recovered`。

> ⚠️ **`deploy.sh update-all` 只重建 app+scheduler+admin，不覆盖 worker。** worker 需单独执行：
> ```bash
> docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml build worker
> docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml up -d --no-deps worker
> ```

### 9.2 worker 服务生产校验要点（启动被拦截的坑）

worker 启动经过两道校验，缺一不可：

| 校验 | 要求 | 坑 |
|------|------|-----|
| `production_config_validator` | `OCR_USE_GPU` 必须显式 `false`（对所有角色强制，config 默认 True） | 漏配即拒绝启动 |
| 同上 | `EXPORT_DIR` 目录可写 | 必须显式 `EXPORT_DIR=/opt/22408-ai/exports` 且挂 `exports_data` 卷（首次挂载继承镜像 chown 的 app:app）；漏配会按相对路径 `var/exports` 创建失败 |
| `OcrRuntimeConfig`（`_init_worker_dependencies` 无条件调用 `get_runtime_config()`） | `OCR_EXECUTION_BACKEND=disabled` 时无需 remote token | 若为 `paddlex_http` 且 production，强制要求 `remote_auth_token` |

**OCR 配置原则：** 服务器 OCR 仅由 **web 进程经外部 API**（PaddleOCR-VL aistudio，paddlex_http）完成，worker 不承载 OCR。因此 worker 环境硬编码：

```yaml
OCR_USE_GPU: ${OCR_USE_GPU:-false}
OCR_EXECUTION_BACKEND: "disabled"
```

> ⚠️ `OCR_EXECUTION_BACKEND` 必须**硬编码 `disabled`**，不可写 `${OCR_EXECUTION_BACKEND:-disabled}`——服务器 `.env` 的 `paddlex_http` 会覆盖变量默认值，导致 worker 再次因缺 `remote_auth_token` 拒绝启动。

### 9.5 函数图像真机渲染慢优化（2026-09-20）

**现象：** 管理端上传的函数图像在miniprogram函数图像列表页（`subpackages/formulas/library`）与速记卡阅读页（`subpackages/formulas/reader`）真机渲染明显缓慢，列表滚动时图像逐张长时间空白。

**根因（按影响排序）：**
1. **上传主图未压缩**：`formula_graph_asset_service` 曾按原图存储（最大 8000×8000、10MB），PNG 无损未优化；生成型图像固定 1600×1000 PNG。真机经 HTTPS 拉取数 MB 图像耗时数秒。
2. **列表页加载大图**：`graphPreviewUrl` 优先取 `graphImageUrl`（全尺寸主图），而列表卡片显示区仅 360rpx 高。
3. **阅读页无渐进加载**：仅挂大图 URL，慢网络下长时间空白。

**修复：**
- 后端上传路径（`backend/app/services/formula_graph_asset_service.py`）：主图统一缩放至长边 ≤1600（`MAX_STORED_DIMENSION`）并 PNG `optimize` 重编码；缩略图同样 `optimize`。仅影响新上传。
- 存量回填（`backend/scripts/backfill_formula_graph_image_size.py`，`--dry-run`/`--apply`）：本地存储（`STORAGE_BACKEND=local`）的就地重压缩，同对象键覆写并更新 DB 宽高/大小；外部对象存储 URL 自动跳过。服务器执行：
  ```bash
  cd /opt/22408-ai/backend
  docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml exec app \
    python scripts/backfill_formula_graph_image_size.py --dry-run   # 先预览
  # 确认后再 --apply
  ```
- 小程序列表页：`graphPreviewUrl` 改为 `resolveGraphPreviewUrl()`（缩略图优先，无缩略图回退主图），逻辑收敛在 `subpackages/formulas/utils/formula-graph.js`。
- 小程序阅读页：`formula-card` 组件渐进加载——先显示缩略图，页内隐藏 preloader `<image>` 预载主图，`bindload` 后切换为主图；主图失败时保留缩略图。状态机 `computeDisplayGraphUrl()` 与列表页共用。
- 小程序阅读页图像显示比例（同日补充修复）：`.fc-graph-image` 曾带历史遗留的 `transform: scale(1.12)`（整体放大 12% 并被 `overflow:hidden` 裁边），且主图用 `widthFix` 按自然比例撑高，加载完成后区块突然变高。现改为**固定宽高比视口**：`fc-graph-viewport` 用内联 `padding-bottom:{{graphViewportRatio}}%` 钉住高度（比例取 `graph_asset.width/height`，钳制 25%–125%，缺元数据回退 75% 即 4:3），图像统一 `aspectFit` 填充（`computeGraphViewportRatio()` 位于 `formula-graph.js`）。缩略图→主图切换零布局跳动，异常长图在视口内 letterbox 显示而非拉伸卡片。
- nginx `/static/formulas/` 已有 `expires 30d; Cache-Control public, immutable`（URL 含内容寻址段），压缩后字节数下降直接减少真机首屏流量；无需改动。

**持久化：** `deploy/docker-compose.prod.yml` 中 app、scheduler、worker 都挂载命名卷 `formulas_data:/app/static/formulas`。运行期上传写在卷内 `graphs/{id}/uploaded`，容器重建不丢图。空卷首次挂载会带入镜像里已有的公式静态文件。

**AI 预热题图：** `prewarm_analysis` 在 worker 中运行，必须与 app 共享 `question_assets_data` 卷；app 与 worker 共同挂载 `/app/static/question-assets`（生产启动校验要求该目录可写）。否则 worker 无法从本地读取运行期上传的题图，在远程抓取不可用时会将有题图的题目误判为 `vision_input_missing`。仅修改 Compose 文件不会更新运行中的容器；应用时需单独重建 worker 容器（不删除卷），并按需手动重试已经进入死信队列的任务。

**回填脚本提交注意：** `.gitignore` 第 98 行忽略 `backend/scripts/`，该目录既有脚本均为 `git add -f` 跟踪；新脚本需同样 `git add -f backend/scripts/backfill_formula_graph_image_size.py`。

**暂存目录：** `WORKER_SCRATCH_DIR=/tmp/scratch` 用容器 1777 `/tmp` 临时区即可，**不要挂命名卷**（命名卷 root 属主，非 root 的 app 用户不可写）。

### 9.3 `ai_service.py` `analyze_error` 的 `model_name` 未定义 bug

**现象：** worker 的 prewarm 任务（以及同步 `/api/v1/ai` 错因解析）全部失败，日志 `NameError: name 'model_name' is not defined`。

**根因：** `result.get("model", model_name or "")` 的默认值会先于 `.get` 求值，而 `model_name` 从未定义，导致任何成功到达该行的 AI 解析都抛 NameError。

**修复：** 两处（`_meta` 与返回响应）改为 `result.get("model", "")`。`chat_with_db_model` 返回始终含 `model` 键，默认值不会触发。

### 9.4 容器时区与北京时间时差

**现象：** 容器日志时间比北京时间慢 8 小时。

**根因：** 服务器系统时区是 `Asia/Beijing`（正确），但 Docker 容器默认 UTC（TZ 为空）。

**修复：** compose 给 app/scheduler/worker/admin 设 `TZ: Asia/Shanghai`。**安全性**：DB 时间戳一律 `utcnow()`（显式 UTC，不受进程 TZ 影响）；APScheduler 显式 `AsyncIOScheduler(timezone="UTC")` 调度不变；产品时区（study_day/pomodoro）用显式 UTC+8 换算。裸 `datetime.now()` 仅用于 ID 后缀/瞬时 Redis 状态/时长差，无入库污染。

> admin 镜像缺 tzdata，容器内 OS `date` 仍显示 UTC；但 Node 进程尊重 `TZ`，SSR 显示北京时间正确，无需处理。
