# 任务 Prompt

任务入口与历史任务书并存。当前活动重构按 `context.md` 和 `current_task.md` 接续；其他历史任务书不自动构成执行指令。

| 目录 | 内容 |
|------|------|
| `current_task.md` / `context.md` / `refactor_workflow.md` | 活动全栈重构的任务入口、接续摘要和执行工作流 |
| `current_task/` | 有限领域收口账本、原计划与历史记录分卷；每份历史文件最多100批次，容量索引见 `current_task.md` |
| `next_task.md` / `fix_task.md` | 历史任务书，按文件自身状态和当前授权判断，不自动施工 |
| `reference/` | 仍被文档引用的结构说明，例如 segment schema |
| `backlog/` | 历史任务书。每个文件开头标明不要施工；不代表待办，也不要按正文改代码 |
| `done/` | 已结束的任务书和审计记录 |
| `archive/repair-briefs/` | 早期全仓修复任务书（原 `on_repair/`） |
| `upgrade/` | 2026-09-07 的 408 总控计划，不是自动施工单 |
| `OCR_fix/` | OCR 整改分阶段任务，`phase_5.md` 修正了原来的文件名拼写 |
| `PDF_import/` | 各科 PDF 导入任务 |
| `fast_fill_answer/` | 按科目整理的答案批次，不是系统规则 |
| `questions_import/` | 题目答案批次 |
| `math_chart/` | 公式函数图目录。现行文本是 `*_v2.1.md`，更早版本在 `previous/` |
| `mini_ui_fix/` | 小程序 UI 任务。`past/`、`past_1/` 是旧轮次 |
| `practice_no_repeat/` | 练习去重方案 |

代码若写 `ocr_book_pdf_non_question_filter_plan.md`，正文在 `done/done-ocr_book_pdf_non_question_filter_plan.md`。
