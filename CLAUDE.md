# 22408AI 考研学习助手 — CLAUDE.md

> 项目硬性约束与常用命令。专项规则在 `.claude/rules/`（OCR 流水线、部署、环境变量、文档索引，按路径自动加载）；详细文档见 `/docs/`。

## 项目基础

- 考研智能刷题微信小程序（数学二 / 408 / 英语）
- 后端 FastAPI 单体（Route → Service → Model 三层，不分微服务），PostgreSQL（生产）/ SQLite（开发）+ Redis（生产必需）
- AI：OpenAI-compatible 网关（Qwen / GLM 等，模型由 Admin API 配置），httpx 直连，无 langchain/llamaindex
- 前端：微信小程序原生 + Next.js 管理端；部署 Docker Compose（app + nginx + postgres + redis + admin）

## 核心约束

- 微信 openid 唯一用户身份，不存密码；Admin 使用独立用户名与 JWT 域
- 无纯 AI 自动入库：所有导入必须经过 `question_imports` + 人工确认
- AI 是辅助：不可用时不影响核心刷题
- OCR 纠错链路固定为 `PaddleOCR-VL → LLM 纠错（Qwen/GLM）→ rule fallback`，不可绕过质量门禁
- **IMPORTANT**：跨环境数据同步必须用 `sync_uuid` 匹配记录，严禁按 numeric id 直接修改生产库（本地与生产 id 已发散）
- `knowledge_points` 是科目归属的权威来源；`admin_ai_model_configs` 为软删除，模型 ID 必须保持稳定

## 开发理念

- 先实现功能，再优化架构；能跑就比什么都强
- 不提前抽象，不主动加新依赖

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

## 部署与 CI 陷阱

- `deploy.sh migrate` 在旧 app 容器内执行：新增迁移须先 build 新镜像，再 `docker compose run --rm app alembic upgrade head` 应用
- `nginx.conf` 为文件级 bind mount：rsync 换 inode 后不生效，须 `--force-recreate`
- CI 架构测试使用 `.github/workflows/ci.yml` 中的固定文件清单：移动、重命名或新增测试文件后必须同步该清单

## 提交规范

Git 提交必须遵守 `/docs/COMMIT_RULES.md`。要点：Conventional Commits 格式；严禁自动添加任何 AI（Claude/Anthropic 等）的 `Co-Authored-By` 或其他 attribution trailer；不执行未经授权的 force push / 历史重写；不提交 secrets。

## 代码查询

优先使用 `codebase-memory` 知识图谱工具而非 grep/glob 进行代码搜索，减少文件读取次数。

## 本地开发

- 后端 venv 为 `backend/.venv`；`.venv-ocr-gpu-330` 是 OCR GPU 遗留目录，勿用于日常开发
- 全量本地 pytest 包含依赖 PostgreSQL/Redis/外部 OCR 服务的用例，失败不代表代码有问题；CI 只跑 `ci.yml` 固定清单
- 仓库根目录 `log.txt` 是临时日志，不要提交
