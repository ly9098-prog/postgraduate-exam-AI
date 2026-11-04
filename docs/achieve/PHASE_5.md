# 阶段 6：生产部署 + 正式上线 ✅

**目标**：让系统具备可部署、可维护、可恢复、可监控、可长期稳定运行的能力。

**核心原则**：不新增功能，只做生产化改造。

### 交付件

| 项目 | 说明 |
|------|------|
| `deploy/Dockerfile.prod` | 多阶段生产构建（python:3.11-slim） |
| `deploy/nginx.conf` | Nginx 反向代理 + HTTPS + 限流 + 安全头 |
| `deploy/deploy.sh` | 首次部署 / 日常更新脚本 |
| `deploy/backup.sh` | 每日 pg_dump 备份（保留 7 天） |
| `deploy/checklist.md` | 上线前检查清单 |
| `docker-compose.prod.yml` | 生产环境编排（PostgreSQL + app + Nginx） |

### 部署架构

```
用户 → HTTPS → Nginx → FastAPI (Gunicorn + Uvicorn)
                          ├── PostgreSQL
                          └── Redis（可选）
```

### 安全措施

- `.env` 禁止提交到 git | JWT 密钥独立高强度 | API 限流 | CORS 仅允许小程序域名
- 数据库最小权限用户 | 用户数据不落日志 | 备份加密

### 监控

- `/health` 端点 | 结构化 JSON 日志 | 慢查询日志 | AI 调用日志
- 异常自动捕获 | 磁盘 / CPU / 内存监控

### 验收

- [x] 云服务器部署（2C2G, Alibaba Cloud Linux）
- [x] Docker 镜像构建 + 服务编排
- [x] HTTPS 证书签发（Let's Encrypt）+ 自动续期
- [x] Nginx 反向代理 + gzip + 安全头
- [x] API 全链路验证通过
- [ ] 微信小程序正式环境切换（需提交审核）— **当前唯一阻塞项**

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
