# MemoGrad / 22408AI刷题小程序 项目说明

MemoGrad 是一个面向考研场景的智能刷题与题库管理系统。项目由 **FastAPI 后端服务**、**Next.js 后台管理端**、**微信小程序端** 三部分组成，覆盖微信登录、题库练习、错题本、复习计划、学习报告、番茄钟、AI 题目讲解、OCR/AI 导题、后台题库治理、角色权限、审计日志、AI 模型配置与向量检索等功能。

---

## 1. 项目结构

```text
.
├── backend/                    # FastAPI 后端服务
│   ├── app/                    # Python 应用源码
│   │   ├── main.py             # FastAPI 应用入口
│   │   ├── api/                # API 路由
│   │   │   ├── v1/             # 小程序/公共端 API
│   │   │   └── admin/          # 管理端 API
│   │   ├── ai/                 # AI Prompt、上下文、兜底逻辑
│   │   ├── core/               # 配置、数据库、安全、缓存、日志、Sentry
│   │   ├── features/           # OCR、导题、题目拆分、质量校验、版面识别
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── services/           # 业务服务层
│   │   └── utils/              # 工具函数
│   ├── alembic/                # 数据库迁移
│   ├── docker/                 # Docker 构建配置
│   ├── requirements.txt        # Python 依赖
│   ├── requirements-ocr.txt    # OCR 额外依赖（PaddleOCR 等）
│   ├── Dockerfile              # Docker 镜像构建
│   ├── gunicorn.conf.py        # 生产 Gunicorn 配置
│   └── .env.example            # 环境变量模板
│
├── admin-frontend/             # 后台管理端（Next.js）
│   ├── package.json            # Node 依赖
│   ├── next.config.ts          # Next.js 配置
│   ├── tsconfig.json           # TypeScript 配置
│   └── src/
│       ├── app/                # App Router 页面
│       ├── components/         # 通用 UI、布局、审计日志、数据表组件
│       └── lib/                # API client、权限、鉴权状态、工具函数
│
├── miniprogram/                # 微信小程序端
│   ├── pages/                  # 登录、首页、刷题、错题本、复习、导入、报表、番茄钟
│   ├── components/             # 题目卡片、数学公式渲染、动画、mp-html
│   ├── utils/                  # API、鉴权、缓存、题干渲染、数学格式化
│   ├── app.js / app.json
│   └── config.js               # 小程序 API 环境配置
│
├── deploy/                     # 生产部署
│   ├── docker-compose.prod.yml # 生产 Docker Compose
│   ├── docker-compose.dev.yml  # 开发 Docker Compose
│   ├── Dockerfile.prod         # 生产多阶段构建镜像
│   ├── nginx/                  # Nginx 配置、SSL 证书
│   ├── scripts/                # 部署、备份、迁移脚本
│   └── systemd/                # systemd 服务单元
│
├── docs/                       # 项目文档
│   ├── architecture/           # 系统架构、OCR、记忆系统、复习算法
│   ├── backend/                # API 端点、DB schema、存储设计
│   ├── frontend/               # UI 规则、设计系统、组件规范
│   ├── project/                # 项目规则、路线图、变更日志
│   ├── ai/                     # AI 管线、OCR 策略、标准化流程
│   └── ...
│
├── prompts/                    # 当前开发任务与系统 Prompt
├── scripts/                    # 实用脚本
├── tests/                      # 测试用例
├── .env.example                # 环境变量模板（根入口）
└── CLAUDE.md                   # 项目 AI 辅助指令
```

---

## 2. 技术栈

### 后端 `backend/`

- Python 3.11 + FastAPI 0.111
- SQLAlchemy 2.0 Async ORM + Alembic 迁移
- PostgreSQL 15（生产）/ SQLite（开发）
- Redis 7（生产必需：缓存、番茄钟调度锁）
- JWT（HS256）+ refresh token + 管理员 RBAC
- Gunicorn + Uvicorn worker（生产）
- Docker + Docker Compose 部署
- APScheduler 定时任务
- Sentry 错误监控（可选）
- PyMuPDF / Pillow / PaddleOCR（可选，GPU 加速支持）
- **OCR 模型**：本地 PP-OCRv4（PaddleOCR 2.10.0）+ 外部 PaddleOCR-VL 1.6（API 服务）
- DeepSeek API（httpx 直连，无 langchain/llamaindex）
- pgvector 向量检索（可选）

### 后台管理端 `admin-frontend/`

- Next.js 16 + React 19
- TypeScript
- TanStack Query / TanStack Table
- Zustand 状态管理
- ECharts 6 / Recharts 图表
- Lucide React 图标
- Tailwind CSS v4

### 微信小程序 `miniprogram/`

- 原生微信小程序
- 微信登录 `wx.login`
- 本地 token / refresh token 存储
- Lottie 动画分包
- KaTeX / mp-html 公式和富文本渲染

---

## 3. 核心功能

### 小程序端

- 微信登录与自动续签
- 首页学习入口
- 刷题练习与答题提交
- 错题本、错题详情、错题质量反馈
- 今日复习、复习计划、掌握/未掌握标记
- 学习报告、趋势、知识掌握分析
- AI 题目讲解、错因分析、学习建议
- 题目导入入口
- 番茄钟、专注统计、完成提醒
- 数学公式与复杂题干渲染

### 后台管理端

- 管理员登录、刷新登录态、退出登录
- 总览仪表盘
- 小程序用户管理、封禁/解封、绑定管理员
- 管理员账号管理、强制下线、重置密码
- 角色与权限矩阵
- 题库列表、题目详情、编辑、上下架、版本查看、批量删除
- 题目导入管理：文件上传、文本导入、批量图片导入、审核、发布、失败样本导出
- AI 解析设置：OCR、补全、模型配置、调用统计、向量配置
- 审计日志查看
- 系统健康检查

### 后端能力

- Public API：登录、刷题、错题、复习、统计、知识点、AI、导入、缓存、番茄钟、同步
- Admin API：管理端认证、用户、角色权限、题库、导入、AI 配置、审计日志、推荐策略、知识图谱、系统健康
- OCR 导题流水线：页面分类、区域检测、文本纠错、题目拆分、AI 补全、质量门禁、发布
  - **双 OCR 模型**：本地 PP-OCRv4 作为基础识别引擎，外部 PaddleOCR-VL 1.6 作为高精度纠错与视觉回退
  - OCR 纠错链路：`PaddleOCR-VL → DeepSeek AI → rule fallback`（自动降级）
- 自适应学习与推荐：知识状态、难度状态、复习调度、向量召回、推荐实验与指标
- 定时任务：refresh token 清理、番茄钟提醒、审计日志清理、AI 预热 worker

---

## 4. 快速启动

### 4.1 环境要求

- Python 3.11+
- Node.js 20+
- 微信开发者工具

### 4.2 启动后端服务

#### 1）创建虚拟环境

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

#### 2）安装依赖

```bash
pip install -r requirements.txt
```

如需 OCR 能力，额外安装：

```bash
pip install -r requirements-ocr.txt
```

#### 3）创建 `.env`

```bash
cp .env.example .env
```

编辑 `.env`，至少填入以下必填项：

```env
APP_SECRET=change-me-in-production
WECHAT_APP_ID=
WECHAT_APP_SECRET=
DEEPSEEK_API_KEY=
```

#### 4）启动服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
```

开发环境也会自动建表并创建初始管理员（`admin / admin`）。

#### 5）使用 Docker Compose（开发）

```bash
docker compose -f deploy/docker-compose.dev.yml up -d
```

#### 6）开发环境默认管理员

当 `APP_ENV` 为 `development`、`local` 或 `test` 时，后端启动会尝试创建开发环境超级管理员：

```text
用户名：admin
密码：admin
```

生产环境必须修改默认账号与密码，并配置安全的 `APP_SECRET`、数据库连接和 CORS 白名单。

---

### 4.3 启动后台管理端

```bash
cd admin-frontend
npm install
npm run dev
```

环境变量（可选，默认连接 `http://localhost:8000`）：

```env
NEXT_PUBLIC_ADMIN_API_BASE_URL=http://localhost:8000/api/admin/v1
```

访问：

```text
http://localhost:3000
```

管理端默认跳转到 `/dashboard`，未登录时进入 `/login`。

---

### 4.4 启动微信小程序

#### 1）安装依赖

```bash
cd miniprogram
npm install
```

#### 2）配置 API 地址

编辑 `miniprogram/config.js`：

```js
const DEV = true
```

开发环境默认请求 `http://localhost:8000/api/v1`，生产请求 `https://xzshub.top/api/v1`。

#### 3）微信开发者工具打开

使用微信开发者工具打开 `miniprogram/` 目录。当前项目配置：

```text
projectname: MemoGrad
appid: wx013724bc2f592940
libVersion: 3.3.4
```

如使用自己的小程序账号，请替换 `appid`，并在后端 `.env` 中配置对应的 `WECHAT_APP_ID` 与 `WECHAT_APP_SECRET`。

---

## 5. 数据库说明

### 5.1 开发环境

默认使用 SQLite：

```env
DATABASE_URL=sqlite+aiosqlite:///./postgraduate.db
```

开发环境下后端启动时自动执行 `Base.metadata.create_all`，补齐历史字段，创建开发管理员、角色、权限等。

### 5.2 生产环境

生产使用 PostgreSQL 15：

```env
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgraduate
```

注意事项：

- `APP_ENV=production` 时不会自动建表，必须通过 Alembic 迁移。
- 生产环境还需 Redis 7（必需：缓存、番茄钟调度锁）。
- 启用向量检索需 PostgreSQL 安装 `pgvector` 扩展。
- 数据库迁移使用 Alembic，通过 `deploy/scripts/deploy.sh migrate` 显式执行。

### 5.3 主要数据表

代码中定义的核心表包括：

```text
users                         小程序用户
refresh_tokens                登录刷新令牌
questions                     正式题库
question_imports              导入暂存题目
question_versions             题目版本
subjects                      学科/科目
knowledge_points              知识点
question_knowledge_points     题目-知识点关联
wrong_questions               错题记录
practice_records              练习记录
review_schedules              复习计划
review_records                复习记录
pomodoro_sessions             番茄钟记录
admin_users                   后台管理员
roles                         角色
permissions                   权限
role_permissions              角色权限关联
audit_logs                    审计日志
admin_ai_settings             AI 设置
admin_ai_model_configs        AI 模型配置
admin_ai_configs              AI 功能配置
admin_vector_configs          向量检索配置
import_pipelines              导入流水线
import_pipeline_chunks        导入流水线分块
import_batch_jobs             批量图片导入任务
import_batch_job_items        批量图片导入明细
knowledge_edges               知识图谱边
recommendation_logs           推荐日志
recommendation_strategy_configs 推荐策略配置
recommendation_experiments    推荐实验
recommendation_metrics_daily  推荐每日指标
watermark_rules               水印规则
```

---

## 6. API 概览

### 6.1 公共端 API

公共端接口主要面向微信小程序：

```text
GET  /health
GET  /api/v1/health
GET  /api/v1/version

POST /api/v1/auth/login
POST /api/v1/auth/refresh
GET  /api/v1/users/me
PUT  /api/v1/users/me

GET  /api/v1/questions
POST /api/v1/questions
GET  /api/v1/questions/random
GET  /api/v1/questions/{question_id}
GET  /api/v1/questions/{question_id}/detail
GET  /api/v1/questions/{question_id}/similar

GET  /api/v1/practice/subjects
GET  /api/v1/practice/questions
POST /api/v1/practice/submit
POST /api/v1/practice/batch-submit
GET  /api/v1/practice/stats
GET  /api/v1/practice/records

GET  /api/v1/wrong-questions
GET  /api/v1/wrong-questions/stats
GET  /api/v1/wrong-questions/{wq_id}
PUT  /api/v1/wrong-questions/{wq_id}
PUT  /api/v1/wrong-questions/{wq_id}/quality

GET  /api/v1/review/today
POST /api/v1/review/schedule-submit
POST /api/v1/review/batch-submit
POST /api/v1/review/grade-submit
GET  /api/v1/review/history

GET  /api/v1/stats/overview
GET  /api/v1/stats/subjects
GET  /api/v1/stats/trends
GET  /api/v1/stats/dashboard
GET  /api/v1/stats/dashboard-v2
GET  /api/v1/stats/ai-diagnosis

POST /api/v1/ai/error-analysis
POST /api/v1/ai/study-advice
POST /api/v1/ai/explain
POST /api/v1/ai/recommend
POST /api/v1/ai/report
POST /api/v1/ai/analyze-mistake

GET  /api/v1/knowledge-points
GET  /api/v1/knowledge-points/tree
GET  /api/v1/knowledge/states
GET  /api/v1/knowledge/weak-points
GET  /api/v1/knowledge-path

POST /api/v1/pomodoro/start
POST /api/v1/pomodoro/{session_id}/complete
POST /api/v1/pomodoro/{session_id}/pause
POST /api/v1/pomodoro/{session_id}/resume
GET  /api/v1/pomodoro/active
GET  /api/v1/pomodoro/stats
GET  /api/v1/pomodoro/trends
GET  /api/v1/pomodoro/history

GET  /api/v1/import/template
GET  /api/v1/import/batches
POST /api/v1/import/pipeline/upload
GET  /api/v1/import/pipelines/{pipeline_id}
POST /api/v1/sync/import
```

### 6.2 管理端 API

管理端接口主要面向 `admin-frontend/`：

```text
POST /api/admin/v1/auth/login
POST /api/admin/v1/auth/refresh
POST /api/admin/v1/auth/logout
GET  /api/admin/v1/auth/me
POST /api/admin/v1/auth/change-password

GET  /api/admin/v1/dashboard/overview
GET  /api/admin/v1/dashboard/daily
GET  /api/admin/v1/dashboard/questions-stats

GET  /api/admin/v1/app-users
GET  /api/admin/v1/app-users/{user_id}
PATCH /api/admin/v1/app-users/{user_id}
POST /api/admin/v1/app-users/{user_id}/ban
POST /api/admin/v1/app-users/{user_id}/unban

GET  /api/admin/v1/admin-users
POST /api/admin/v1/admin-users
PATCH /api/admin/v1/admin-users/{admin_user_id}
DELETE /api/admin/v1/admin-users/{admin_user_id}
POST /api/admin/v1/admin-users/{admin_user_id}/force-logout
POST /api/admin/v1/admin-users/{admin_user_id}/reset-password

GET  /api/admin/v1/roles
GET  /api/admin/v1/permissions
PUT  /api/admin/v1/roles/{role_id}/permissions

GET  /api/admin/v1/questions
GET  /api/admin/v1/questions/{question_id}
PATCH /api/admin/v1/questions/{question_id}
DELETE /api/admin/v1/questions/{question_id}
PATCH /api/admin/v1/questions/{question_id}/toggle-active
GET  /api/admin/v1/questions/{question_id}/versions

POST /api/admin/v1/imports/upload
GET  /api/admin/v1/imports
GET  /api/admin/v1/imports/{batch_id}
POST /api/admin/v1/imports/{batch_id}/approve
POST /api/admin/v1/imports/{batch_id}/reject
POST /api/admin/v1/imports/{batch_id}/publish
POST /api/admin/v1/imports/text-parse
POST /api/admin/v1/imports/text-import
POST /api/admin/v1/imports/batch-image/upload
GET  /api/admin/v1/imports/batch-image/{job_id}
GET  /api/admin/v1/imports/batch-image/{job_id}/stream

GET  /api/admin/v1/ai-settings
PATCH /api/admin/v1/ai-settings
GET  /api/admin/v1/ai-settings/usage
GET  /api/admin/v1/ai-settings/stats
GET  /api/admin/v1/ai-models
POST /api/admin/v1/ai-models
PATCH /api/admin/v1/ai-models/{model_id}
DELETE /api/admin/v1/ai-models/{model_id}
POST /api/admin/v1/ai-models/test-connection
GET  /api/admin/v1/vector-config
PATCH /api/admin/v1/vector-config
POST /api/admin/v1/vector-config/test-embedding

GET  /api/admin/v1/audit-logs
GET  /api/admin/v1/audit-logs/{audit_log_id}
GET  /api/admin/v1/system/health
GET  /api/admin/v1/health/live
GET  /api/admin/v1/health/ready
```

---

## 7. 环境变量参考

### 核心

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `APP_ENV` | `development` | 运行环境。生产设为 `production` |
| `APP_SECRET` | — | **必填**。应用密钥，生产必须使用强随机字符串 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./postgraduate.db` | 数据库连接（生产使用 PostgreSQL） |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | 管理端跨域白名单 |
| `LOG_LEVEL` | `INFO` | 应用日志级别 |

### 微信

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `WECHAT_APP_ID` | — | **必填**。微信小程序 AppID |
| `WECHAT_APP_SECRET` | — | **必填**。微信小程序 AppSecret |
| `WECHAT_SUBSCRIBE_POMODORO_TEMPLATE_ID` | 空 | 番茄钟订阅消息模板 ID |
| `POMODORO_NOTIFY_ENABLED` | `false` | 番茄钟微信订阅提醒总开关 |
| `POMODORO_NOTIFY_PAGE` | `pages/pomodoro/pomodoro` | 番茄钟通知跳转页面 |
| `POMODORO_SCHEDULER_INTERVAL_SEC` | `60` | 调度器扫描间隔 |

### AI / LLM

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `DEEPSEEK_API_KEY` | — | DeepSeek / 兼容模型 API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API Base URL |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 默认模型名 |
| `AI_TIMEOUT` | `150` | AI 调用超时（秒） |
| `AI_DAILY_TOKEN_LIMIT` | `50000` | 单日 Token 上限 |
| `AI_CONFIG_ENCRYPT_KEY` | 空 | AI 模型配置加密密钥 |

### OCR

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `OCR_ENABLED` | `false` | 是否启用 OCR |
| `OCR_USE_GPU` | `false` | 是否使用 GPU 加速 |
| `OCR_LANGUAGE` | `ch` | OCR 语言 |
| `OCR_MAX_WORKERS` | `1` | OCR 并发线程数 |
| `MAX_OCR_PAGES` | `0` | 最大页数，0 不限 |

**OCR 模型配置**（通过后台 AI 设置页面配置，非环境变量）：

| 模型 | 类型 | 说明 |
|------|------|------|
| PP-OCRv4 | 本地引擎 | PaddleOCR 2.10.0，基于 `requirements-ocr.txt` 安装，用于基础文本识别 |
| PaddleOCR-VL 1.6 | 外部 API | `https://paddleocr.aistudio-app.com`，需配置 API Token；用于 OCR 纠错第一优先级和视觉回退 |

### Redis

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `REDIS_URL` | 空 | Redis 地址。生产必需（缓存、番茄钟调度锁） |

### 向量检索

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `VECTOR_ENABLED` | `false` | 是否启用向量检索 |
| `VECTOR_MODE` | `off` | 模式：`off` / `shadow` / `allowlist` / `all` |
| `EMBEDDING_API_KEY` | 空 | Embedding API Key |
| `EMBEDDING_BASE_URL` | 空 | Embedding Base URL |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型 |
| `EMBEDDING_DIM` | `1024` | Embedding 维度 |

### 生产部署

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `GUNICORN_WORKERS` | `2` | Gunicorn worker 数 |
| `POSTGRES_USER` | `pguser` | PostgreSQL 用户 |
| `POSTGRES_PASSWORD` | — | PostgreSQL 密码 |
| `POSTGRES_DB` | `postgraduate` | PostgreSQL 数据库名 |
| `CODE_DETECTOR_ENABLED` | `false` | 代码检测器灰度开关 |
| `SQL_ECHO` | `false` | 是否打印 SQL 日志 |
| `SQL_LOG_LEVEL` | `WARNING` | SQLAlchemy 日志级别 |
| `SLOW_QUERY_MS` | `500` | 慢查询阈值（毫秒） |
| `SENTRY_DSN` | 空 | Sentry DSN |
| `NEXT_PUBLIC_ADMIN_API_BASE_URL` | `/api/admin/v1` | 管理端 API 地址 |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | 静态资源公开访问基地址 |

---

## 8. 生产部署

### 8.1 架构

生产环境使用 Docker Compose 部署，包含 5 个服务：

| 服务 | 说明 |
|------|------|
| `app` | FastAPI + Gunicorn，源码构建 |
| `nginx` | nginx:1.25-alpine，HTTPS 反向代理 |
| `postgres` | PostgreSQL 15，持久卷 |
| `redis` | Redis 7，持久卷 |
| `admin` | Next.js 管理前端（仅内网 3000） |

网络拓扑：

```
用户 → nginx:443 (HTTPS) → app:8000 (HTTP)
                      → postgres:5432（仅 app 可访问）
                      → redis:6379（仅 app 可访问）
```

### 8.2 服务器信息

| 项目 | 值 |
|------|-----|
| 域名 | `xzshub.top` |
| 公网 IP | `8.163.56.109` |
| 部署目录 | `/opt/2240ai-v2` |
| CPU | 2 核 |
| 内存 | 1.8 GB |
| OS | Linux (Debian) |

### 8.3 部署流程

详细部署文档见 `docs/project/DEPLOY_PLAN.md`。

**日常更新：**

```bash
# 同步代码
rsync -az --exclude-from=".deployignore" \
  -e "ssh -i loginkey.pem -o BatchMode=yes" \
  ./ root@8.163.56.109:/opt/2240ai-v2/

# 更新后端
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh update"

# 更新管理端
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh update-admin"

# 查看状态
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh status"

# 显式执行数据库迁移
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh migrate"
```

**禁止的日常操作：**

- ❌ `docker compose down` — 会停止 postgres/redis/nginx，数据不丢失但会导致服务中断
- ❌ `docker compose build --no-cache` — 破坏 layer cache
- ❌ 从本地覆盖服务器 `backend/.env`、`cert/`、密钥

### 8.4 关键文件

| 路径 | 说明 |
|------|------|
| `deploy/docker-compose.prod.yml` | 生产 Docker Compose 入口 |
| `deploy/scripts/deploy.sh` | 生产部署脚本 |
| `deploy/nginx/nginx.conf` | Nginx 配置 |
| `deploy/scripts/backup.sh` | 备份脚本 |
| `deploy/Dockerfile.prod` | 生产多阶段 Dockerfile |

---

## 9. 常见问题

### 9.1 后端启动后访问接口报数据库错误

检查：

- 是否在 `backend/` 下启动，确保 `postgraduate.db` 创建在预期位置。
- `DATABASE_URL` 是否正确。
- 生产环境是否已执行 `deploy.sh migrate`。

### 9.2 管理端无法请求后端

检查：

- 后端是否运行在 `http://localhost:8000`。
- `NEXT_PUBLIC_ADMIN_API_BASE_URL` 是否正确。
- 后端 `CORS_ORIGINS` 是否包含管理端地址。
- 登录是否使用开发默认账号 `admin / admin`。

### 9.3 小程序真机调试接口不通

检查：

- 真机不能访问电脑的 `localhost`。
- 需要使用局域网 IP、内网穿透地址或 HTTPS 正式域名。
- 微信开发者工具是否关闭了"不校验合法域名"。
- 正式版必须在微信公众平台配置 request 合法域名。

### 9.4 OCR 或 AI 功能不可用

检查：

- `OCR_ENABLED` 是否开启，OCR 依赖是否安装（`requirements-ocr.txt`）。
- AI 模型是否已在后台配置并启用。
- `DEEPSEEK_API_KEY` 或后台模型配置中的 API Key 是否有效。
- 日志中是否出现 `AI_MODEL_NOT_CONFIGURED` 或模型连接失败信息。

### 9.5 向量检索不可用

检查：

- 是否使用 PostgreSQL（SQLite 不支持向量检索）。
- 是否安装 `pgvector` 扩展。
- `VECTOR_ENABLED` 与 `VECTOR_MODE` 是否开启。
- Embedding 配置是否与模型一致。

### 9.6 Docker 构建缓慢

PaddlePaddle（~500MB）等大包下载较慢。Dockerfile 配置了清华源（`pypi.tuna.tsinghua.edu.cn`），可将构建时间从数小时缩短至 2-3 分钟。如清华源不可用，备选阿里云或中科大镜像。

---

## 10. 当前文件包注意事项

1. 后端 `backend/requirements.txt` 已锁定版本，可直接用于生产构建。
2. `admin-frontend/` 包含完整的 `package.json`、`tsconfig.json`、`next.config.ts`，`npm install` 后即可启动。
3. 生产部署使用 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`，不建议手动使用 `gunicorn` 启动。
4. 开发环境 SQLite 与生产 PostgreSQL 在布尔类型、JSON 字段、自增 ID 等方面存在差异，迁移数据时需转换。
5. 开发默认管理员 `admin / admin` 仅适合本地调试，生产环境必须修改。

---

## 11. 推荐补充文件

```text
requirements-ocr.txt  ✅ 已有
alembic/              ✅ 已有
admin-frontend/package.json  ✅ 已有
Dockerfile            ✅ 已有（dev + prod）
docker-compose.yml    ✅ 已有（dev + prod）
.env.example          ✅ 已有
```

暂缺但推荐补充：

```text
docker-compose.yml    （根级入口，当前在 deploy/ 下）
```
