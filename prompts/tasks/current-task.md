当前任务（2026-05-30）：Level 1 题目完全重复检测已完成，收尾评估已完成。

已完成：

- 标准化题干、选项、答案后生成 `question_hash`（MD5，32 位）。
- `questions` 新增 `question_hash`；`question_imports` 新增 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id`。
- 导入阶段只标记重复，不删除、不拒绝导入。
- 发布 / 审核通过阶段按 `subject + question_hash` 做最终重复拦截，命中时阻止重复题写入正式题库。
- 审核队列、导入批次详情和 admin import schema 已返回重复检测字段。
- 启动 schema repair 与 Alembic migration 已补齐。
- 后端回归通过：`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend pytest /home/lmh/projects/postgraduate-ai/backend/tests -q --tb=short -x`，699 passed。
- 历史题目 `question_hash` 回填方案已评估：不放入启动 repair，不放入复杂 Alembic 数据迁移；建议后续用幂等的 admin/maintenance 脚本或服务手动执行，只填充空 `question_hash`，不覆盖、不删除、不合并历史题。
- 前端展示缺口已评估：管理端审核页 / 题库页当前未消费重复检测字段；如要增强展示，应对接 `duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id`、`question_hash`。

# 后续可选增强

- 实现一个可 dry-run、分批 commit、可重复运行的历史 `question_hash` 回填维护命令。
- 在 admin-frontend 审核工作台和题库详情中展示疑似重复 badge、重复来源和 hash 摘要。
