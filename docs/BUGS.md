# 已知问题

> 更新：2026-05-30

当前 Level 1 题目完全重复检测、启动 schema repair、Alembic migration、后端回归与收尾评估已完成；未保留可复现阻断级 bug。

# 后续可选增强

- 历史正式题库中缺失 `question_hash` 的题目可后续通过非破坏性维护命令回填：仅填充空 hash，分批提交，可 dry-run，可重复运行，不覆盖、不删除、不合并历史题。
- 前端如需展示疑似重复标记，应对接 `question_imports` 的 `duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id`、`question_hash`。
