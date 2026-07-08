# 22408AI 考研学习助手 — CLAUDE.md

> 项目元信息。详细规则分散在 `/docs/` 和 `/prompts/` 中。

---

## 项目基础

- **名称**：2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）
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
rsync -az --exclude-from=".deployignore" -e "ssh -i loginkey.pem" ./ root@8.163.56.109:/opt/2240ai-v2/
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh update"

# 数据库迁移（生产）
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh migrate"
```

## 环境变量

```bash
# 必填
APP_SECRET=                    # 应用密钥
DATABASE_URL=                  # sqlite+aiosqlite:///./postgraduate.db（开发） / postgresql+asyncpg://...（生产）
DEEPSEEK_API_KEY=              # DeepSeek / 兼容模型 API Key
WECHAT_APP_ID=                 # 微信小程序 AppID
WECHAT_APP_SECRET=             # 微信小程序 AppSecret

# 可选
OCR_ENABLED=false              # 启用 OCR（需安装 requirements-ocr.txt）
REDIS_URL=                     # 生产必需（缓存、番茄钟调度锁）
AI_TIMEOUT=150                 # AI 调用超时（秒）
CORS_ORIGINS=["http://localhost:3000"]

# 生产常用
GUNICORN_WORKERS=2
POSTGRES_USER=pguser
POSTGRES_PASSWORD=
```

> PaddleOCR-VL 等 AI / OCR 模型配置通过后台 AI 设置页面管理，非环境变量。详细环境变量列表见 `README.md`。

## 文档索引

| 位置 | 内容 |
|------|------|
| `/docs/architecture/` | 系统架构、OCR、记忆系统、复习算法 |
| `/docs/backend/` | API 端点、DB schema、存储设计 |
| `/docs/frontend/` | UI 规则、设计系统、组件规范 |
| `/docs/project/` | 项目规则、路线图、MVP、变更日志 |
| `/docs/ai/` | AI 管线、OCR 策略、标准化流程 |
| `/docs/achieve/` | 历史开发阶段归档 |
| `/docs/project/DEPLOY_PLAN.md` | 生产部署方案（服务器信息、Docker Compose、迁移） |
| `/prompts/` | 当前开发任务和系统 Prompt |
| `README.md` | 完整项目说明与技术文档 |
