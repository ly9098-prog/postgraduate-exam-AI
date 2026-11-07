# 部署方案

> 更新时间：2026-11-08
> 2026-11-08 变更：发布记录与问题史拆分——生产发布记录（原 §0.1–0.3、§6–§8）移至 [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]]，部署问题与修复记录（原 §9.x）移至 [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]]；章节编号沿用原文件，对应关系见下文「拆分内容索引」。本文件保留现行部署架构、流程、环境变量与操作约束。
> 生产入口：`deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`

> 2026-11-04 变更：登记内部 readiness 探针必须带生产域名 Host 头。生产 `ALLOWED_HOSTS` 生效后，
> 不带 Host 的探针会触发可信主机校验失败；公网 `/health/ready` 仍由 nginx 保护，不能替代内部探针。
> 首次检查返回非 200 时，先用同一探针核验旧镜像，避免把探针配置错误误判为新版本回滚触发条件。
>
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

## 拆分内容索引（2026-11-08）

| 原章节 | 内容 | 现位置 |
|--------|------|--------|
| §0.1–0.3 | 2026-11-06 三次生产发布（科目目录匿名读取、共享 AI 健康与预热重试、AI 审查收敛） | `docs/project/DEPLOY_CHANGELOG.md` §0 |
| §6 | 数据库迁移审计（2026-06-28） | `docs/project/DEPLOY_CHANGELOG.md` §6 |
| §7 | 生产强化部署说明（2026-07-25，含 PROCESS_ROLE、连接预算与启动自检清单） | `docs/project/DEPLOY_CHANGELOG.md` §7 |
| §8 | 生产强化 Batch 8–11（2026-07-26；§8.8 含 readiness Host 头探针验证清单） | `docs/project/DEPLOY_CHANGELOG.md` §8 |
| §9.1–9.5 | 部署问题与修复（worker 缺失、worker 校验、函数图渲染慢、model_name bug、容器时区） | `docs/project/DEPLOY_BUGS_HISTORY.md` §9 |

> 外部活跃文档按 § 编号的引用已同步改指新文件；`prompts/` 历史任务记录中的 § 引用按本索引对照，不改写原文。

---

## 相关链接

- [[docs/project/DEPLOY_CHANGELOG.md|DEPLOY_CHANGELOG]] — 生产发布与部署变更记录
- [[docs/project/DEPLOY_BUGS_HISTORY.md|DEPLOY_BUGS_HISTORY]] — 部署问题与修复记录
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/REDIS_USAGE.md|REDIS_USAGE]] — Redis 使用与备份恢复
