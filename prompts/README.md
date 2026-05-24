# Prompts 目录

> 2240AI 项目 Prompt 工程系统 — 面向 Claude Code 的长期可维护 Prompt 体系。

---

## 目录结构

```
/prompts
├── README.md                   # 本文件，Prompt 系统索引
├── system/                     # 系统级规则（长期稳定，每次任务前读取）
│   ├── base-system-prompt.md   # 基础系统 Prompt：项目规则/开发规范/AI行为
│   ├── task-execution.md       # 任务执行规范：如何拆任务/写代码/测试
│   ├── coding-rules.md         # 编码规则：风格/模块化/可测试性
│   └── debug-rules.md          # 调试/测试规则
├── development/                # 阶段开发 Prompt（当前开发任务）
│   ├── standardization.md      # 导入管线主规划
│   ├── stage1_text_normalizer.md  # 文本标准化
│   ├── stage2_structure_analysis.md
│   ├── stage3_question_splitter.md
│   ├── stage4_answer_matcher.md
│   ├── stage5_question_normalizer.md
│   ├── stage6_ai_repair.md
│   ├── stage7_review_system.md
│   ├── stage8_pipeline_integration.md
│   └── stage9_ocr_enhancement.md
├── tasks/                      # 单任务 Prompt（一次性任务）
│   └── current-task.md         # 当前正在执行的任务
└── templates/                  # Prompt 模板
    ├── feature-template.md     # 新功能开发模板
    ├── bugfix-template.md      # Bug 修复模板
    └── refactor-template.md    # 重构模板
```

---

## 读取策略

| Prompt | 读取时机 | 是否必须 |
|--------|---------|---------|
| `system/base-system-prompt.md` | 每次新会话开始 | 是 |
| `system/task-execution.md` | 每次新会话开始 | 是 |
| `system/coding-rules.md` | 开始编码前 | 是 |
| `system/debug-rules.md` | 调试阶段 | 按需 |
| `development/*.md` | 当前开发阶段 | 按需 |
| `tasks/current-task.md` | 每次任务开始 | 是 |
| 其他 | 按需读取 | 否 |

---

## Prompt 分层

1. **系统层**（`system/`）：长期稳定，不随开发阶段变化
2. **开发层**（`development/`）：当前阶段的开发任务，完成即归档
3. **任务层**（`tasks/`）：一次性具体任务，完成即更新或删除

## 关联文档

- `/docs/architecture/`：系统架构参考
- `/docs/backend/`：API/DB 参考
- `/docs/frontend/`：UI/组件参考
- `/docs/project/`：项目规则/路线图
- `/docs/ai/`：AI/OCR 参考
