# Stage 15: 上线部署

## 1. 阶段目标

完成从开发到正式上线的最后一公里，包括 HTTPS 证书、域名、Docker Compose 部署、CI/CD 流水线、自动备份、异常监控和日志系统，确保服务可以稳定运行。

## 2. MVP 范围

### 能做

- HTTPS 证书自动续签（Let's Encrypt + Nginx）
- 域名 DNS 配置指导和脚本
- Docker Compose 一键部署（含所有服务）
- CI/CD 流水线（GitHub Actions）
- PostgreSQL 自动备份
- Sentry 异常监控
- 结构化日志系统
- 健康检查端点
- 部署验证脚本

### 禁止做

- 不做 Kubernetes 集群
- 不做多区域部署
- 不做蓝绿部署（MVP 停机更新即可）
- 不做灰度发布
- 不做全链路压测

## 3. 非目标

- 不实现自动扩缩容
- 不实现多租户隔离
- 不实现 SLA 99.99%（MVP 99.9% 即可）
- 不实现数据库读写分离

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `deploy/docker-compose.yml` | 生产 Docker Compose 配置 |
| `deploy/docker-compose.dev.yml` | 开发 Docker Compose 覆盖 |
| `deploy/nginx/nginx.conf` | Nginx 配置 |
| `deploy/nginx/ssl/` | SSL 证书目录（占位） |
| `deploy/scripts/init-db.sh` | 数据库初始化脚本 |
| `deploy/scripts/backup.sh` | 自动备份脚本 |
| `deploy/scripts/deploy.sh` | 部署脚本 |
| `deploy/scripts/health-check.sh` | 健康检查脚本 |
| `deploy/.env.example` | 环境变量模板 |
| `deploy/Makefile` | 常用操作快捷命令 |
| `.github/workflows/deploy.yml` | CI/CD 部署流水线 |
| `backend/app/api/v1/health.py` | 健康检查端点 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/Dockerfile` | 生产构建配置（若有） |
| `.gitignore` | 添加部署敏感文件忽略规则 |
| `backend/app/core/config.py` | 新增部署相关配置项 |
| `README.md` | 部署说明 |

## 5. 数据库变更

无数据库结构变更。新增以下数据库维护脚本：

### 备份脚本

```bash
#!/bin/bash
# deploy/scripts/backup.sh
# PostgreSQL 自动备份（建议 cron 每日执行）

BACKUP_DIR="/data/backups/postgres"
DB_NAME="2240ai"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

pg_dump -h localhost -U postgres $DB_NAME | gzip > "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

# 保留最近 30 天备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
```

## 6. API 设计

### 新增：健康检查端点

```
GET /api/v1/health
```

**Response (200 OK):**
```json
{
    "status": "ok",
    "version": "1.0.0",
    "timestamp": "2025-05-24T10:00:00Z",
    "uptime": 3600,
    "services": {
        "database": {"status": "ok", "latency_ms": 2},
        "redis": {"status": "ok", "latency_ms": 1},
        "ai_api": {"status": "ok"}
    }
}
```

**Response (503 Service Unavailable):**
```json
{
    "status": "degraded",
    "services": {
        "database": {"status": "ok"},
        "redis": {"status": "unavailable"}
    }
}
```

### 新增：版本信息端点

```
GET /api/v1/version
```

**Response:**
```json
{
    "version": "1.0.0",
    "build_at": "2025-05-24T10:00:00Z",
    "commit": "abc123",
    "environment": "production"
}
```

## 7. 部署架构

### Docker Compose 服务拓扑

```
nginx (反向代理 + SSL)
  └── app (FastAPI + Uvicorn, 4 workers)
       └── db (PostgreSQL 15)
       └── redis (Redis 7, 可选)
```

### 网络设计

```
services:
  nginx:
    ports: ["443:443", "80:80"]
    depends_on: [app]

  app:
    expose: ["8000"]
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/2240ai
      - REDIS_URL=redis://redis:6379/0
    depends_on: [db, redis]

  db:
    expose: ["5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    restart: always

  redis:
    expose: ["6379"]
    restart: always
```

### CI/CD 流水线（GitHub Actions）

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          cd backend
          pip install -r requirements.txt
          python -m pytest tests/ -v

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_KEY }}
          script: |
            cd /app/2240ai
            git pull origin main
            docker compose -f deploy/docker-compose.yml down
            docker compose -f deploy/docker-compose.yml build
            docker compose -f deploy/docker-compose.yml up -d
```

## 8. 运维配置

### Nginx 配置要点

```nginx
server {
    listen 443 ssl http2;
    server_name api.2240ai.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    # 安全头
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    # API 代理
    location /api/ {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }

    # WebSocket（未来用）
    location /ws/ {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name api.2240ai.com;
    return 301 https://$host$request_uri;
}
```

### 环境变量管理

```bash
# deploy/.env.example
APP_SECRET=change-me
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/2240ai
DEEPSEEK_API_KEY=sk-xxx
WECHAT_APP_ID=wx-xxx
WECHAT_APP_SECRET=xxx
OCR_ENABLED=false
REDIS_URL=redis://redis:6379/0

# 生产配置
ENVIRONMENT=production
LOG_LEVEL=info
WORKERS=4
MAX_CONNECTIONS=100

# Sentry
SENTRY_DSN=https://xxx@sentry.io/xxx
```

### Sentry 集成

```python
# app/core/sentry.py
import sentry_sdk
from app.core.config import settings

def init_sentry():
    if settings.ENVIRONMENT == "production" and settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            traces_sample_rate=0.1,
        )
```

## 9. 监控和告警

### 日志系统

```python
# 使用 structlog 或标准 logging + JSON 格式
logging_config = {
    "version": 1,
    "formatters": {
        "json": {
            "format": '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}
```

### 健康检查频率

- Docker healthcheck：每 30 秒
- 外部监控：每 5 分钟
- 证书续签检查：每天

### 备份策略

| 数据 | 频率 | 保留 | 存储 |
|------|------|------|------|
| PostgreSQL | 每日 03:00 | 30 天 | 本地 + S3 |
| 配置文件 | 每次变更 | 永久 | Git |
| 日志 | — | 7 天 | Docker 日志驱动 |

## 10. 测试计划

### 新增测试文件

`backend/tests/test_api/test_health.py`

| 测试用例 | 描述 |
|---------|------|
| `test_health_endpoint` | 健康检查返回 200 |
| `test_health_db_unavailable` | DB 不可用时返回 503 |
| `test_version_endpoint` | 版本信息端点 |
| `test_version_contains_build_info` | 版本含构建信息 |

### 部署验证

```bash
# 部署后验证脚本
./deploy/scripts/health-check.sh api.2240ai.com
# 检查：
# 1. HTTPS 证书有效
# 2. /api/v1/health 返回 200
# 3. /api/v1/version 返回版本信息
# 4. 数据库连接正常
# 5. 所有 API 端点可访问
```

## 11. 风险与兼容性

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 证书过期 | HTTPS 不可用 | 自动续签 + 过期告警 |
| 数据库故障 | 服务不可用 | 每日备份 + 恢复演练 |
| 部署回滚 | 新版本出问题 | 保留上个版本的 Docker 镜像 |
| 环境变量泄露 | 安全风险 | .env 不纳入 Git，严格权限控制 |
| DDOS 攻击 | 服务不可用 | Nginx rate limit + fail2ban（可选） |

## 12. 开发顺序

### Step 1: 基础设施

- Docker Compose 配置
- Nginx 配置 + SSL 证书
- 环境变量模板

### Step 2: 健康检查 + 监控

- 健康检查端点
- Sentry 集成
- 结构化日志

### Step 3: 备份 + 运维脚本

- 数据库备份脚本
- 部署脚本
- Makefile

### Step 4: CI/CD

- GitHub Actions 流水线
- 自动化测试 + 部署

### Step 5: 部署验证

- 完整部署演练
- 恢复演练
- 性能验证

## 13. 验收标准

- [ ] 完整部署文档编写完成
- [ ] Docker Compose 一键部署成功
- [ ] HTTPS 证书自动续签配置完成
- [ ] 健康检查端点正常工作
- [ ] Sentry 异常监控接入完成
- [ ] PostgreSQL 自动备份配置完成
- [ ] CI/CD 流水线通过
- [ ] 部署验证脚本全部通过
- [ ] 回滚方案文档化
- [ ] 运维文档完整

## 14. 服务器信息

| 项目 | 值 |
|------|-----|
| 公网 IP | 8.163.56.109 |
| 内网 IP | 172.18.50.44 |
| 域名 | xzshub.top |
| 服务器密钥路径 | `/loginkey.pem` |

## 15. 部署路径

| 版本 | 部署路径 | 说明 |
|------|---------|------|
| 旧版 (Stage 1-11) | `/opt/2240ai/` | 已在服务器上运行的旧版本，合入 SSH deploy 脚本中 |
| 新版 (Stage 12+) | `/opt/2240ai-v2/` | 建议另起新目录，与旧版隔离，回滚时保留旧版不动 |

### 部署路径说明

- **旧版 `/opt/2240ai/`**：已在生产运行，CI/CD deploy 脚本中默认路径为此。如需修改需同步更新 GitHub Actions secrets 和 deploy 脚本。
- **新版 `/opt/2240ai-v2/`**：建议另起新目录，与旧版完全隔离。好处是：
  - 回滚时旧版不动，只需切换 Nginx upstream
  - 新版部署失败不影响旧版运行
  - 可并行运行进行灰度验证
- CI/CD 切换新路径后，`appleboy/ssh-action` 中的 `script` 需对应改为 `cd /opt/2240ai-v2 && ...`
