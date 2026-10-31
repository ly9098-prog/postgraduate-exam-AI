# Prompts 目录

一次性任务书和早期系统 Prompt。当前仓库规则以根目录 `AGENTS.md` 和 `docs/project/PROJECT_RULES.md` 为准，不要把本目录里的旧任务当成必须执行的步骤。

## 目录

```text
prompts/
├── README.md
├── system/           # 早期系统 Prompt。文件开头已标明不是当前最高规则
├── development/      # stage1–stage15 导入管线阶段任务书（历史）
├── templates/        # feature / bugfix / refactor 模板
└── tasks/            # 一次性任务，分区见 tasks/README.md
```

## 怎么用

| 需要 | 读 |
|------|----|
| 项目长期约束 | `AGENTS.md`、`docs/project/PROJECT_RULES.md` |
| 写新任务 | `templates/`，放进 `tasks/backlog/` |
| 看现在有没有指定任务 | `tasks/current_task.md` |
| 查某次旧任务怎么写的 | `tasks/done/`、`tasks/archive/`、各主题目录 |

`system/` 里仍有「只调 DeepSeek、JWT 7 天、每次会话必须读 current-task」这类旧句子。那些句子不要覆盖代码和 `docs/`。

## 这次整理留在原处的原因

- 答案批次、PDF 导入稿、UI 旧轮次数量大，只按目录归类，不改正文。
- `tasks/current_task.md` 保留为活动全栈重构入口，原计划与每卷最多100批次的历史记录在 `tasks/current_task/`；接续先读 `tasks/context.md` 和 `tasks/refactor_workflow.md`。`tasks/next_task.md`、`tasks/fix_task.md` 保留原路径，按各自状态和当前授权判断。
- 公式图目录只把 `v2.1` 留在 `math_chart/` 根上，更早的 `directory_*.md` 移到 `previous/`。
