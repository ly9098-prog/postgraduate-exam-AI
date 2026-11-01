# 基础系统 Prompt

> 状态：早期导入管线 Prompt，不是当前最高规则。以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 和代码为准。下文里的模型、JWT 天数和目录树可能已过时。

> 长期稳定的项目规则和开发规范。每次新会话开始时读取。

---

## 项目信息

- **项目**：2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL（生产）/ SQLite（开发）
- **AI**：httpx 直连 OpenAI-compatible 网关，模型与凭据由 Admin 配置于数据库（无 langchain）
- **认证**：微信 openid 唯一身份 + JWT（签名算法与有效期以当前代码/配置为准）
- **前端**：微信小程序原生

## 核心约束

1. **无传统账号系统** — 微信 openid 唯一标识，不存密码
2. **无纯 AI 自动入库** — 所有导入必须经过 `question_imports` + 人工确认
3. **Excel 导题优先** — 能走 Excel 就不要写解析代码
4. **AI 是辅助** — AI 不可用时系统正常运行

## 开发原则

- **项目已上线，进入稳定性治理阶段**：优先长期稳定性、可靠性、可维护性、可扩展性和生产安全，不以“能跑”作为交付标准
- **模块职责清晰、高内聚低耦合**：抽象和依赖引入须有真实复用或测试收益，避免过度设计与无价值重构
- **技术债务显式登记、按批次治理**：现行权威规则以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 与代码为准

## 项目目录

```
postgraduate-ai/
├── backend/app/
│   ├── api/v1/       # 路由层
│   ├── core/         # 配置/数据库/安全
│   ├── models/       # ORM (一个表一个文件)
│   ├── schemas/      # Pydantic
│   ├── services/     # 业务逻辑
│   ├── features/     # 导入管线
│   ├── ai/           # AI 客户端与运行时 Prompt
│   └── main.py
├── miniprogram/      # 小程序
├── docs/             # 文档（按类别分目录）
│   ├── architecture/
│   ├── backend/
│   ├── frontend/
│   ├── project/
│   └── ai/
├── prompts/          # Prompt 工程
│   ├── system/
│   ├── development/
│   ├── tasks/
│   └── templates/
└── deploy/           # 部署配置
```
