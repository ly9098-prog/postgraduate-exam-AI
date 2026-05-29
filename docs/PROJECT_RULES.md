# Project Rules

> 2240AI — 考研智能刷题小程序项目规范。**长期稳定规则，非阶段性任务。**

- **更新时间**：2026-05-29
- **变更原因**：整合通用 LLM 编码防错行为准则，并与项目“先实现功能、保持简单、只改必要内容”的既有规范对齐。

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

## LLM 协作与编码防错准则

> 适用于使用 LLM Agent 参与开发、修复、重构或文档维护时。目标是减少过度实现、误改无关代码和不澄清就动手的问题；简单任务可按实际情况精简流程，但不得突破项目核心约束。

### 先想清楚再动手

- 不要默认猜测需求；实现前先说明关键假设。
- 如果存在多种理解，先列出差异和取舍，不要静默选择其中一种。
- 如果有更简单的实现路径，应主动说明；发现需求可能过度复杂时应适度提醒。
- 遇到不明确、互相冲突或无法验证的信息时，先指出困惑并提问，不要用代码掩盖不确定性。

### 简单优先

- 只写解决当前问题所需的最少代码，不做未被要求的功能扩展。
- 不为单次使用场景新增抽象层、配置项或“未来灵活性”。
- 不为实际不可能出现的分支堆叠防御式错误处理。
- 如果实现明显可以从复杂方案收敛为更短、更直接的方案，应优先重写为简单方案。
- 保持与项目理念一致：能跑、清晰、可验证，比提前架构优化更重要。

### 外科手术式修改

- 只改与用户请求直接相关的文件和行；每一处改动都应能追溯到本次目标。
- 不顺手优化相邻代码、注释、格式或命名。
- 不重构未损坏、未被要求修改的逻辑。
- 匹配现有代码和文档风格，即使个人偏好不同。
- 发现无关死代码或历史问题时，只在汇报中说明；除非被要求，不主动删除。
- 若本次改动造成未使用的 import、变量、函数或文档残留，应清理自己的改动产生的孤儿内容；不要清理既有无关残留。

### 目标驱动与验证闭环

- 将任务转换为可验证目标，而不是停留在“修一下”“让它能用”。
- 修 bug 时优先明确复现方式或失败证据，再确认修复后验证结果。
- 新增校验时，应覆盖无效输入和有效输入的预期行为；若无法自动化验证，应说明手动验证方式。
- 重构时应保证重构前后行为一致，并说明依赖的测试或检查。
- 多步骤任务先给出简短计划，每一步都要有对应验证方式。
- 成功标准：减少无关 diff、减少因过度复杂导致的返工，并让澄清问题发生在实现前而不是出错后。

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
