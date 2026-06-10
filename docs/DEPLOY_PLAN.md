# 部署方案

> 更新时间：2026-06-03
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

### 2.2 日常更新（app-only）

构建并替换 app 服务，不重启 postgres/redis/nginx：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh update
```

内部执行：
1. `docker compose build app`（保留 Docker layer cache）
2. `docker compose up -d --no-deps app`（只替换 app）
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

### 2.5 回滚

若新 app 启动失败：
1. 查看日志 `docker compose logs --tail=80 app`
2. 不执行 `down` 或删除 volume
3. 回滚代码到上一版本 → 重新 `bash deploy/scripts/deploy.sh update`

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
OCR_ENABLED=true
GUNICORN_WORKERS=1
POSTGRES_USER=postgraduate
POSTGRES_PASSWORD=...
POSTGRES_DB=postgraduate
```

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

Dockerfile 中 `pip install` 使用清华源加速：

```dockerfile
RUN pip install --no-cache-dir --user \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt
```

服务器带宽有限（~20KB/s），不使用国内源时 PaddlePaddle（194MB）等大包下载需要数小时。清华源可将 build 时间从数小时缩短至 2-3 分钟。

如清华源不可用，备选：
- 阿里云：`https://mirrors.aliyun.com/pypi/simple/`
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

> 审计日期：2026-06-03
> 目的：确认本地 SQLite（开发/OCR 导入）数据能否安全迁移到生产 PostgreSQL

### 6.1 环境对比

| 项目 | 本地开发 | 生产服务器 |
|------|---------|-----------|
| 数据库引擎 | SQLite | PostgreSQL 15 |
| 数据库文件 | `backend/postgraduate.db` | `postgres` 容器持久卷 |
| Alembic 版本 | `b4e3d2c1f0a9` | `k2a3b4c5d6e7` |
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
