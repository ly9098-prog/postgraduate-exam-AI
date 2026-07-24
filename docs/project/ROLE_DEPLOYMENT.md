# web / worker / scheduler 角色拆分部署指南

> 基于 current_task.md P0-4 和 DEPLOY_PLAN.md

## 概述

`PROCESS_ROLE` 将应用拆分为三个独立进程：

| 角色 | 职责 | 默认并发 |
|------|------|---------|
| `web` | HTTP、鉴权、DB 查询、上传 staging、入队 | GUNICORN_WORKERS=2 |
| `worker` | 导题 pipeline、PDF/OCR/AI/公式、reaper | 1 |
| `scheduler` | 番茄钟、token cleanup、audit cleanup、staging cleanup | 1 |

> `PROCESS_ROLE=all` 仅允许在开发环境使用，production/cloud_api 校验会拒绝。

---

## 1. 环境变量

```bash
# 每个进程设置对应角色
PROCESS_ROLE=web        # 或 worker / scheduler
DEPLOYMENT_PROFILE=cloud_api
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgresql+asyncpg://pguser:pgpass@postgres:5432/postgraduate
```

---

## 2. Docker Compose 拆分示例

```yaml
# deploy/docker-compose.prod.yml (追加到现有配置)

services:
  app-web:
    <<: *app-base
    container_name: deploy-app-web
    environment:
      - PROCESS_ROLE=web
      - GUNICORN_WORKERS=2
    ports:
      - "8000:8000"

  app-worker:
    <<: *app-base
    container_name: deploy-app-worker
    environment:
      - PROCESS_ROLE=worker
    # 不暴露端口
    deploy:
      resources:
        limits:
          memory: 512M

  app-scheduler:
    <<: *app-base
    container_name: deploy-app-scheduler
    environment:
      - PROCESS_ROLE=scheduler
    # 不暴露端口
    deploy:
      resources:
        limits:
          memory: 256M
```

---

## 3. 独立启动命令

### systemd

```ini
# /etc/systemd/system/2240ai-web.service
[Unit]
Description=2240AI Web (HTTP)
After=network.target redis.service postgresql.service

[Service]
Type=notify
User=2240ai
WorkingDirectory=/opt/2240ai-v2/backend
EnvironmentFile=/opt/2240ai-v2/backend/.env
Environment=PROCESS_ROLE=web
ExecStart=/opt/2240ai-v2/backend/.venv/bin/gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/2240ai-worker.service
[Unit]
Description=2240AI Worker (Pipeline/OCR/AI)
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=2240ai
WorkingDirectory=/opt/2240ai-v2/backend
EnvironmentFile=/opt/2240ai-v2/backend/.env
Environment=PROCESS_ROLE=worker
ExecStart=/opt/2240ai-v2/backend/.venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/2240ai-scheduler.service
[Unit]
Description=2240AI Scheduler (Cron/Cleanup)
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=2240ai
WorkingDirectory=/opt/2240ai-v2/backend
EnvironmentFile=/opt/2240ai-v2/backend/.env
Environment=PROCESS_ROLE=scheduler
ExecStart=/opt/2240ai-v2/backend/.venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

### supervisor

```ini
[program:2240ai-web]
command=/opt/2240ai-v2/backend/.venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000
directory=/opt/2240ai-v2/backend
environment=PROCESS_ROLE="web"
user=2240ai
autostart=true
autorestart=true

[program:2240ai-worker]
command=/opt/2240ai-v2/backend/.venv/bin/python -m app.main
directory=/opt/2240ai-v2/backend
environment=PROCESS_ROLE="worker"
user=2240ai
autostart=true
autorestart=true

[program:2240ai-scheduler]
command=/opt/2240ai-v2/backend/.venv/bin/python -m app.main
directory=/opt/2240ai-v2/backend
environment=PROCESS_ROLE="scheduler"
user=2240ai
autostart=true
autorestart=true
```

---

## 4. 健康检查

```bash
# web 角色
curl -f http://localhost:8000/health/live     # 存活
curl -f http://localhost:8000/health/ready    # 就绪（503 表示不健康）

# worker 角色 — 检查进程存活和任务队列
curl -f http://localhost:8000/health/live

# scheduler 角色 — 检查进程存活和锁持有
curl -f http://localhost:8000/health/live
```

---

## 5. 角色约束

| 约束 | 说明 |
|------|------|
| `PROCESS_ROLE=all` 禁止生产 | `_check_process_role()` 会拒绝 |
| web 不初始化 OCR client | 只在 worker 启动 OCR Gateway |
| scheduler 独占定时任务 | token/staging cleanup 只在 scheduler 运行 |
| 共享 Redis | 三角色共用一个 Redis 实例做任务队列和锁 |
| 独立 DB 连接池 | 每角色用自己的 pool size 配置 |

---

## 6. 回滚方案

如果角色拆分出现问题：

1. 临时回退：设置 `PROCESS_ROLE=all` 并用旧的单进程模式启动
2. 注意：`all` 模式在 `DEPLOYMENT_PROFILE=cloud_api` 下会被配置校验拒绝
3. 如需紧急回退，同时设置 `APP_ENV=development` 或注释掉 `_check_process_role` 校验
4. 恢复后立即改回角色拆分
