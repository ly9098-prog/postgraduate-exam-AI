# 部署配置审查报告

> 审查日期：2026-07-15
> 审查范围：docker-compose.prod.yml、nginx.conf、Dockerfile、deploy.sh、docker-compose.test.yml、docker-compose.dev.yml、DEPLOY_PLAN.md

---

## 1. Streaming Handler 兼容性

**结论：✅ 完全向后兼容**

- 无新增环境变量要求
- `stream_to_temp()` 使用系统临时目录，不依赖特定挂载点
- `file_path` 在 worker 内读取，与原有 Docker 卷挂载无冲突
- 无需修改 nginx/反向代理配置

## 2. nginx.conf 审查

### upload 大小限制：✅
- `client_max_body_size 20M`
- OCR profile 中 `max_upload_bytes = 5 MB`，上限冗余 4 倍

### SSE buffering：✅
- SSE 端点：`/api/admin/v1/imports/batch-image/{job_id}/stream`
- `/api/` location block 默认 `proxy_buffering on`
- 但 SSE endpoint 已在响应头设置 `X-Accel-Buffering: no`，nginx 会尊重此头关闭缓冲
- 心跳机制（每 1.5s 无事件时发送 `: heartbeat`）可防止 proxy 超时断开

### 超时配置：✅
- `proxy_read_timeout 60s` — 适用于所有 API 请求
- 耗时导入（OCR PDF）均为后台任务，不阻塞 HTTP 请求
- 导入状态查询是轻量请求，60s 足够

### SSL/TLS：✅
- TLSv1.2 + TLSv1.3
- 仅 ECDHE 高等加密套件
- HSTS（`max-age=63072000` = 2 年）
- XSS/XFO/Content-Type 安全头完整

## 3. Gunicorn Worker 数与内存预算

### 限制
- 服务器：2 核 / 1.8 GB RAM
- Docker compose 硬限制（`mem_limit`）：app=512m, postgres=512m, redis=128m, nginx=64m, admin=256m
- 合计保留：1,472 MB（剩余 ~328 MB 给 OS）

### Worker 配置
- `GUNICORN_WORKERS=2`（服务器 `.env` 模板中设为 1，compose 默认 2）
- 每个 PaddleOCR worker 估算：200–500 MB

### 风险分析：⚠️ 中等

| 场景 | 内存估算 | 结论 |
|------|---------|------|
| 2 workers + PaddleOCR | ~400-1000 MB | 512m limit 紧张 |
| 1 worker + PaddleOCR (生产 .env 配置) | ~200-500 MB | 512m limit 安全 |
| 无 OCR 请求时 | ~200-300 MB | 安全 |

**建议**：生产环境保持 `GUNICORN_WORKERS=1`（已有配置），如有性能需要可升至 2 但需配合提升 `mem_limit`。Dockerfile 中 `CMD` 默认 `GUNICORN_WORKERS:-2` 与生产 `.env` 的 `GUNICORN_WORKERS=1` 不一致，但 `.env` 会覆盖，无实际影响。

## 4. Dockerfile 审查

### 多阶段构建：✅
- Builder 阶段安装 Python 依赖和 PaddleOCR
- Runtime 阶段最小化 base（slim）
- 预下载 PaddleOCR 模型到镜像层

### 依赖镜像源：⚠️
- Dockerfile 使用阿里云源（`mirrors.aliyun.com`）
- DEPLOY_PLAN.md 2.6 节描述为清华源（`pypi.tuna.tsinghua.edu.cn`）
- **两者不一致**，但仅为文档与实际配置差异，无功能影响

### 安全：✅
- 非 root 用户运行
- `PYTHONUNBUFFERED=1` 确保日志即时输出

## 5. docker-compose.prod.yml 结构审查

### 网络绑定：✅
- app/admin 均绑定到 `127.0.0.1`（仅 nginx 可访问），nginx 通过 Docker 内部 DNS（`server app:8000`）转发
- 所有服务端口均不对外暴露

### 依赖顺序：✅
- app 依赖 postgres + redis 健康检查
- nginx 依赖 app
- backup 有 `profiles: ["manual"]`，不随 compose up 启动

### 健康检查：✅
- postgres: `pg_isready`，5s 间隔
- redis: `redis-cli ping`，10s 间隔
- app: 容器内 `GET /health/live`，30s 间隔
- backup: 无（按需运行）

### 卷挂载：✅
- pgdata_prod、redisdata_prod、nginx_logs、backup_data 均已独立命名
- nginx ssl 证书通过 bind mount 映射

## 6. 集成测试 docker-compose 兼容性

**结论：✅ 完全兼容**
- Postgres 端口 5433（不冲突生产 5432）
- Redis 端口 6380（不冲突生产 6379）
- 使用 tmpfs，无持久数据
- 无 app 服务，测试从宿主机执行

## 7. 开发 docker-compose 审查

**结论：✅ 配置合理**
- 卷挂载 `../backend:/app` 支持热重载
- 使用 `uvicorn --reload`
- 无 nginx（开发直连 app:8000）
- 未设内存限制（合理，开发环境通常资源充足）

## 8. 遗留 compose 文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `deploy/docker-compose.yml` | 历史，已弃用 | 早期生产配置，GUNICORN_WORKERS=4 不适合当前 1.8GB 服务器 |
| `docker-compose.yml` | 历史，已弃用 | 仅含 db+redis，无 app 服务 |

两个文件均未被 deploy.sh 引用，不会造成意外启动。建议清理以避免混淆。

---

## 审查总表

| 项目 | 状态 | 说明 |
|------|------|------|
| Streaming handler 兼容 | ✅ | 无需配置变更 |
| nginx upload 大小限制 | ✅ | 20M > OCR profile 5M |
| SSE buffering | ✅ | X-Accel-Buffering: no 有效 |
| SSL/TLS | ✅ | 配置合规 |
| Gunicorn workers | ⚠️ | 2 workers 超 512m limit；生产已用 1 worker 无问题 |
| Dockerfile 镜像源文档 | ⚠️ | 实际用阿里云，文档写清华源 |
| 依赖顺序 | ✅ | 正确 |
| 健康检查 | ✅ | 所有服务均已配置 |
| 集成测试兼容 | ✅ | 端口不冲突 |
| 开发配置 | ✅ | 合理 |
| 遗留文件 | ⚠️ | 建议清理 |
