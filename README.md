# MemoGrad / 408AI 智能刷题系统

<img src="assets/qr_code.jpg" alt="小程序码" width="160" />

MemoGrad 是一个面向考研学习场景的智能刷题与题库治理系统，由 **FastAPI 后端**、**Next.js 管理后台** 和 **微信小程序** 三部分组成。

系统覆盖题库练习、错题与复习、学习报告、番茄钟、公式卡、AI 讲解、OCR/AI 导题、知识图谱、自适应学习、后台审核、RBAC、审计日志、AI 模型配置、向量检索以及异步任务治理等能力。

> 本 README 面向「首次运行项目、日常开发、CI 排错和部署维护」。API 的完整字段与协议应以运行时 OpenAPI 和 `docs/` 中的专项文档为准。

> 当前实现快照（2026-11-06）：后端已完成 Public/Admin 路由分层、Redis 任务队列与运维诊断；Admin 使用 Next.js 16.2.12 + React 19.2.4；生产部署必须使用 `APP_ENV=production` + `DEPLOYMENT_PROFILE=cloud_api`，生产入口与服务器连接信息见 [DEPLOY_PLAN.md](docs/project/DEPLOY_PLAN.md)；用户与 Admin JWT 签名域隔离。游客体验已上线：未登录可匿名浏览公式与公共科目目录，并按科目随机试做（5/10/20/30 题，批次独立签名、24 小时有效、不写个人学习数据），登录入口唯一且可取消。408 选择题考试（试卷、作答、成绩、历史、管理端组卷）已接入。多空题分为每空单选 `multi_blank_choice` 与每空多选 `multi_blank_multiple_choice`。公式卡支持函数图，生产用命名卷 `formulas_data` 持久化上传图。错题展示、统计和 AI 分析会跟随当前题库内容，错因分析以服务端核对过的作答事实为准，同时保留错题产生时的历史版本；小程序错题详情会在前台切题时校验最新数据，并提供短时缓存弱网兜底。AI 模型健康状态使用 Redis 共享缓存，预热失败走有界重试并恢复历史死信预算。番茄钟统计只计入已结束会话。

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
- 游客模式：匿名浏览公式与公共科目目录、按科目随机试做（5/10/20/30 题）与匿名判分，本机草稿 24 小时有效
- 自主登录：唯一入口在首页顶部，登录提示可取消，成功后返回来源页；手机号/头像/昵称不是体验前置条件
- 刷题、随机练习、答题记录与学习统计
- 错题本、错题详情、质量反馈
- 今日复习、复习调度、掌握状态管理
- 自适应学习、弱知识点、学习路径与推荐
- 学习报告、趋势、知识掌握分析
- AI 题目讲解、错因分析、学习建议
- 番茄钟、暂停/恢复、专注统计与历史记录
- 408 选择题考试：试卷列表、作答、成绩与历史
- 公式卡浏览、收藏、分类、函数图与公式渲染
- 错题/学习数据导出（PDF；Word 由服务端 `docx_enabled` 决定是否开放）
- KaTeX / mp-html 富文本与数学公式渲染

### 管理后台

- 管理员登录、刷新、退出与密码管理
- Dashboard 与运营数据概览
- 小程序用户管理、封禁/解封、管理员绑定
- 管理员账号、角色与权限矩阵（RBAC）
- 题库查询、编辑、上下架、版本与图片/选项管理
- 408 选择题试卷：组卷、发布、归档与软删除
- OCR / AI 导题、文本导入、题目 CSV 导入、批量图片导入与审核发布
- 公式卡、分类、版本、审核状态与函数图资源管理
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
- AI 模型健康状态共享缓存与预热有界重试
- 游客只读/试做 API：签名批次、按 IP 限流、不写个人数据；公式公共读取与 `/practice/subjects` 采用可选身份鉴权
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
│   ├── tests/                   # 按领域分包的测试（ocr_pipeline、canary、export 等）
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
│   ├── pages/                   # 主包：登录、首页；协议、Dashboard、番茄钟另作分包
│   ├── subpackages/
│   │   ├── study/               # 刷题、复习、错题、学习计划
│   │   ├── exam/                # 408 选择题考试
│   │   ├── knowledge/           # 知识地图
│   │   ├── productivity/        # 番茄钟统计
│   │   ├── formulas/            # 公式卡与函数图
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

- Next.js 16.2 + React 19.2
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

管理后台使用 App Router，主要页面包括 Dashboard、用户、管理员、角色、题库、408 试卷、导入审核、公式卡、知识图谱、推荐策略、AI 设置、审计日志和系统任务等。

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
| 体验版 / 正式版 | 生产 API，地址见 `miniprogram/config.js` |

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
| 游客体验 | `/guest/practice/subjects`, `/guest/practice/questions`, `/guest/practice/evaluate` |
| 错题 | `/wrong-questions/*` |
| 复习 | `/review/*` |
| 学习统计 | `/stats/*`, `/study-report/*` |
| AI / RAG | `/ai/*`, `/rag/*` |
| 知识与自适应 | `/knowledge-*`, `/adaptive-learning/*` |
| 公式卡 | `/formulas/*` |
| 408 考试 | `/exams/*` |
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
docs/api/GUEST_EXPERIENCE_API.md
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

CI 的 Reliability Gate 会在 PostgreSQL 上执行全部迁移，并校验数据库 revision 与仓库 Alembic heads 一致。SQLite 上的升级/降级循环和历史检查点矩阵见 §9.3。

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
- 408 考试：`exam_papers`, `exam_paper_questions`, `exam_attempts`, `exam_answers`
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

### 9.2 后端测试组织

后端测试位于 `backend/tests/`，按领域分包：

| 目录 | 内容 |
|---|---|
| `tests/ocr_pipeline/` | OCR 流水线、页面流、PDF 解析、题号解析 |
| `tests/pipeline/` | pipeline 编排、coordinator、fingerprint |
| `tests/canary/` | OCR/IR Canary 配置、分桶、回滚、发布决策 |
| `tests/architecture/` | 架构边界、生产写零违规守卫 |
| `tests/document_ir/` | Document IR、跨页合并、reading order |
| `tests/export/` | DOCX 导出、OMML、导出安全 |
| `tests/quality_gate/` | 质量门禁 |
| `tests/test_services/` `tests/test_api/` `tests/test_features/` `tests/core/` | 业务服务、API、功能特性、核心设施 |
| `tests/cloud_isolation/` `tests/integration/` `tests/knowledge/` `tests/practice/` `tests/scripts_tests/` 等 | 云端隔离、集成、知识诊断、练习、脚本 |

CI（`.github/workflows/ci.yml`）使用固定测试文件清单；移动、重命名或新增测试文件后必须同步该清单以及 `backend/pytest.ini` 的 `testpaths` 和 `backend/scripts/run_profile_test_matrix.py`。

本地运行示例：

```bash
cd backend
.venv/bin/python -m pytest tests/quality_gate -q
.venv/bin/python -m pytest tests/ocr_pipeline/test_ocr_request.py -q
```

> 注意：全量本地 pytest 包含依赖 PostgreSQL/Redis/外部 OCR 服务的用例，失败不代表代码有问题；CI 只跑固定清单。

### 9.3 迁移测试

迁移检查不在 `lint-and-audit` 的固定 pytest 清单里。`push` / `pull_request` 到 `main` 时，`.github/workflows/ci.yml` 另有两个 job；`.github/workflows/reliability.yml` 再在 PostgreSQL 上做一次全量迁移。

`migration-cycle` 使用 `sqlite:///migration-ci.db`，工作目录是 `backend/`：

1. `alembic heads` 必须正好一个 head。
2. `alembic upgrade head`。
3. `alembic downgrade -1`，然后再 `alembic upgrade head`。

`migration-history-matrix` 使用 `sqlite:///migration-history-ci.db`：

1. `python scripts/ci_collect_migration_checkpoints.py` 从唯一 head 沿第一条 parent 链取样，每 10 个 revision 取一个检查点，并带上链尾。
2. `python scripts/ci_migration_matrix_check.py migration-checkpoints.json` 对每个检查点执行 `upgrade`、`downgrade -1`、再 `upgrade`，最后 `upgrade head`。

矩阵不把整条历史做成一次线性降级，因此不会主动走过标记为不可逆的旧迁移。

在 `backend/` 且依赖已安装时，可以本地复现：

```bash
DATABASE_URL=sqlite:///migration-ci.db alembic heads
DATABASE_URL=sqlite:///migration-ci.db alembic upgrade head
DATABASE_URL=sqlite:///migration-ci.db alembic downgrade -1
DATABASE_URL=sqlite:///migration-ci.db alembic upgrade head

DATABASE_URL=sqlite:///migration-history-ci.db python scripts/ci_collect_migration_checkpoints.py > migration-checkpoints.json
DATABASE_URL=sqlite:///migration-history-ci.db python scripts/ci_migration_matrix_check.py migration-checkpoints.json
```

Reliability Gate 与上面两组 SQLite job 不同：它在 `pgvector/pgvector:pg15` 上执行 `alembic upgrade head`，并断言数据库 revision 等于仓库 Alembic heads。同一步里的 `alembic check` 只报告 ORM 与迁移漂移，`continue-on-error: true`，失败不阻断该 workflow。

仓库里还有针对迁移的 pytest。它们不在 `ci.yml` 的固定清单中。`tests/test_features/` 和 `tests/test_services/` 写在 `backend/pytest.ini` 的 `testpaths` 里，默认 `pytest` 会跑到其中一部分。

| 测试 | 覆盖 |
|---|---|
| `tests/test_features/test_migration_smoke.py` | 单一 head；空 SQLite 可 `upgrade head`。降级循环只在 `DATABASE_URL` 指向 PostgreSQL 时运行 |
| `tests/test_features/test_migration_ci_scripts.py` | 检查点列表非空、不重复，并拒绝非法 JSON；断言最后一个检查点是当前迁移链链尾（2026-11-06 为 `v19_pomodoro_subject_allocations`），迁移链推进时需同步更新该断言 |
| `tests/test_services/test_p5_0_schema_baseline_migration.py` | `p5_0_schema_baseline` 迁移文件和相关 ORM 声明 |
| `tests/test_services/test_pomodoro_v2_migration.py` | 番茄钟 V2 回填、幂等和迁移后校验 |
| `tests/integration/test_pomodoro_constraints_migration.py`、`tests/integration/test_pomodoro_constraint_definition_migration.py` | 在内存 SQLite 上执行对应迁移操作 |
| `tests/ocr_pipeline/test_migration_question_types.py` | 迁移文件中的 `CANONICAL_TYPES` 与 `QuestionType` 一致 |
| `tests/integration/test_alembic_fresh_database.py` | 空库只走 Alembic，不调用 `create_all`。需要 `--run-integration` |
| `tests/integration/test_migration_subject_id.py`、`tests/integration/test_migration_question_embeddings.py`、`tests/integration/test_migration_question_embeddings_model_fk.py` | 在真实 PostgreSQL 上验证科目 ID 与 embedding 外键迁移。需要 `--run-integration`，测试文件默认连 `localhost:5433` |

`--run-integration` 的跳过逻辑在 `backend/tests/integration/conftest.py`。没有 PostgreSQL 时，这些集成失败不代表 SQLite 迁移 job 失败。

### 9.4 Reliability Gate

Reliability workflow 会覆盖：

- PostgreSQL + pgvector service
- Redis service
- Alembic 全量迁移与 head 一致性校验（SQLite 循环见 §9.3）
- 后端 reliability unit / integration tests
- OpenAPI contract 导出与校验
- FastAPI OpenAPI → TypeScript contract
- 管理后台 TypeScript contract 检查
- 管理后台构建

### 9.5 前端与小程序

管理后台：

```bash
cd admin-frontend
npm run build
```

微信小程序没有统一测试命令时，可运行 `miniprogram/tests/` 中与当前改动相关的独立 Node 测试脚本，并通过微信开发者工具进行编译、真机/模拟器验证。例如：

```bash
cd miniprogram
node tests/test-render-invariant.js
node tests/test-config-resolution.js
node tests/render_regression/run.js
```

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
| `worker`   | Redis 任务消费者（投影、AI 预热等）；生产 OCR 不在此进程执行 |
| `scheduler`| 定时任务、导出与清理 scheduler    |
| `nginx`    | nginx HTTPS 反向代理              |
| `postgres` | pgvector/PostgreSQL 15 持久卷     |
| `redis`    | Redis 7 任务队列与缓存             |
| `admin`    | Next.js 管理前端（仅内网 3000）   |
| `backup`   | PostgreSQL 备份任务                |

网络拓扑：

```
用户 → nginx:443 (HTTPS) → app:8000（/api、/health、/static）
                         → admin:3000（/admin）
app / worker / scheduler / backup → postgres:5432
app / worker / scheduler → redis:6379
```

### 10.4 服务器信息

生产入口、服务器规格与连接信息保留在本地部署文档中，README 不再重复记录。完整内容见 [DEPLOY_PLAN.md](docs/project/DEPLOY_PLAN.md)。

构建前先 `df -h`。主机级操作按 RPM 系命令执行。

### 10.5 部署流程

完整备份、同步、更新、worker 重建、显式迁移和 nginx reload 命令见本地 [DEPLOY_PLAN.md](docs/project/DEPLOY_PLAN.md)。

**禁止的日常操作：**

- ❌ `docker compose down` — 会停止 postgres/redis/nginx，数据不丢失但会导致服务中断
- ❌ `docker compose build --no-cache` — 破坏 layer cache
- ❌ 从本地覆盖服务器 `backend/.env`、`cert/`、密钥

### 10.6 关键文件

| 路径                                     | 说明                                         |
| ---------------------------------------- | -------------------------------------------- |
| `deploy/docker-compose.prod.yml`         | 生产 Docker Compose 入口                     |
| `deploy/scripts/deploy.sh`               | 生产部署脚本                                 |
| `deploy/scripts/redis_backup.sh`         | Redis RDB 备份脚本（默认归档到宿主机 `redis_backups/`，可用 `REDIS_BACKUP_DIR` 覆盖） |
| `deploy/scripts/redis_restore.sh`        | Redis 恢复脚本（AOF-safe，恢复期间短暂停止 Redis） |
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

### 游客 / 匿名请求 401 / 403 / 429

- 公式公共读取与 `/practice/subjects` 为可选身份鉴权：无凭据按匿名返回公共内容；携带无效凭据会直接 401，不会降级为匿名。
- 游客试做三个端点按客户端 IP 限流 120 次/分钟，超限返回 429，限流缓存不可用返回 503。
- 游客凭据只能调用 `/guest/practice/*` 与匿名判分，不能用于正式交卷；正式个人接口始终要求有效登录。

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
