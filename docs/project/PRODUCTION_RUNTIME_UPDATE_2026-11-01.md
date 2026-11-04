# 生产运行版本更新（2026-11-01）

用户明确要求将已同步的修复更新到实际运行版本。已完成 app、worker、scheduler、Admin 四个镜像的构建与容器替换，2026-11-01 15:41:42（Asia/Shanghai）完成运行检查。nginx 已通过配置检查并 reload；PostgreSQL、Redis、nginx 容器没有重建或重启。没有执行数据库迁移。

此次更新使 Admin 登录/单题审核审计、上传阶段取消及迟响应归属修复进入实际运行镜像。四个源文件与此前 ENV-02 验收记录的 SHA256 一致；没有在本批修改业务代码。限定生产验证不代表全部 ENV-01..06 验收完成。

## 当前运行版本

| 服务 | 运行镜像 ID |
| --- | --- |
| app | `sha256:4d46548e9c462e6392863cda4ec9bb4fb036ee6e3d627cc5345e8d581909ab28` |
| worker | `sha256:1e8309de17ac71af71f0eb401714d3ab7e93204852f34334f2b5768b7cba3315` |
| scheduler | `sha256:4c26fc8b701c238e4498b0e59fbbc69240da7e3d755f62e402c53dd3eda85e69` |
| Admin | `sha256:777a04714d35ad3161e4b0c6a43f88eb62552f081dd920c73e4e21d5732b2784` |

后端镜像创建于 15:33:49，Admin 镜像创建于 15:34:42；新容器于 15:40:08 启动，均为北京时间。Admin BUILD_ID 从 `ttOTOpZ03z0sWeucUoSfQ` 更新为 `Ioxstl7ZkFENgG6g-saix`。镜像 ID 与运行容器逐项核对，不使用宿主机源码同步状态代替运行版本证明。

## 实施范围

1. 对照 `DEPLOY_PLAN.md` 和实际 Compose 配置，确认四服务配置环境与当前容器一致，生产画像仍为 `production/cloud_api`；构建设置 `INSTALL_OCR=false`。
2. 校验服务器 Dockerfile、依赖锁、Compose、部署脚本及 Admin 包清单与本地一致；确认 Docker 上下文排除环境文件、凭据和运行数据。
3. 新建当前 PostgreSQL 完整备份及 Redis RDB；保留四个旧运行镜像的 rollback 标签。
4. 先缓存构建 app/worker/scheduler，再构建 Admin。全部构建及镜像内检查成功后，使用 `up -d --no-deps --no-build --pull never --timeout 90 app worker scheduler admin` 替换四服务，不操作其他服务依赖。
5. 新 app 内部 readiness 和 Admin 登录页就绪后，执行 `nginx -t`、`nginx -s reload`，复查公网路径、实际运行源码与前端资源。

Compose 项目显式指定为 `deploy`，环境文件沿用服务器 `backend/.env`。没有执行 git pull、迁移、清库、镜像/缓存清理、volume 删除或环境配置覆盖。

## 验证与边界

- 本地后端 compileall 和两个变更 Python 文件的严格 Ruff 通过；此前 API/服务/浏览器等验收通过证据按四源文件相同 SHA256 复用，没有将旧测试记为本轮重跑。
- 新后端镜像在无网络、无生产卷的临时容器中 compileall 通过；app/worker/scheduler 实际运行文件的 SHA256 均匹配批准版本。
- 新 Admin BUILD_ID 与运行容器相同；公网可读取包含“取消上传”的新构建 JS 资源，HTTP 200。未执行生产账号登录或浏览器完整上传验收。
- app Docker health 为 healthy，四服务进程运行且重启次数均 0；从本轮启动时间开始读取的日志中 ERROR/CRITICAL/Traceback/ModuleNotFoundError 匹配行均 0。该检查不代表长期监控或真实任务消费验收。
- app 内部 `/health/ready` 200；公网 `/health/live`、`/health`、首页、`/login` 均 200；公网 `/health/ready` 仍为 nginx 保护的 403。
- 生产 81 张表的名称/schema/OID 与替换前一致，迁移版本保持 `v19_pomodoro_subject_allocations`。与此前已验证恢复快照相比，830 个 schema 对象段逐项一致，17 张已恢复表及其约束未被本批改变。
- PostgreSQL、Redis、nginx 的容器 ID 和启动时间不变；服务器 `.env`、Compose 和 nginx 配置文件 SHA256 不变。

已观察到现有 named volume 的 Compose 归属警告及 nginx `listen ... http2` 弃用警告，配置检查和请求正常；未为这些警告扩大生产修改范围。

## 备份、证据与回滚

服务器目录：

```text
/data/backups/runtime_deploy_20261101T073153Z_ZKOxFn/
```

目录 700；初始备份文件 600。PostgreSQL 归档 23,185,646 字节，TOC、完整解码及 SHA256 通过；Redis RDB 8,810 字节，文件头和 `redis-check-rdb` 通过。两份为各自时点备份，不宣称是跨存储原子恢复点。

| 文件 | SHA256 |
| --- | --- |
| postgraduate.dump | `9dea82fb9e1a0676aecef84f8d901f2b73b84cdd34b3788e13dd1cc424d15196` |
| redis.rdb | `a3cf0a71d1189b50588ecad51256a7e4350a259f197e03d79df5f188dda0ade8` |

`containers-before.json`、`images-built.json`、`backend-build.log`、`admin-build.log`、镜像预检结果、`runtime-deployment-verification.json` 及 schema 快照保留在服务器。旧镜像标签为 `deploy-<service>:rollback-20261101T073153Z`，未清理。

如需按具体授权回滚运行镜像，可沿用生产 Compose 和原环境，增加备份目录中的 `rollback-images.json` 覆盖文件，使用 `up --no-deps --no-build --pull never` 替换上述四服务，再 reload nginx 并重新验证。该方式不恢复或覆盖数据库。本轮未触发自动回滚，也未进行生产全量 PG/Redis 恢复。

脱敏机器结果见 [部署结果](../architecture/refactor-results/production-runtime-update-2026-11-01.json)。本轮部署不改变既有最终环境门禁：ENV-01 PARTIAL、ENV-02/03/05 PASS-ISOLATED、ENV-04/06 BLOCKED。

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
