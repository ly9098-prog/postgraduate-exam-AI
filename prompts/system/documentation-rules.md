# Documentation Rules — 导入管线系统

> 状态：早期导入管线 Prompt，不是当前最高规则。以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 和代码为准。下文里的模型、JWT 天数和目录树可能已过时。

## 每阶段完成后必须更新的文档

| 文档 | 更新时机 | 更新内容 |
|------|---------|---------|
| `docs/architecture/OCR_FLOW.md` | stage1/9 完成后 | 文本标准化层说明、OCR 架构变更 |
| `docs/ai/STANDARDIZATION_FLOW.md` | stage5 完成后 | 标准化规则变更、题型映射变更 |
| `docs/ai/AI_PIPELINE.md` | 每个 stage 完成后 | 新增对应模块说明 |
| `docs/backend/DB_SCHEMA.md` | stage7 完成后 | question_imports 字段变更 |
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | stage8 完成后 | 新增 features/ 目录结构、管线说明 |
| `docs/project/PROJECT_RULES.md` | 任何阶段 | 目录结构变更、技术栈变更、管线阶段说明 |
| `docs/backend/API_SPEC.md` | stage4/5/7/8 完成后 | 新增模块、审核接口说明 |
| `docs/frontend/UI_RULES.md` | stage7 完成后 | 新增审核页面交互规则 |
| `prompts/tasks/current_task.md` | 每阶段开始前 | 更新当前任务描述 |

## 文档更新规范

- 每个 stage prompt 末尾标注"需更新文档"清单
- 文档更新与代码变更在同一 PR/提交中
- 文档使用中文撰写，中英文混排保持可读性
- 不改 README（README 面向终端用户，与导入管线无关）

## 不需要更新的文档

- 与导入管线无关的文档（`REVIEW_ALGORITHM.md`、`CHANGELOG.md`、`MVP_SCOPE.md` 等）
- 代码注释（代码自解释，不额外写文档说明代码逻辑）

## 文档格式

- 使用 Markdown
- 内容更新时保留原有文件结构，只修改对应章节
- 新增模块在目录树中同步更新
