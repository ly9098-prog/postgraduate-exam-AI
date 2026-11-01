---
tags: [concept, development, ruoyi-codex, 工作流]
title: 开发流程 ruoyi-codex
type: concept
---

> 本仓库外部参考文档；原文使用 ruoyi-codex 示例，冲突时以根目录 `AGENTS.md`、`docs/COMMIT_RULES.md` 与本项目代码为准。
> 参考依据：[Superpowers](https://github.com/obra/superpowers) 的 TDD / 系统化调试 / 完成验证 / 计划执行模式，[Spec Kit](https://github.com/github/spec-kit) 的规格-任务-验收分层。

# 开发流程 — ruoyi-codex 项目

> 基于通用开发工作流的 ruoyi-codex 项目实施流程
> 原始参考：[[wiki/concepts/development/git-workflow|Git 工作流]]

---

## 项目阶段与技术决策标准

> 2026-11-02 起，项目处于上线后的稳定性治理阶段。本节与根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 一致。

- 优先长期稳定性、可靠性、可维护性、可扩展性和生产安全；“功能能运行”不是设计或交付标准。
- 模块职责清晰、高内聚低耦合、依赖边界明确；抽象须有真实复用或测试收益，避免过度设计和无实际价值的重构。
- 新增依赖先评估安全、许可、维护成本、兼容性与回退方式，经确认后引入；不为省事绕过既有边界。
- 技术债务显式登记、按批次治理；不做无出口拆分，不扩大现状缺陷；生产变更须单独授权。
- 涉及路由、模型、迁移、队列、OCR、AI 或安全边界的改动，按根目录 `AGENTS.md` 的测试要求补对应回归与真实环境验收计划。

## 特性实现流程

### 0. 需求澄清（Spec Kit: specify 阶段）

实现前必须确认三件事，缺一即先澄清再动手：

1. **要解决什么问题** — 用一段话复述需求，标注不确定处；不复述就动代码是猜测而非实现。
2. **怎么算完成** — 每条验收标准必须写成可执行验证（Given / When / Then 或具体命令 + 期望输出），不可验证的标准不算标准。
3. **改动影响面** — 列出预计新增/修改的文件和依赖的现有模块；无法定位影响面说明理解不足。

复杂度判断：单一文件小修可直接进入实现；涉及多模块、新依赖或架构取舍时，先走 Step 1 计划再实现。

### 1. 研究 & 复用

- **代码库检索优先**（本仓库使用 codebase-memory MCP，见根目录 `AGENTS.md` 检索路由规则）：实现前先确认现有代码是否已有可复用实现
- **库文档其次**：使用官方文档确认 API 行为
- **搜索可适配的实现**：开源项目中找到高度匹配的方案再考虑引入，禁止为简单问题引入新依赖；确需引入时先评估安全、许可、维护成本和回退方式

### 2. 先计划
- 使用 **planner** agent 创建实施计划（按任务性质存档于 `docs/planning/` 或当前任务目录）
- 每个任务必须包含：涉及文件（精确路径）、依赖关系、验证方法（命令 + 期望输出）
- 任务按依赖分层排序（Spec Kit: Setup → Foundational → User Story 分层）；无依赖的任务标注可并行
- 每个阶段以独立可验证的 checkpoint 收尾（"此时阶段 N 的验收标准全部通过且不破坏之前阶段"）

### 3. TDD 方法
- 使用 **tdd-guide** agent 或按 Superpowers RED→GREEN→REFACTOR 循环：
  1. **RED** — 写一个最小失败测试并运行，确认输出是预期失败（不是 import error）
  2. **GREEN** — 写最小实现让测试通过；不过测试就不进入下一步
  3. **REFACTOR** — 在测试保持通过的前提下清理实现
- **Iron Law**（Superpowers test-driven-development）：没有失败的测试就不写生产代码。先写了实现再补测试 = 重新开始。
- 例外：一次性原型、配置文件、纯文档——但需明确标注并说明理由
- 本仓库不强制 80% 覆盖率门禁（`CLAUDE.md` 已明确不引入），以行为覆盖为准：每个新行为至少一个测试

### 4. 代码审查
- 编写代码后立即使用 **code-reviewer** agent（多子 agent 模式）或 `codex review --uncommitted`（单会话模式）
- 审查发现的所有级别（含 P3）在提交前处理，不以 CRITICAL/HIGH 分级为下限（与 `CLAUDE.md` 子 agent 规则一致）
- 对审查反馈先验证再实现：不盲从——如果建议与代码库现状冲突，用技术理由回应而不是直接改

### 5. 提交 & 推送
- **完成验证**（Superpowers verification-before-completion）：
  - 声明"通过"前必须 fresh 运行验证命令并读完整输出；使用上一次运行结果、推测或"应该没问题"不算验证
  - 测试通过 = 测试命令输出 0 failures（不是"看起来正确"）；构建成功 = exit 0（不是日志没有报错字样）
  - 验证不通过时，报告实际状态和证据，不伪造通过
- 遵循常规提交格式（参见 Git 工作流）

---

## ruoyi-codex 专属规范

### 系统化调试（Superpowers: systematic-debugging 四阶段）

遇到 bug 或测试失败时，按顺序走完四阶段，未完成前一阶段不得提出修复：

1. **根因调查** — 读完整错误信息（不跳过）、稳定复现（不可复现就继续收集数据）、检查近期变更（`git diff`）、多组件系统先加诊断日志定位失败层（本仓库用 `docs/debug/DEBUG_SYSTEM.md` 的 TraceId 体系）
2. **模式分析** — 找同类可工作的代码做对照，列出差异，理解依赖
3. **假设验证** — 单一假设、最小变更、一次验证一个变量；假设不成立就回到 Phase 1
4. **实现修复** — 先写失败测试再修根因（不是修症状）；一次修一个根因，不顺手重构；修完验证不引入新失败

**连续 3 次修复尝试失败 = 停下质疑架构假设**，不要做第 4 次修复（Superpowers 系统化调试的铁律）。

已闭环的调试案例沉淀到 `docs/debug/DEBUG_HISTORY.md`。

### 状态记录

任务执行过程中，以下状态必须明确记录，不得默认为通过：

| 状态 | 记录方式 |
|------|----------|
| 通过 | 验证命令输出（复制关键行，如 `34 passed`） |
| 失败 | 失败输出 + 根因 + 修复计划 |
| 部分完成 | 已完成项 + 未完成项 + 阻塞原因 |
| 环境受阻 | 缺少的依赖/服务/凭据，不猜不绕 |
| 跳过 | 原因 + 是否需要后续补偿验证 |

未运行验证的声明用"未验证"标注；不得将推测、记忆中的旧结果或子 agent 汇报当作验证证据。

### 子 agent 分工

| Agent | 职责 |
|-------|------|
| backend-developer | Python 后端（FastAPI 路由/Service/Repository/HTTP 客户端/配置中心） |
| mini-program-developer | 微信小程序前端 |
| frontend-developer | 管理端前端（Vue / Next.js 等按项目技术栈） |
| dba | 关系型数据库设计/迁移/优化（SQLAlchemy + Alembic，MySQL / PostgreSQL 等） |
| project-manager | 需求分解/任务分配/进度跟踪 |
| code-reviewer | 代码审查 |
| build-error-resolver | 构建/依赖/类型错误修复 |

### 跨服务调用
- 必须通过统一的 API 客户端模块（`httpx.AsyncClient` 封装的服务接口）
- 禁止直接依赖调用

### 数据库访问
- 通过项目现有 SQLAlchemy 异步 ORM 和 Alembic 迁移管理数据库访问；不引入额外 MCP 数据库连接服务

### 版本记录
- 不维护 `version.md`（`CLAUDE.md` 已明确不引入该机制）；版本追踪使用 Git 提交历史 + `docs/CHANGELOG.md`

---

## 参考

- [[wiki/concepts/development/coding-style|编码规范]]
- [[wiki/concepts/development/git-workflow|Git 工作流]]
- [[projects/english/_README|ruoyi-codex 项目架构]]
- [Superpowers: test-driven-development](https://github.com/obra/superpowers/tree/main/skills/test-driven-development) — TDD Iron Law 和 RED→GREEN→REFACTOR
- [Superpowers: verification-before-completion](https://github.com/obra/superpowers/tree/main/skills/verification-before-completion) — 完成验证证据规则
- [Superpowers: systematic-debugging](https://github.com/obra/superpowers/tree/main/skills/systematic-debugging) — 四阶段根因调试
- [Spec Kit: tasks-template](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md) — 任务分层与并行标注
