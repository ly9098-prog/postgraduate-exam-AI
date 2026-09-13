# 22408AI 考研学习助手 — CLAUDE.md

> 项目元信息。详细规则分散在 `/docs/` 和 `/prompts/` 中。

---

## 项目基础

- **名称**：22408AI — 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL（生产）/ SQLite（开发）+ Redis（生产必需）
- **AI**：DeepSeek API + PaddleOCR-VL 1.6 外部 API（httpx 直连，无 langchain/llamaindex）
- **OCR 模型**：本地 PP-OCRv4（PaddleOCR 2.10.0）+ 外部 PaddleOCR-VL 1.6
- **认证**：微信 openid 唯一身份 + JWT（HS256，7天有效期）
- **前端**：微信小程序原生 + Next.js 16 后台管理端
- **部署**：Docker Compose（5 服务：app + nginx + postgres + redis + admin）

## 核心约束

- 无传统账号系统（微信 openid 唯一标识，不存密码）
- 无纯 AI 自动入库（所有导入必须经过 `question_imports` + 人工确认）
- AI 是辅助（不可用时不影响核心刷题）
- OCR 纠错链路固定为 `PaddleOCR-VL → DeepSeek AI → rule fallback`，不可绕过质量门禁

## 开发理念

- **先实现功能，再优化架构**
- **能跑就比什么都强**
- **不提前抽象，不主动加新依赖**

## 快速参考

```bash
# 启动后端（开发）
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 启动管理端（开发）
cd admin-frontend && npm run dev

# 生产部署
rsync -az --exclude-from=".deployignore" -e "ssh -i Linux_connect.pem" ./ root@101.33.231.186:/opt/22408-ai/
ssh root@101.33.231.186 "cd /opt/22408-ai && bash deploy/scripts/deploy.sh update"

# 数据库迁移（生产）
ssh root@101.33.231.186 "cd /opt/22408-ai && bash deploy/scripts/deploy.sh migrate"
```

## 提交规范

Git 提交必须遵守 `/docs/COMMIT_RULES.md`。要点：Conventional Commits 格式；严禁自动添加任何 AI（Claude/Anthropic 等）的 `Co-Authored-By` 或其他 attribution trailer；不执行未经授权的 force push / 历史重写；不提交 secrets。

## 代码查询

优先使用 `codebase-memory` 知识图谱工具而非 grep/glob 进行代码搜索，减少文件读取次数。
