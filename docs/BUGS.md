## 本地后端启动日志警告

- 状态：已修复（2026-05-30）
- 现象：本地旧 SQLite 启动后端时，startup approved record migration 查询 `question_imports` 全字段，因本地库缺少新增审核字段 `reject_reason` 等列触发 `sqlite3.OperationalError`，并打印 `Startup migration failed (non-fatal)` warning。
- 原因：`_migrate_old_approved` 使用 `select(QuestionImport)` 隐式加载模型全字段，而该启动迁移只需要补发布相关字段。
- 修复：在 `backend/app/features/question_publish_service.py` 中为 `_migrate_old_approved` 两处查询增加 `load_only(...)`，仅加载迁移必需字段，避免访问旧 SQLite 中不存在的新增审核列。
- 验证：`PYTHONPATH=backend pytest backend/tests/test_services/test_question_publish_service.py -q`，结果 `23 passed`。
