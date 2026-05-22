# Project Rules

> 2240AI — 考研智能刷题小程序项目规范。**长期稳定规则，非阶段性任务。**

---

## 项目信息

- **项目**：2240AI（MemoGrad）— 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL/SQLite + Redis | 微信小程序
- **AI**：DeepSeek API（httpx 直连，无 langchain/llamaindex）
- **认证**：微信 openid 唯一身份 + JWT 会话（HS256，7 天有效期）

---

## 明确不做什么

- ❌ OCR 识别手写题 / 复杂 OCR pipeline
- ❌ LangChain / Agent / 多模型编排
- ❌ 知识图谱 / 复杂推荐系统
- ❌ 微服务 / Kubernetes
- ❌ 多租户 / 权限体系
- ❌ 社区 / 论坛 / 排行榜
- ❌ 实时协同 / WebSocket
- ❌ 账号密码登录 / 邮箱注册 / 密码重置
- ❌ 多方式登录体系（仅微信 openid）
- ❌ 在线公式编辑器（LaTeX 手动输入）

---

## 技术栈明细

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | 异步 Python Web 框架 |
| ORM | SQLAlchemy 2.0 | 异步声明式映射 |
| 数据库 | PostgreSQL 15+（生产）/ SQLite（开发） | asyncpg / aiosqlite |
| 缓存 | Redis（可选） | 当前未集成 |
| AI | DeepSeek API | httpx 直连，temperature=0.3 |
| 认证 | JWT (HS256) | 7 天有效期 |
| 前端 | 微信小程序 | 原生框架 |
| 部署 | Docker Compose + Nginx | Gunicorn + Uvicorn Workers |

---

## 目录结构

```
postgraduate-ai/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/             # 路由层（参数校验 + 响应组装）
│   │   ├── core/               # 配置 / 数据库 / 安全
│   │   ├── models/             # SQLAlchemy 模型（一个文件一个表）
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── services/           # 业务逻辑层
│   │   ├── ai/                 # AI 模块（client / prompts / token_counter / fallback）
│   │   ├── utils/              # 工具函数
│   │   └── main.py             # 应用入口
│   ├── rag/                    # 代码级 RAG 检索（关键词匹配，无向量库）
│   ├── alembic/                # 数据库迁移
│   ├── tests/                  # 测试
│   └── requirements.txt
├── miniprogram/                # 微信小程序
│   ├── pages/                  # 页面
│   ├── components/             # 公共组件
│   ├── utils/                  # 工具（api.js / auth.js / storage.js）
│   └── styles/                 # 全局样式（tokens.wxss / components.wxss）
├── deploy/                     # 部署配置
├── scripts/                    # 数据脚本
└── docs/                       # 项目文档
```

---

## 开发规范

### Python

- Python 3.11+
- 类型注解全覆盖
- 使用 `ruff` lint + format
- 不写 service 抽象类/接口
- 一个文件不超过 300 行，一个函数不超过 50 行
- model 不使用 `__repr__` / 自定义 Query
- 不用 `__init__.py` 做重导出

### FastAPI 路由

- 路由只做参数校验和响应组装，业务下沉到 services/
- 不引入三层以上依赖注入
- 响应格式：`{code: 0, message: "success", data: {}}`
- 分页格式：`{items, total, page, pageSize, totalPages}`

### 数据库

- 不提前建索引（等慢查询再建）
- 不写 migration 回滚脚本
- 不超过 3 表 join，否则反范式或 service 层拼接
- `content` 使用 JSONB：`{text, images, latex}`
- `knowledge_points` 用 PG 数组 + GIN 索引

### AI

- 不引入 langchain / llamaindex
- 直接 httpx 调 DeepSeek API
- Prompt 直接写在 `prompts.py`，不引入管理平台
- 失败降级优先于重试
- AI 是辅助功能，不影响核心刷题流程

---

## 提交规范

```
<type>: <简短描述>

<body (可选)>
```

type: `feat` / `fix` / `refactor` / `perf` / `docs` / `chore`

---

## 核心约束

1. **无传统账号系统** — 微信 openid 是用户唯一标识
2. **无纯 AI 自动入库** — 所有导入题目必须经过 `question_imports` 暂存区 + 人工确认
3. **Excel 导题优先** — 能走 Excel 就不要写解析代码
4. **SM-2 字段在 WrongQuestion 表上** — 不拆分独立调度表
5. **后端不管理密码** — 所有身份验证依赖微信
