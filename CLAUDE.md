# 2240AI 考研学习助手 — CLAUDE.md

> 项目元信息。详细规则分散在 `/docs/` 和 `/prompts/` 中。

---

## 项目基础

- **名称**：2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL（生产）/ SQLite（开发）
- **AI**：DeepSeek API（httpx 直连，无 langchain/llamaindex）
- **认证**：微信 openid 唯一身份 + JWT（HS256，7天有效期）
- **前端**：微信小程序原生

## 核心约束

- 无传统账号系统（微信 openid 唯一标识，不存密码）
- 无纯 AI 自动入库（所有导入必须经过 `question_imports` + 人工确认）
- AI 是辅助（不可用时不影响核心刷题）

## 开发理念

- **先实现功能，再优化架构**
- **能跑就比什么都强**
- **不提前抽象，不主动加新依赖**

## 环境变量

```bash
# 必填
APP_SECRET=
DATABASE_URL=
DEEPSEEK_API_KEY=
WECHAT_APP_ID=
WECHAT_APP_SECRET=

# 可选
OCR_ENABLED=false
REDIS_URL=
```

## 文档索引

| 位置 | 内容 |
|------|------|
| `/docs/architecture/` | 系统架构、OCR、记忆系统、复习算法 |
| `/docs/backend/` | API 端点、DB schema、存储设计 |
| `/docs/frontend/` | UI 规则、设计系统、组件规范 |
| `/docs/project/` | 项目规则、路线图、MVP、变更日志 |
| `/docs/ai/` | AI 管线、OCR 策略、标准化流程 |
| `/docs/achieve/` | 历史开发阶段归档 |
| `/prompts/` | 当前开发任务和系统 Prompt |
