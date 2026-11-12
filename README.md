<p align="center">
  <img src="assets/qr_code.jpg" alt="MemoGrad 小程序码" width="160" />
</p>

<h1 align="center">MemoGrad · 408AI 智能刷题系统</h1>

<p align="center">
  面向考研 408 场景的 AI 智能刷题、错题治理与学习运营系统
</p>

<p align="center">
  <a href="https://github.com/ly9098-prog/postgraduate-exam-AI/actions/workflows/ci.yml"><img src="https://github.com/ly9098-prog/postgraduate-exam-AI/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/ly9098-prog/postgraduate-exam-AI/actions/workflows/reliability.yml"><img src="https://github.com/ly9098-prog/postgraduate-exam-AI/actions/workflows/reliability.yml/badge.svg" alt="Reliability Gate" /></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/WeChat-Mini%20Program-07C160?logo=wechat&logoColor=white" alt="WeChat Mini Program" />
  <img src="https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white" alt="Redis" />
</p>

> [!NOTE]
> 本仓库当前为私人部署项目，未配置开源许可证。请勿直接复用业务代码、题库资源或运维信息。

<a id="目录"></a>
## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [核心能力](#核心能力)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [API 概览](#api-概览)
- [数据库与迁移](#数据库与迁移)
- [测试与质量](#测试与质量)
- [生产部署](#生产部署)
- [开发工具链](#开发工具链)
- [常见问题](#常见问题)
- [文档索引](#文档索引)

## 项目简介

MemoGrad 是一套完整的考研刷题平台，覆盖微信小程序端、管理后台和后端平台。项目不仅处理练习与错题记录，还治理题库版本、OCR/AI 导题、学习调度、推荐实验、权限审计和异步任务。

### 设计目标

- **学习闭环完整**：刷题、错题、复习、掌握状态、学习报告和推荐策略形成闭环。
- **题库可治理**：题目版本、公式卡、知识图谱、导入审核和质量门禁共同保障内容质量。
- **生产可用**：Public/Admin API 分层、RBAC、审计日志、任务队列、健康检查和双部署画像。
- **AI 可控**：模型凭据集中配置，具备并发、限流、熔断、Token 预算和健康状态治理。

### 当前状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 微信小程序 | 已上线 | 刷题、错题、复习、公式卡、408 考试、番茄钟、导出 |
| 管理后台 | 已上线 | 题库治理、导入审核、RBAC、AI/OCR/向量配置、审计 |
| 后端 API | 已上线 | Public/Admin 分层、Redis 队列、AI 网关、OCR 流水线 |
| 生产部署 | 已上线 | Docker Compose、Nginx、PostgreSQL、Redis、备份任务 |

## 系统架构

```mermaid
flowchart LR
    MP[微信小程序<br/>MemoGrad] -->|/api/v1| API[FastAPI API]
    ADMIN[Next.js<br/>管理后台] -->|/api/admin/v1| API

    API --> DB[(PostgreSQL / SQLite)]
    API --> REDIS[(Redis)]
    API --> AI[AI Gateway]
    API --> OCR[OCR Pipeline]
    API --> STORE[Local / COS Storage]

    AI --> MODEL[OpenAI-compatible Models]
    OCR --> LOCAL[Local PaddleOCR]
    OCR --> REMOTE[PaddleX / VL HTTP]

    WORKER[Worker] --> REDIS
    WORKER --> DB
    SCHED[Scheduler] --> DB
    SCHED --> REDIS
```

后端按 `PROCESS_ROLE` 拆分运行角色：

| 角色 | 职责 |
| --- | --- |
| `web` | HTTP API、鉴权、业务接口、OCR gateway |
| `worker` | 异步任务、pipeline dispatcher、AI 预热、reaper |
| `scheduler` | 定时任务、清理、提醒、导出处理 |
| `all` | 单进程整合模式，仅建议本地开发 |

## 核心能力

### 微信小程序

- 游客模式：匿名浏览公式与公共科目，随机试做 5/10/20/30 题，本机草稿 24 小时有效。
- 自主登录：入口唯一，支持取消；登录后返回来源页，不强制索取手机号、头像或昵称。
- 练习与错题：答题记录、错题本、质量反馈、短时缓存弱网兜底。
- 学习治理：今日复习、复习调度、掌握状态、自适应学习与学习路径。
- 数据视图：学习报告、趋势、知识掌握分析。
- AI 能力：题目讲解、错因分析、学习建议。
- 考试与工具：408 选择题考试、公式卡、函数图、番茄钟、PDF 导出。

### 管理后台

- 用户与权限：管理员、角色矩阵、RBAC、审计日志。
- 题库运营：题目版本、上下架、选项与图片管理、408 试卷治理。
- 内容导入：OCR/AI 导题、文本导入、CSV 导入、批量图片导入和人工审核。
- 公式与知识：公式卡、分类、版本、函数图、知识图谱和质量报告。
- 运营配置：Dashboard、推荐实验、AI/OCR/向量配置、系统任务队列。

### 后端平台

- Public API 与 Admin API 分层，用户与管理员 JWT 域隔离。
- SQLAlchemy 2.0 Async ORM、Alembic 迁移、PostgreSQL/SQLite 支持。
- Redis 缓存与持久任务队列，web/worker/scheduler 可分离部署。
- OCR 导题流水线：页面处理、识别、纠错、拆题、质量门禁、发布。
- AI 统一网关：凭据集中配置、并发与限流、熔断、Token 预算、健康缓存。
- 可观测性：健康检查、慢查询、审计日志、可选 Sentry 与 pgvector。

## 项目结构

```text
.
├── backend/                      # FastAPI 后端
│   ├── app/api/                  # Public、Admin 与内部 API
│   ├── app/features/             # OCR、pipeline、质量门禁
│   ├── app/services/             # 业务服务、任务、导出、推荐
│   ├── alembic/                  # 数据库迁移
│   └── tests/                    # 按领域分包的测试
├── admin-frontend/               # Next.js 管理后台
│   ├── src/app/                  # App Router 页面
│   ├── src/components/           # UI、表格、题目、公式组件
│   └── src/lib/                  # API client、鉴权、权限
├── miniprogram/                  # 微信小程序
│   ├── pages/                    # 主包页面
│   ├── subpackages/              # study / exam / knowledge / formulas 等
│   └── config.js                 # 本地与生产 API 切换
├── deploy/                       # Docker、Nginx、systemd、部署脚本
├── docs/                         # 项目文档与架构设计
└── sync-to-windows.sh            # WSL → Windows 镜像同步
```

## 快速开始

### 环境要求

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.11+ | 后端与迁移 |
| Node.js | 20+ | 管理后台与小程序测试 |
| PostgreSQL | 15 | 生产数据库 |
| Redis | 7 | 缓存与任务队列 |
| 微信开发者工具 | 最新 | 小程序开发与预览 |

### 后端

1. 创建本地配置：

   ```bash
   cp backend/.env.example backend/.env
   ```

2. 启动开发 API：

   ```bash
   ./run.sh
   ```

   脚本会创建或复用 `backend/.venv`、安装基础依赖，并以 `PROCESS_ROLE=all` 启动。

3. 手动启动：

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. 验证服务：

   ```bash
   curl http://localhost:8000/health
   ```

   非生产环境可访问 `http://localhost:8000/docs` 与 `http://localhost:8000/openapi.json`。

### 管理后台

推荐使用启动脚本：

```bash
./run-admin-linux.sh
```

或手动启动：

```bash
cd admin-frontend
npm ci
npm run dev
```

默认地址为 `http://localhost:3000`。本地开发 API 默认指向：

```env
NEXT_PUBLIC_ADMIN_API_BASE_URL=http://localhost:8000/api/admin/v1
```

开发环境会初始化本地管理员：

| 字段 | 值 |
| --- | --- |
| 用户名 | `admin` |
| 密码 | `admin` |

> 仅限本地开发。生产环境必须禁用或替换默认管理员。

### 微信小程序

1. 安装依赖：

   ```bash
   cd miniprogram
   npm install
   ```

2. 配置环境：编辑 `miniprogram/config.js`，本地调试保持 `LOCAL_DEBUG = true`；真机、体验版或正式版发布前设为 `false`。

3. 使用微信开发者工具打开 `miniprogram/`。

4. 配置自己的小程序账号：

   - 修改 `project.config.json` 中的 `appid`。
   - 在后端配置对应的 `WECHAT_APP_ID` 与 `WECHAT_APP_SECRET`。

> 真机不能通过 `localhost` 访问电脑后端；需要使用局域网地址、测试域名或正式域名。

## 环境变量

### 核心配置

| 变量 | 建议值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | 本地必须显式设置，避免触发生产校验 |
| `APP_SECRET` | 随机强密钥 | JWT/应用密钥 |
| `PROCESS_ROLE` | `web` / `worker` / `scheduler` / `all` | 后端运行角色 |
| `DATABASE_URL` | SQLite 或 PostgreSQL URL | 数据库连接 |
| `REDIS_URL` | Redis URL | 生产任务与缓存能力依赖 Redis |
| `DEPLOYMENT_PROFILE` | `local_import` / `cloud_api` | 本地重导入或云端 API 画像 |
| `ALLOWED_HOSTS` | localhost / 127.0.0.1 | Host 白名单 |
| `CORS_ORIGINS` | localhost / 127.0.0.1:3000 | 管理后台 CORS 白名单 |

### AI 与 OCR

| 变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `AI_TIMEOUT` | `150` | AI 调用超时，单位秒 |
| `AI_DAILY_TOKEN_LIMIT` | `50000` | 日 Token 预算 |
| `AI_MAX_CONCURRENCY` | `3` | 统一 AI 并发上限 |
| `AI_USER_RPM_LIMIT` | `12` | 用户级 RPM |
| `AI_CONFIG_ENCRYPT_KEY` | 空 | 后台 AI 凭据加密密钥 |
| `OCR_ENABLED` | `false` | OCR 总开关 |
| `OCR_EXECUTION_BACKEND` | `paddlex_http` | `disabled` / `local_process` / `paddlex_http` |
| `OCR_REMOTE_URL` | 空 | 远程 OCR endpoint；本地用 WSL 后端调用 Windows PaddleX GPU 服务 |
| `OCR_REMOTE_TOKEN` | 空 | 远程 OCR 鉴权 Token；生产必须使用 HTTPS |

AI 模型凭据应通过管理后台配置并持久化；OCR 与数据库连接池的完整变量以 `backend/.env.example` 和 `backend/app/core/config.py` 为准。

## API 概览

### Public API

前缀：`/api/v1`

| 领域 | 示例 |
| --- | --- |
| 认证 | `/auth/login`, `/auth/refresh` |
| 用户 | `/users/me` |
| 题库 | `/questions` |
| 练习 | `/practice/*` |
| 游客体验 | `/guest/practice/*` |
| 错题与复习 | `/wrong-questions/*`, `/review/*` |
| 学习统计 | `/stats/*`, `/study-report/*` |
| AI 与 RAG | `/ai/*`, `/rag/*` |
| 知识与自适应 | `/knowledge-*`, `/adaptive-learning/*` |
| 公式与考试 | `/formulas/*`, `/exams/*` |
| 番茄钟 | `/pomodoro/*` |
| 导入导出 | `/import/*`, `/exports/*` |

### Admin API

前缀：`/api/admin/v1`

覆盖认证、Dashboard、App 用户、管理员、RBAC、科目、题库、导入审核、公式卡、知识图谱、推荐、AI 设置、向量配置、水印、审计日志、任务队列和系统健康。

> 运行时 OpenAPI 是路由协议的 source of truth，优先查看 `/docs` 与 `/openapi.json`。

## 数据库与迁移

### 本地开发

SQLite 配置：

```env
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db
```

`local_import` 画像下会执行本地数据库初始化与兼容修复逻辑。

### 生产环境

推荐 PostgreSQL：

```env
APP_ENV=production
DEPLOYMENT_PROFILE=cloud_api
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgraduate
REDIS_URL=redis://HOST:6379/0
```

生产数据库必须通过 Alembic 管理：

```bash
cd backend
alembic upgrade head
alembic current
alembic heads
```

### 核心数据域

| 领域 | 主要模型 |
| --- | --- |
| 用户认证 | `users`, `refresh_tokens` |
| 题库 | `questions`, `question_versions`, `subjects`, `knowledge_points` |
| 练习错题 | `practice_records`, `practice_sessions`, `wrong_questions` |
| 复习 | `review_schedules`, `review_records` |
| 番茄钟 | `pomodoro_sessions`, `pomodoro_pause_intervals` |
| 管理后台 | `admin_users`, `roles`, `permissions`, `audit_logs` |
| AI | `admin_ai_model_configs`, `admin_ai_configs`, usage/feedback logs |
| 导题 | import pipeline / batch job / OCR job 相关表 |
| 公式卡 | formula card / version / tag / graph 相关表 |
| 408 考试 | `exam_papers`, `exam_attempts`, `exam_answers` |
| 异步任务 | `task_outbox` 等基础设施表 |

## 测试与质量

### GitHub Actions

| Workflow | 覆盖 |
| --- | --- |
| **CI** | Python 语法、Ruff、MyPy、Bandit、pip-audit、静态架构与非 GPU 回归、Docker 构建、迁移循环 |
| **Reliability Gate** | PostgreSQL + pgvector、Redis、Alembic、可靠性测试、OpenAPI contract、Admin 构建 |
| **Publish Container Images** | 发布容器镜像 |
| **Deploy** | 手动触发的部署流程 |

### 后端

```bash
cd backend
python -m compileall -q app
ruff check app/ --ignore I001,F401,N818
ruff check path/to/changed_file.py
```

运行局部测试：

```bash
cd backend
.venv/bin/python -m pytest tests/quality_gate -q
.venv/bin/python -m pytest tests/ocr_pipeline/test_ocr_request.py -q
```

> CI 使用固定测试清单。全量本地 pytest 可能包含需要 PostgreSQL、Redis 或外部 OCR 的用例，不应把本地失败直接当作代码缺陷。

### 管理后台

```bash
cd admin-frontend
npm run check
```

`check` 依次执行 typecheck、lint、test 和 build。

### 小程序

小程序没有统一测试别名，按改动运行独立 Node 测试：

```bash
cd miniprogram
node tests/test-render-invariant.js
node tests/test-config-resolution.js
node tests/render_regression/run.js
```

修改页面或渲染逻辑后，仍需使用微信开发者工具做编译和真机/模拟器验证。

## 生产部署

### 架构

生产使用 `deploy/docker-compose.prod.yml`：

| 服务 | 说明 |
| --- | --- |
| `app` | FastAPI + Gunicorn Web 进程 |
| `worker` | Redis 任务消费者；生产 OCR 不在此进程执行 |
| `scheduler` | 定时任务、导出与清理 |
| `nginx` | HTTPS 反向代理 |
| `postgres` | PostgreSQL 15 / pgvector |
| `redis` | Redis 7 任务队列与缓存 |
| `admin` | Next.js 管理前端 |
| `backup` | PostgreSQL 备份任务 |

### 检查清单

- `APP_ENV=production`
- `DEPLOYMENT_PROFILE=cloud_api`
- 替换默认 `APP_SECRET`
- 配置 PostgreSQL 与 Redis
- 配置 `ALLOWED_HOSTS` 与 `CORS_ORIGINS`
- 禁用或修改开发默认管理员
- 启用 HTTPS
- 执行 Alembic migration
- 检查 `/health`、`/health/ready`、`/health/live`
- 确认 worker 与 scheduler 已启动

### 部署入口

`Deploy` workflow 手动触发：先运行后端测试，仅 `main` 分支进入部署作业，再通过 SSH 在服务器执行：

```bash
bash deploy/scripts/deploy.sh update
```

`deploy.sh update` 不执行数据库迁移。生产服务器信息、完整备份、同步、worker 重建、迁移和回滚命令保留在本地 `docs/project/DEPLOY_PLAN.md`。

### 禁止操作

- 不要在生产日常操作中执行 `docker compose down`。
- 不要使用 `docker compose build --no-cache`，会破坏 layer cache。
- 不要从本地覆盖服务器 `backend/.env`、`cert/` 或密钥。

### 关键文件

| 路径 | 说明 |
| --- | --- |
| `deploy/docker-compose.prod.yml` | 生产 Compose 入口 |
| `deploy/scripts/deploy.sh` | 生产部署脚本 |
| `deploy/scripts/redis_backup.sh` | Redis RDB 备份 |
| `deploy/scripts/redis_restore.sh` | Redis AOF-safe 恢复 |
| `deploy/nginx/nginx.conf.template` | Nginx 配置模板 |
| `scripts/postgres_backup.py` | PostgreSQL 备份脚本 |
| `deploy/systemd/postgres-backup.timer` | 定时备份 |

## 开发工具链

### WSL → Windows 同步

`sync-to-windows.sh` 将 WSL 项目镜像到 Windows 文件系统，用于 Windows IDE 或 GUI 工具。

预览：

```bash
./sync-to-windows.sh -n
```

同步：

```bash
./sync-to-windows.sh
```

脚本不同步 `.git`，使用 `--delete-after` 与 `--partial`，并额外排除虚拟环境、测试、本地产物和 SSL。默认目标目录可在脚本中修改。

### 提交规范

提交信息遵循 Conventional Commits，允许的类型包括：

`feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`revert`

提交前至少检查：

```bash
git status
git diff --check
```

不要提交 `.env`、数据库文件、备份、日志、缓存、构建产物、证书或任何密钥。

## 常见问题

### 后端启动报生产配置错误

`APP_ENV` 代码默认值是 `production`。本地开发应显式设置：

```env
APP_ENV=development
```

### 小程序无法访问本地 API

微信开发者工具可以使用 `http://localhost:8000/api/v1`。真机不能通过 `localhost` 访问电脑，需要使用手机可访问的局域网地址、HTTPS 测试域名或正式域名，并配置小程序合法域名。

### 管理后台 401 / 403

依次检查管理员登录状态、access token 过期、refresh 结果、当前角色权限和 `NEXT_PUBLIC_ADMIN_API_BASE_URL`。

### 游客请求 401 / 403 / 429

- 携带无效凭据会直接 `401`，不会降级为匿名。
- 游客试做接口按客户端 IP 限流 120 次/分钟，超限返回 `429`。
- 游客凭据只能调用 `/guest/practice/*`，不能用于正式交卷。

### OCR 不工作

检查：

```env
OCR_ENABLED=true
OCR_EXECUTION_BACKEND=...
```

远程 OCR 还需要确认 `OCR_REMOTE_URL`、网络连通性、Token、HTTP/HTTPS 策略和部署画像限制。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/INDEX.md`](docs/INDEX.md) | 文档目录 |
| [`docs/PROJECT_RULES.md`](docs/PROJECT_RULES.md) | 项目规则 |
| [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md) | 系统架构 |
| [`docs/backend/API_SPEC.md`](docs/backend/API_SPEC.md) | 后端 API 说明 |
| [`docs/admin/ADMIN_API_SPEC.md`](docs/admin/ADMIN_API_SPEC.md) | Admin API 说明 |
| [`docs/ai/AI_PIPELINE.md`](docs/ai/AI_PIPELINE.md) | AI 流水线 |
| [`docs/ocr/OPERATIONS.md`](docs/ocr/OPERATIONS.md) | OCR 运维 |
| [`docs/frontend/ADMIN_UI_RULES.md`](docs/frontend/ADMIN_UI_RULES.md) | Admin UI 规则 |
| [`docs/development/git-workflow.md`](docs/development/git-workflow.md) | Git 工作流 |

<div align="center">
  <sub>MemoGrad · 为考研 408 学习场景构建的智能刷题与题库治理系统</sub>
</div>
