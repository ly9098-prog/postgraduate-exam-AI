# Documentation Rules — 导入管线系统

> 状态：早期文档 Prompt，不是当前最高规则。已按 2026-11-02 上线后稳定性治理口径更新；以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md`、`docs/INDEX.md` 和代码为准。

## 文档同步矩阵

| 文档 | 更新时机 | 更新内容 |
|------|---------|---------|
| `docs/architecture/OCR_FLOW.md` | OCR 流程/接口变化 | 架构、质量门禁和降级边界 |
| `docs/ai/STANDARDIZATION_FLOW.md` | 标准化/题型映射变化 | 规则、兼容性和验收限制 |
| `docs/ai/AI_PIPELINE.md` | AI 管线/模型配置/Prompt 变化 | 模块说明、失败降级、配置来源和 Prompt 版本 |
| `docs/backend/DB_SCHEMA.md` | 模型/字段/迁移变化 | 当前 schema、迁移与兼容边界 |
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | 跨模块结构/运行时变化 | 当前架构、角色和未验证项 |
| `docs/project/PROJECT_RULES.md` | 长期规则/阶段定位变化 | 技术决策标准与业务边界 |
| `docs/backend/API_SPEC.md` | API/契约变化 | 端点、错误和兼容性说明 |
| `docs/frontend/UI_RULES.md` | 页面/交互规则变化 | 当前 UI 行为和回归入口 |
| `prompts/tasks/current_task.md` | 当前批次调度变化 | 状态、证据和下一步 |

## 文档更新规范

- 每个任务/批次说明末尾标注"需更新文档"清单
- 文档更新与代码变更在同一 PR/提交中
- 文档使用中文撰写，中英文混排保持可读性
- 只更新与本次变更相关的文档，不机械刷新无关日期或历史结论

## 不需要更新的文档

- 与本次变更无关、且当前结论未被影响的文档
- 历史审计报告和已封卷记录保持原文，不把历史事实改写成当前承诺
- 代码注释：仅在复杂边界或非显然决策处补充，不用注释复述代码

## 文档格式

- 使用 Markdown
- 内容更新时保留原有文件结构，只修改对应章节
- 新增模块在目录树中同步更新
- 文档只记录已实现或已验证事实；未实现/未验证内容明确标注
- 涉及 API、数据库、OCR/AI、运行时 Prompt、前端规则或部署变化时，同步 `docs/INDEX.md` 指向的对应权威文档
