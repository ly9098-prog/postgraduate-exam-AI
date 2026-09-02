# MemoGrad / 22408AI 智能刷题系统

MemoGrad 是一个面向考研学习场景的智能刷题与题库治理系统，由 **FastAPI 后端**、**Next.js 管理后台** 和 **微信小程序** 三部分组成。

系统覆盖题库练习、错题与复习、学习报告、番茄钟、公式卡、AI 讲解、OCR/AI 导题、知识图谱、自适应学习、后台审核、RBAC、审计日志、AI 模型配置、向量检索以及异步任务治理等能力。

> 本 README 面向「首次运行项目、日常开发、CI 排错和部署维护」。API 的完整字段与协议应以运行时 OpenAPI 和 `docs/` 中的专项文档为准。

> 当前实现快照（2026-09-02）：后端已完成 Public/Admin 路由分层、Redis 任务队列与运维诊断；Admin 使用 Next.js 16.2 + React 19.2；生产部署必须使用 `APP_ENV=production` + `DEPLOYMENT_PROFILE=cloud_api`；用户与 Admin JWT 签名域隔离。近期前端变更包括编程题专用渲染和小程序题目图片预加载。

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 核心能力](#2-核心能力)
- [3. 项目结构](#3-项目结构)
- [4. 技术栈](#4-技术栈)
- [5. 快速开始](#5-快速开始)
- [6. 环境与部署画像](#6-环境与部署画像)
- [7. API 与开发文档](#7-api-与开发文档)
- [8. 数据库与迁移](#8-数据库与迁移)
- [9. 测试、代码质量与 CI](#9-测试代码质量与-ci)
- [10. 生产部署](#10-生产部署)
- [11. WSL → Windows 同步](#11-wsl--windows-同步)
- [12. 常见问题](#12-常见问题)

---

## 1. 系统架构

```mermaid
flowchart LR
    MP[微信小程序\nMemoGrad] -->|/api/v1| API[FastAPI API]
    ADMIN[Next.js 管理后台] -->|/api/admin/v1| API

    API --> DB[(PostgreSQL / SQLite)]
    API --> REDIS[(Redis)]
    API --> AI[AI Model Gateway]
    API --> OCR[OCR Pipeline]
    API --> STORE[Local / COS Storage]

    OCR --> LOCAL_OCR[Local PaddleOCR]
    OCR --> REMOTE_OCR[PaddleX / PaddleOCR-VL HTTP]
    AI --> MODEL[OpenAI-compatible / DeepSeek models]

    WORKER[Worker] --> REDIS
    WORKER --> DB
    SCHED[Scheduler] --> DB
    SCHED --> REDIS
```

### 运行角色

后端支持按进程角色拆分：

| 角色 | 主要职责 |
|---|---|
| `web` | HTTP API、鉴权、业务接口、OCR gateway |
| `worker` | 异步任务、pipeline dispatcher、reaper、AI 预热等 |
| `scheduler` | 定时任务、清理、提醒、导出任务等 |
| `all` | 单进程整合模式，仅建议本地开发/调试 |

生产环境建议使用 `web / worker / scheduler` 分离部署，而不是使用 `all`。

---

## 2. 核心能力

### 微信小程序

- 微信登录、token / refresh token 自动续签
- 刷题、随机练习、答题记录与学习统计
- 错题本、错题详情、质量反馈
- 今日复习、复习调度、掌握状态管理
- 自适应学习、弱知识点、学习路径与推荐
- 学习报告、趋势、知识掌握分析
- AI 题目讲解、错因分析、学习建议
- 番茄钟、暂停/恢复、专注统计与历史记录
- 公式卡浏览、收藏、分类与公式渲染
- 错题/学习数据导出
- KaTeX / mp-html 富文本与数学公式渲染

### 管理后台

- 管理员登录、刷新、退出与密码管理
- Dashboard 与运营数据概览
- 小程序用户管理、封禁/解封、管理员绑定
- 管理员账号、角色与权限矩阵（RBAC）
- 题库查询、编辑、上下架、版本与图片/选项管理
- OCR / AI 导题、文本导入、批量图片导入与审核发布
- 公式卡、分类、版本、审核状态与图形资源管理
- 知识图谱、知识质量报告
- 推荐策略、实验、指标与报表
- AI 模型、OCR、向量检索配置与连接测试
- 审计日志、系统任务队列与健康检查

### 后端平台能力

- Public API 与 Admin API 分层
- JWT 用户鉴权与管理员 RBAC
- SQLAlchemy 2.0 Async ORM + Alembic
- OCR 导题流水线：页面处理、识别、纠错、拆题、质量门禁、发布
- AI 统一调用入口、并发/限流/熔断/Token 预算
- Redis 缓存与持久任务队列
- 自适应学习、知识状态、推荐与实验指标
- pgvector 向量检索（可选）
- 审计日志、健康检查、慢查询与 Sentry（可选）
- 本地 / 云端双部署画像

---

## 3. 项目结构

```text
.
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── main.py              # 应用入口 / lifespan / health
│   │   ├── api/
│   │   │   ├── v1/              # Public 与 Admin route modules
│   │   │   ├── admin/           # Admin router 聚合入口
│   │   │   └── internal/        # 内部 worker API
│   │   ├── ai/                  # AI Prompt、上下文与模型调用辅助
│   │   ├── core/                # 配置、数据库、安全、部署画像、日志
│   │   ├── features/            # OCR、pipeline、质量门禁等
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── schemas/             # Pydantic schema
│   │   ├── services/            # 业务服务、任务、导出、推荐等
│   │   └── utils/               # 通用工具
│   ├── alembic/                 # 数据库迁移
│   ├── requirements.txt
│   ├── requirements-ocr.txt     # OCR 可选依赖
│   ├── Dockerfile
│   └── gunicorn.conf.py
│
├── admin-frontend/              # Next.js 管理后台
│   ├── src/app/                 # App Router 页面
│   ├── src/components/          # UI、表格、题目、公式、审计组件
│   └── src/lib/                 # API client、鉴权、权限、工具
│
├── miniprogram/                 # 微信小程序
│   ├── pages/                   # 登录、协议、首页、Dashboard、番茄钟
│   ├── subpackages/
│   │   ├── study/               # 刷题、复习、错题
│   │   ├── productivity/        # 番茄钟统计
│   │   ├── formulas/            # 公式卡
│   │   ├── export/              # 导出
│   │   └── animation/           # Lottie 动画
│   ├── components/
│   ├── utils/
│   ├── config.js                # API 环境切换
│   ├── app.js / app.json
│   └── project.config.json
│
├── deploy/                      # Docker / Nginx / systemd / 部署脚本
├── docs/                        # 架构、API、前端、AI、项目文档
├── prompts/                     # 开发任务与 Prompt
├── scripts/                     # 工具脚本
├── tests/                       # 项目级测试
├── sync-to-windows.sh           # WSL → Windows 镜像同步
└── README.md
```

> 若某些目录在分支中发生调整，以仓库实际结构为准；README 不应替代 `docs/` 中的专项设计文档。

---

## 4. 技术栈

### 后端

- Python 3.11+
- FastAPI
- Pydantic / pydantic-settings
- SQLAlchemy 2.0 Async ORM
- Alembic
- PostgreSQL 15 / SQLite
- Redis 7
- JWT（用户与管理员 audience 分离）
- Gunicorn + Uvicorn worker
- APScheduler / 异步任务体系
- PyMuPDF / Pillow / PaddleOCR（按部署画像启用）
- PaddleX / PaddleOCR-VL HTTP OCR（本地进程或远程 HTTP）
- OpenAI-compatible AI Gateway / DeepSeek 等模型配置
- pgvector（可选）
- Sentry（可选）

### 管理后台

- Next.js + React 19
- TypeScript
- TanStack Query / TanStack Table
- Zustand
- ECharts / Recharts
- Tailwind CSS
- Lucide React
- KaTeX

### 微信小程序

- 原生微信小程序
- `wx.login`
- Lottie Mini Program
- KaTeX / mp-html
- 主包 + 分包加载

---

## 5. 快速开始

### 5.1 环境要求

建议准备：

- Python 3.11+
- Node.js 20+
- npm
- 微信开发者工具
- Git
- 可选：Docker / Docker Compose
- 可选：PostgreSQL 15、Redis 7

### 5.2 启动后端

#### 推荐：使用项目启动脚本

先完成一次本地配置（脚本不会替你生成后端 `.env`）：

```bash
cp backend/.env.example backend/.env
```

Linux / WSL 在项目根目录执行：

```bash
./run.sh
```

`run.sh` 会检查 Python、创建或复用 `backend/.venv`、安装 `backend/requirements.txt`，然后启动 FastAPI。默认 `PROCESS_ROLE=all`，适合本地同时运行 API 和本地后台任务；只启动 Web API 时执行：

```bash
PROCESS_ROLE=web ./run.sh
```

如果依赖已经安装，也可以直接执行后端目录内的轻量脚本：

```bash
cd backend
./run.sh
```

脚本检测到缺少 OCR 依赖时可能会安装 `requirements-ocr.txt`，首次执行耗时较长；不需要本地 OCR 时可先确认现有环境或改用下方手动安装方式。Windows 可从项目根目录运行 `run.bat`，它会进入 `backend/` 并启动开发 API。

脚本启动后可在另一个终端启动管理后台：

```bash
./run-admin-linux.sh
```

该脚本会检查 Node.js/npm，必要时在 `admin-frontend/` 执行 `npm ci`，并启动 Next.js 开发服务器。Windows 管理后台脚本当前未提供，请使用 [手动方式](#53-启动管理后台)。

#### 1）创建虚拟环境

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### 2）安装依赖

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如需本地 OCR：

```bash
pip install -r requirements-ocr.txt
```

#### 3）创建本地配置

```bash
cp .env.example .env
```

本地开发至少确认以下配置：

```env
APP_ENV=development
APP_SECRET=replace-with-a-local-secret
DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db
PROCESS_ROLE=web

WECHAT_APP_ID=
WECHAT_APP_SECRET=
```

> `APP_ENV` 的代码默认值是 `production`。本地开发建议显式设置为 `development`，避免误触发生产配置校验。

#### 4）启动 API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

检查：

```bash
curl http://localhost:8000/health
```

非生产环境还可访问：

```text
http://localhost:8000/docs
http://localhost:8000/redoc
http://localhost:8000/openapi.json
```

#### 5）开发管理员

当 `APP_ENV` 为 `development`、`local` 或 `test` 时，后端会初始化开发用超级管理员：

```text
用户名：admin
密码：admin
```

**该账号仅用于本地开发。生产环境会对默认 `admin/admin` 等不安全配置执行校验，不应继续使用。**

### 5.3 启动管理后台

#### 推荐：使用项目启动脚本

后端已启动时，在项目根目录另开一个 Linux / WSL 终端执行：

```bash
./run-admin-linux.sh
```

默认地址为 `http://localhost:3000`。脚本会在 `.env.local` 不存在且 `.env.example` 存在时创建本地前端配置，并在依赖目录不存在时执行 `npm ci`。

#### 手动启动

```bash
cd admin-frontend
npm ci
npm run dev
```

默认开发地址：

```text
http://localhost:3000
```

常用环境变量：

```env
NEXT_PUBLIC_ADMIN_API_BASE_URL=http://localhost:8000/api/admin/v1
```

管理后台使用 App Router，主要页面包括 Dashboard、用户、管理员、角色、题库、导入审核、公式卡、知识图谱、推荐策略、AI 设置、审计日志和系统任务等。

### 5.4 启动微信小程序

#### 1）安装 npm 依赖

```bash
cd miniprogram
npm install
```

#### 2）配置 API 环境

编辑 `miniprogram/config.js`：

```js
const LOCAL_DEBUG = true
```

当前配置含义：

| 模式 | API |
|---|---|
| 本地开发 | `http://localhost:8000/api/v1` |
| 体验版 / 正式版 | `https://xzshub.top/api/v1` |

发布或真机测试前应将：

```js
const LOCAL_DEBUG = false
```

本地 `localhost` 模式主要用于微信开发者工具；真机上的 `localhost` 指向手机自身，不能直接访问电脑上的后端。

#### 3）微信开发者工具

使用微信开发者工具打开 `miniprogram/`。

当前项目配置：

```text
projectname: MemoGrad
appid: wx013724bc2f592940
libVersion: 3.6.6
```

如使用自己的小程序账号，请同步修改 AppID，并在后端配置对应的：

```env
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
```

---

## 6. 环境与部署画像

### 6.1 核心配置

| 变量 | 代码默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `production` | 运行环境；本地建议显式设为 `development` |
| `APP_SECRET` | `change-me-in-production` | JWT/应用密钥，生产必须替换 |
| `USER_JWT_SECRET` | 空（由 `APP_SECRET` 派生） | 可选的用户 JWT 独立签名密钥，生产建议显式配置 |
| `ADMIN_JWT_SECRET` | 空（由 `APP_SECRET` 派生） | 可选的 Admin JWT 独立签名密钥，必须与用户密钥不同 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./postgraduate.db` | 数据库连接 |
| `PROCESS_ROLE` | `web` | `web` / `worker` / `scheduler` / `all` |
| `LOCAL_ASYNC_RUNTIME_ENABLED` | `false` | 是否在本地 web 进程显式启用完整异步 runtime |
| `DEPLOYMENT_PROFILE` | 空 | `local_import` / `cloud_api`，为空时由环境推导 |
| `CORS_ORIGINS` | localhost / 127.0.0.1:3000 | 管理后台 CORS 白名单 |
| `ALLOWED_HOSTS` | localhost / 127.0.0.1 / testserver | Host header 白名单 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `OBSERVABILITY_TOKEN` | 空 | 生产访问 `/health/metrics` 所需 Bearer Token |

### 6.2 部署画像

后端支持两个主要 deployment profile：

| Profile | 适用场景 | 特征 |
|---|---|---|
| `local_import` | 本地开发、重 OCR/导题场景 | 可使用本地 OCR / GPU 等能力 |
| `cloud_api` | 生产 API 服务 | 更严格的资源、安全和 OCR 隔离策略 |

解析规则概览：

- `DEPLOYMENT_PROFILE` 显式设置时优先使用。
- `APP_ENV=production` 时必须使用 `cloud_api`。
- 非生产环境未指定 profile 时通常解析为 `local_import`。

### 6.3 AI / LLM

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `AI_TIMEOUT` | `150` | AI 调用超时（秒） |
| `AI_DAILY_TOKEN_LIMIT` | `50000` | 日 Token 预算 |
| `AI_MONTHLY_TOKEN_LIMIT` | `500000` | 月 Token 预算 |
| `AI_MAX_CONCURRENCY` | `3` | 统一 AI 并发上限 |
| `AI_USER_RPM_LIMIT` | `12` | 用户级每分钟请求限制 |
| `AI_CONFIG_ENCRYPT_KEY` | 空 | 后台 AI 凭据加密密钥 |
| `AI_ALLOW_HTTP_BASE_URLS` | `false` | 是否允许非 HTTPS 的 AI Base URL |

模型 API Key、Base URL、模型标识等主要通过管理后台配置并持久化，而不是直接硬编码到源码。

### 6.4 OCR

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `OCR_ENABLED` | `false` | OCR 总开关 |
| `OCR_USE_GPU` | `true` | 本地 OCR 是否使用 GPU；`cloud_api` 有额外限制 |
| `OCR_LANGUAGE` | `ch` | OCR 语言 |
| `OCR_MAX_WORKERS` | `2` | OCR worker 数 |
| `OCR_EXECUTION_BACKEND` | `paddlex_http` | `disabled` / `local_process` / `paddlex_http` |
| `OCR_REMOTE_URL` | `http://127.0.0.1:8080/ocr` | 远程 OCR endpoint |
| `OCR_REMOTE_TOKEN` | 空 | 远程 OCR 鉴权 Token |
| `OCR_REMOTE_CONNECT_TIMEOUT_SEC` | `5` | 连接超时 |
| `OCR_REMOTE_READ_TIMEOUT_SEC` | `600` | 读取超时 |
| `MAX_OCR_PAGES` | `0` | 最大 OCR 页数；`0` 表示不限 |

> OCR 配置较多，实际部署时以 `backend/app/core/config.py` 与 `.env.example` 为准。

### 6.5 Redis / 队列

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `REDIS_URL` | 空 | Redis 地址；生产任务与缓存能力依赖 Redis |
| `ALLOW_IN_MEMORY_TASK_QUEUE` | `false` | 是否允许内存队列回退，仅适合本地调试 |

### 6.6 数据库连接池

生产环境支持按进程角色配置独立连接池：

| 变量 | 默认值 |
|---|---:|
| `DB_POOL_SIZE_WEB` | `3` |
| `DB_MAX_OVERFLOW_WEB` | `5` |
| `DB_POOL_SIZE_WORKER` | `2` |
| `DB_MAX_OVERFLOW_WORKER` | `3` |
| `DB_POOL_SIZE_SCHEDULER` | `1` |
| `DB_MAX_OVERFLOW_SCHEDULER` | `2` |

---

## 7. API 与开发文档

### 7.1 Public API

小程序接口前缀：

```text
/api/v1
```

主要领域：

| 领域 | 示例 |
|---|---|
| 认证 | `/auth/login`, `/auth/refresh` |
| 用户 | `/users/me` |
| 题库 | `/questions`, `/questions/{id}` |
| 刷题 | `/practice/*` |
| 错题 | `/wrong-questions/*` |
| 复习 | `/review/*` |
| 学习统计 | `/stats/*`, `/study-report/*` |
| AI / RAG | `/ai/*`, `/rag/*` |
| 知识与自适应 | `/knowledge-*`, `/adaptive-learning/*` |
| 公式卡 | `/formulas/*` |
| 番茄钟 | `/pomodoro/*` |
| 导入 / 导出 | `/import/*`, `/exports/*` |
| 同步 / 缓存 | `/sync/*`, `/cache/*` |

### 7.2 Admin API

后台接口前缀：

```text
/api/admin/v1
```

主要领域：认证、Dashboard、App 用户、管理员、RBAC、科目、题库、导入审核、公式卡、知识图谱、推荐、AI 设置、向量配置、水印、审计日志、任务队列和系统健康。

### 7.3 API source of truth

开发环境优先查看运行时 OpenAPI：

```text
http://localhost:8000/docs
http://localhost:8000/openapi.json
```

项目内文档可继续维护：

```text
docs/backend/API_SPEC.md
docs/admin/ADMIN_API_SPEC.md
```

> README 只保留稳定的接口领域和入口，避免复制完整路由清单后长期失真。

---

## 8. 数据库与迁移

### 8.1 本地开发

推荐使用 SQLite：

```env
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db
```

`local_import` 画像下，应用启动会注册模型并执行本地数据库初始化/兼容修复逻辑，适合快速开发。

### 8.2 生产环境

推荐：

```env
APP_ENV=production
DEPLOYMENT_PROFILE=cloud_api
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgraduate
REDIS_URL=redis://HOST:6379/0
```

生产数据库应由 Alembic 管理：

```bash
cd backend
alembic upgrade head
```

检查当前 revision：

```bash
alembic current
alembic heads
```

CI 的 Reliability Gate 会执行全部迁移，并校验数据库 revision 与仓库 Alembic heads 一致。

### 8.3 核心数据域

主要模型可按领域理解：

- 用户与认证：`users`, `refresh_tokens`
- 题库：`questions`, `question_versions`, `subjects`, `knowledge_points`
- 刷题与错题：`practice_records`, `practice_sessions`, `wrong_questions`
- 复习：`review_schedules`, `review_records`
- 番茄钟：`pomodoro_sessions`, `pomodoro_pause_intervals`, `user_pomodoro_settings`
- 管理后台：`admin_users`, `roles`, `permissions`, `role_permissions`, `audit_logs`
- AI：`admin_ai_model_configs`, `admin_ai_configs`, AI usage / feedback logs
- 导题：import pipeline / batch job / OCR job 相关表
- 公式卡：formula card / version / tag / graph / import 相关表
- 推荐：strategy / experiment / assignment / metrics / logs
- 异步任务：`task_outbox` 等任务基础设施表

---

## 9. 测试、代码质量与 CI

仓库当前有三类主要 GitHub Actions 检查：

### 9.1 CI / lint-and-audit

主要包含：

1. `compileall`：全量 Python 语法检查
2. Ruff correctness gate
3. 修改文件的严格 Ruff gate
4. Ruff legacy debt report
5. Ruff format（当前以迁移/提示为主）
6. MyPy、Bandit、pip-audit
7. 静态架构与非 GPU 回归测试
8. import smoke test
9. OCR benchmark（advisory）
10. Docker image build

本地建议至少执行：

```bash
cd backend

python -m compileall -q app
ruff check app/ --ignore I001,F401,N818
```

对于你本次新增或修改的 Python 文件，建议额外严格执行：

```bash
ruff check path/to/changed_file.py
```

这样可以提前发现 `F823`、未定义变量、作用域错误等会直接阻塞 CI 的问题。

### 9.2 Reliability Gate

Reliability workflow 会覆盖：

- PostgreSQL + pgvector service
- Redis service
- Alembic 全量迁移
- Alembic head 一致性校验
- 后端 reliability unit / integration tests
- OpenAPI contract 导出与校验
- FastAPI OpenAPI → TypeScript contract
- 管理后台 TypeScript contract 检查
- 管理后台构建

### 9.3 前端与小程序

管理后台：

```bash
cd admin-frontend
npm run build
```

微信小程序没有统一测试命令时，可运行 `scripts/test-*.js` 中与当前改动相关的测试脚本，并通过微信开发者工具进行编译、真机/模拟器验证。

---

## 10. 生产部署

### 10.1 部署前检查

生产环境至少确认：

- `APP_ENV=production`
- `DEPLOYMENT_PROFILE=cloud_api`
- 替换默认 `APP_SECRET`
- 配置 PostgreSQL 与 Redis
- 配置 `ALLOWED_HOSTS` 与 `CORS_ORIGINS`
- 禁用或修改开发默认管理员
- 使用 HTTPS
- 不把 `.env`、数据库密码、微信 AppSecret、AI API Key、OCR Token 提交到 Git
- 执行 Alembic migration
- 检查 `/health`、ready/live health
- 确认 worker 与 scheduler 已启动

### 10.2 GitHub Deploy workflow

当前 Deploy workflow 为手动触发（`workflow_dispatch`）：

1. GitHub Actions 先运行后端测试。
2. 仅 `main` 分支进入 deploy job。
3. 通过 SSH 登录服务器。
4. 在部署目录执行：

```bash
bash deploy/scripts/deploy.sh update
```

部署主逻辑应继续集中维护在 `deploy/scripts/`，避免把复杂部署步骤复制到 README 或 workflow 中形成多套实现。

### 10.3 架构

生产环境使用 `deploy/docker-compose.prod.yml` 部署，当前包含 8 个服务：

| 服务       | 说明                              |
| ---------- | --------------------------------- |
| `app`      | FastAPI + Gunicorn Web 进程       |
| `worker`   | OCR/AI/导入等异步任务 worker      |
| `scheduler`| 定时任务、导出与清理 scheduler    |
| `nginx`    | nginx HTTPS 反向代理              |
| `postgres` | pgvector/PostgreSQL 15 持久卷     |
| `redis`    | Redis 7 任务队列与缓存             |
| `admin`    | Next.js 管理前端（仅内网 3000）   |
| `backup`   | PostgreSQL 备份任务                |

网络拓扑：

```
用户 → nginx:443 (HTTPS) → app:8000 (HTTP)
                      → postgres:5432（仅 app 可访问）
                      → redis:6379（仅 app 可访问）
```

### 10.4 服务器信息

> 2026-08-06 生产已迁移至新服务器并完成 DNS 切流；2026-08-07 旧机服务已停用（数据卷保留，可回滚）。新服务器为当前唯一生产。

| 项目     | 新服务器（当前生产）                                      | 旧服务器（冷备）                   |
| -------- | --------------------------------------------------------- | ---------------------------------- |
| 域名     | `xzshub.top`                                              | `xzshub.top`（DNS 已改指新服务器） |
| 公网 IP  | `101.33.231.186`                                          | `8.163.56.109`                     |
| 内网 IP  | `10.1.0.13`                                               | `172.18.50.44`                     |
| 部署目录 | `/opt/22408-ai`                                           | `/opt/2240ai-v2`                   |
| 连接密钥 | `Linux_connect.pem`                                       | `loginkey.pem`                     |
| CPU      | 4 核（AMD EPYC 7K62）                                     | 2 核                               |
| 内存     | 3.6 GiB                                                   | 1.8 GB                             |
| 磁盘     | 40 GB（注意 Docker 镜像/缓存占用，构建前先 `df -h` 检查） | —                                  |
| OS       | OpenCloudOS 9.6（RPM 系）                                 | Linux (Debian)                     |

### 10.5 部署流程

详细部署文档见 `docs/project/DEPLOY_PLAN.md`。

**日常更新：**

```bash
# 同步代码
rsync -az --exclude-from=".deployignore" \
  -e "ssh -i Linux_connect.pem -o BatchMode=yes" \
  ./ root@101.33.231.186:/opt/22408-ai/

# 构建镜像并替换 app（含健康检查）
ssh root@101.33.231.186 "cd /opt/22408-ai && bash deploy/scripts/deploy.sh update"

# 如包含新 migration，app 启动会因"迁移落后"检查失败，
# 需先停 app → 迁移 → 重启：
ssh root@101.33.231.186 "cd /opt/22408-ai && docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml stop app"
ssh root@101.33.231.186 "cd /opt/22408-ai && bash deploy/scripts/deploy.sh migrate"
ssh root@101.33.231.186 "cd /opt/22408-ai && docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml start app"

# 或仅执行显式迁移（无新 migration 时）
ssh root@101.33.231.186 "cd /opt/22408-ai && bash deploy/scripts/deploy.sh migrate"
```

**禁止的日常操作：**

- ❌ `docker compose down` — 会停止 postgres/redis/nginx，数据不丢失但会导致服务中断
- ❌ `docker compose build --no-cache` — 破坏 layer cache
- ❌ 从本地覆盖服务器 `backend/.env`、`cert/`、密钥

### 10.6 关键文件

| 路径                                     | 说明                                         |
| ---------------------------------------- | -------------------------------------------- |
| `deploy/docker-compose.prod.yml`         | 生产 Docker Compose 入口                     |
| `deploy/scripts/deploy.sh`               | 生产部署脚本                                 |
| `deploy/nginx/nginx.conf`                | Nginx 配置                                   |
| `scripts/postgres_backup.py`             | PostgreSQL 备份脚本（pg_dump custom format） |
| `deploy/scripts/backup.sh`               | 旧版备份脚本（已弃用，引用自 Python 脚本）   |
| `deploy/Dockerfile.backup`               | 备份容器镜像（Python + postgresql-client）   |
| `deploy/systemd/postgres-backup.service` | systemd backup 服务单元                      |
| `deploy/systemd/postgres-backup.timer`   | systemd 定时器（每天 03:00）                 |
| `deploy/Dockerfile.prod`                 | 生产多阶段 Dockerfile                        |

---

## 11. WSL → Windows 同步

仓库提供 `sync-to-windows.sh`，用于将 WSL 中的项目镜像到 Windows 文件系统，方便使用 Windows IDE 或 GUI 工具。

脚本特点：

- 以 `.gitignore` 作为主要排除规则来源
- 不同步 `.git`，Git 操作继续留在 WSL
- 使用适合 drvfs/NTFS 的 rsync 参数，避免 `-a` 带来的 owner/group/permission 问题
- 使用 `--delete-after` 与 `--partial`
- 对虚拟环境、tests、prompts、artifacts、SSL 等目录做额外排除
- 保留 `backend/static/question-assets/` 供本地渲染检查

先预览：

```bash
./sync-to-windows.sh -n
```

确认后同步：

```bash
./sync-to-windows.sh
```

如果脚本没有执行权限：

```bash
chmod +x sync-to-windows.sh
```

当前脚本默认目标目录：

```text
/mnt/d/workspace/postgraduate-ai/
```

如本机目录不同，修改脚本中的 `DST` 后再执行。

---

## 12. 常见问题

### 后端一启动就报生产配置错误

检查 `.env` 是否明确设置：

```env
APP_ENV=development
```

因为代码默认环境是 `production`，未配置时会执行更严格的生产校验。

### 小程序无法访问本地 API

微信开发者工具可使用：

```text
http://localhost:8000/api/v1
```

真机不能通过 `localhost` 访问电脑。真机调试需要使用手机可访问的局域网地址、HTTPS 测试域名或正式域名，并同步处理微信小程序合法域名配置。

### 管理后台请求 401 / 403

依次检查：

- 管理员是否已登录
- access token 是否过期
- refresh 是否正常
- 当前角色是否拥有对应 permission
- `NEXT_PUBLIC_ADMIN_API_BASE_URL` 是否指向正确后端

### Ruff 报 `F823 Local variable ... referenced before assignment`

这通常不是 workflow 配置问题，而是 Python 作用域问题。例如函数内部再次 `import` 或赋值某个名字，会让该名字被视为局部变量，从而导致前面的引用失效。应修复源码，而不是把 `F823` 加入 Ruff ignore。

### OCR 不工作

优先检查：

```env
OCR_ENABLED=true
OCR_EXECUTION_BACKEND=...
```

若使用远程 OCR，再检查 `OCR_REMOTE_URL`、网络连通性、Token、HTTP/HTTPS 策略以及 deployment profile 是否允许该配置。

---

## 文档维护原则

建议将 README 保持为「入口文档」，而把高频变化内容放到专项文档：

- 完整 API → OpenAPI / `docs/backend/` / `docs/admin/`
- 系统架构 → `docs/architecture/`
- OCR / AI pipeline → `docs/ai/`
- UI / 组件规范 → `docs/frontend/`
- 发布、迁移、运维 → `deploy/` 与项目运维文档

当代码、环境变量或 workflow 行为变化时，优先更新其 source of truth，再同步 README 中的入口说明。
