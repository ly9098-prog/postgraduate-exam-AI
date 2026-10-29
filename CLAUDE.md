# 22408AI 考研学习助手 — CLAUDE.md

@AGENTS.md

> Claude Code 专属工作流说明。项目基础、核心约束、部署陷阱、提交规范和检索路由规则均在 `AGENTS.md` 中维护，本文件不重复。

## 专项规则

`.claude/rules/` 下的专项规则按路径自动加载，仅触碰对应路径时生效：

- `deploy.md`：`deploy/`、`nginx.conf`、`docker-compose` 相关操作（含生产服务器信息与关键命令）
- `env-vars.md`：`backend/.env`、`docker-compose`、`config.py` 相关操作（环境变量参考）
- `docs-index.md`：`docs/` 或 `README.md` 相关路径（文档目录索引）
- `ocr-pipeline.md`：`app/features/` 下 OCR 相关文件（双 OCR 模型、纠错链路、排版路由策略）

## 子 Agent 工作流

- 新实现先查现有代码，按适用程度使用 planner / tdd-guide / code-reviewer 等子 agent。
- 审查发现的所有级别（含 P3）在提交前处理，不以外部文档的 CRITICAL/HIGH 分级为下限。
- 提交只关联当前任务；PR 描述包含完整 diff、测试计划和遗留 TODO。
- 详细工作流规则见 `docs/development/`：`development-workflow.md`、`coding-style.md`、`git-workflow.md`、`agents-and-commands.md`。
- 这些文档是外部参考，冲突时以 `AGENTS.md`、`docs/project/PROJECT_RULES.md`、`docs/COMMIT_RULES.md` 和代码为准；不引入其中与现状不符的 `version.md`、覆盖率门禁等要求。

## 本地开发

- 后端 venv 为 `backend/.venv`；`.venv-ocr-gpu-330` 是 OCR GPU 遗留目录，勿用于日常开发。
- 全量本地 pytest 包含依赖 PostgreSQL/Redis/外部 OCR 服务的用例，失败不代表代码有问题；CI 只跑 `ci.yml` 固定清单。
- 仓库根目录 `log.txt` 是临时日志，不要提交。
