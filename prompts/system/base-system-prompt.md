# 基础系统 Prompt

> 状态：早期导入管线 Prompt，不是当前最高规则。以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 和代码为准。下文里的模型、JWT 天数和目录树可能已过时。

> 长期稳定的项目规则和开发规范。每次新会话开始时读取。

---

## 项目信息

- **项目**：2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL（生产）/ SQLite（开发）
- **AI**：DeepSeek API（httpx 直连，无 langchain）
- **认证**：微信 openid 唯一身份 + JWT（HS256，7天有效期）
- **前端**：微信小程序原生

## 核心约束

1. **无传统账号系统** — 微信 openid 唯一标识，不存密码
2. **无纯 AI 自动入库** — 所有导入必须经过 `question_imports` + 人工确认
3. **Excel 导题优先** — 能走 Excel 就不要写解析代码
4. **AI 是辅助** — AI 不可用时系统正常运行

## 开发原则

- **先实现功能，再优化架构**
- **能跑就比什么都强**
- **三个重复再考虑抽函数，六个重复再考虑抽类**

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
│   ├── ai/           # DeepSeek 集成
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
