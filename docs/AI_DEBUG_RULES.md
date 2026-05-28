# AI Debug Rules

## Debug Gate

任何 BUG 禁止直接修复。进入修复前必须完成根因报告，并将阶段推进到 `ROOT_CAUSE_CONFIRMED` 或 `FIX_APPROVED`。

调试阶段状态：

- `INVESTIGATING`
- `ROOT_CAUSE_CONFIRMED`
- `FIX_APPROVED`
- `FIX_IMPLEMENTED`
- `VERIFIED`

## ROOT_CAUSE_REPORT

每个 BUG 必须建立 `/docs/debug/BUG_xxx/`，至少包含：

- `reproduction.md`
- `trace_analysis.md`
- `state_flow.md`
- `render_flow.md`
- `root_cause.md`
- `fix_plan.md`

## 强制流程

1. 定位问题层。
2. 分析数据流。
3. 分析 render 次数。
4. 分析 state 变化。
5. 输出 `ROOT_CAUSE`。
6. 审计根因。
7. 制定最小修复计划。
8. 严格按计划修复。
9. 验证 trace、render、state 与回归风险。

## 禁止事项

- 猜测性修复
- 顺手重构
- 扩散修改
- 多模块同时修改
- 全局替换
- 未定位根因直接 patch

## 连续失败规则

连续 3 轮未修复时，必须停止继续 patch，回到定位阶段重新确认第一污染层和第一异常层。

## Single Bug Isolation

每次只能处理一个 BUG。禁止顺手修其他问题，禁止把多个独立问题合并到同一次修复。

## Minimal Patch Policy

只能修改与已确认根因直接相关的代码。不得顺手优化、改命名、调整架构或清理无关代码。

## 协同角色

- GPT5.5：根因分析、链路分析、Debug 方案、状态流分析。
- Sonnet：小范围实现、局部修复、UI 层小修复。
- Opus：Root Cause 审计、Fix Plan 审计、风险审计。
- Claude Code：严格执行 Fix Plan、最小范围修改、文档同步。
