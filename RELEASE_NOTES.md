# Release Notes

## 版本：RC-1.0（SM-2 单一路径重构 + 稳定性修复）

发布日期：2026-06-27

---

## 重大变更

### SM-2 单一路径重构

本次发布最核心的变更是将复习调度系统从"双数据源"重构为"单数据源"架构。

**变更前**：SM-2 算法的状态字段（efactor、interval、repetitions、next_review_date、quality）同时存在于 `wrong_questions` 和 `review_schedules` 两张表中，导致数据不一致风险高、维护成本大。

**变更后**：`review_schedules` 表成为 SM-2 调度的唯一数据源。`wrong_questions` 表仅保留错题分析相关字段（wrong_answer、error_type、ai_analysis、review_count、last_review_at、mastered），不再存储任何 SM-2 调度状态。

**单向同步**：ReviewSchedule → WrongQuestion 方向仅同步 `last_review_at` 和 `mastered` 两个字段，用于错题本的展示和统计，不参与调度决策。

### 自动评分映射调整

自动批改的评分映射从 correct=5 / wrong=0 改为 correct=4 / wrong=1。这使 SM-2 的 ease_factor 更新更温和：正确回答不再直接给最大奖励，错误回答也不再给最大惩罚。

### admin_auth bcrypt 兼容修复

bcrypt 4.1+ 与 passlib 1.7.4 存在兼容性问题（`detect_wrap_bug` 使用 73 字节测试密码触发 ValueError）。修复方案：

- `requirements.txt` 锁定 `bcrypt>=4.0.1,<4.1`
- `admin_security.py` 增加 `BCRYPT_MAX_BYTES=72` 字节校验，在 hash/verify 前检查 UTF-8 字节长度
- admin_auth API 区分密码过长（400）和密码错误（401）

---

## 数据库变更

### 迁移链

新增迁移 `d1e2f3a4b5c6`：从 `wrong_questions` 表删除 5 个 SM-2 字段（efactor、interval、repetitions、next_review_date、quality）。

迁移 `c07a8112c2f2`：防御性删除 `batch_job_trace_events` 表的 `(job_id, seq)` 唯一约束（该约束在建表迁移中从未创建，此迁移为安全兜底）。

### 迁移注意事项

1. **迁移分叉已修复**：`d1e2f3a4b5c6` 的 `down_revision` 已指向 `a5eac9aa37fa`，确保 `alembic heads` 只有一个 head。
2. **索引引用已删除列**：迁移 `e5b62f3a4c7d` 创建的索引 `idx_wrong_questions_user_mastered_date` 引用了 `next_review_date` 列。在 `d1e2f3a4b5c6` 的 upgrade 中需先 drop 该索引，downgrade 中再重建。
3. **执行顺序**：`alembic upgrade head` 会自动按迁移链顺序执行，无需手动干预。

### 历史数据修复

如果生产数据库中 `wrong_questions` 表已有数据，需运行历史数据修复脚本将 SM-2 状态迁移到 `review_schedules` 表。脚本位于 `backend/scripts/repair_review_schedule.py`。

建议先 dry-run 检查：

```bash
python scripts/repair_review_schedule.py --dry-run
```

确认无误后再执行：

```bash
python scripts/repair_review_schedule.py --apply
```

---

## 性能优化

### 批量导入 flush 优化

`submit_to_review` 函数从逐条 flush 改为分批 flush+commit。每 50 道题执行一次 flush+commit+expunge，显著降低数据库交互次数和内存占用。

修复了 flush 前读取 `qi.id`（此时为 None）的风险：将 `seen_hashes` 填充和 `items` 列表构建移至 flush 之后执行。同批次重复检测使用独立的 `seen_hash_set`（set）进行即时判断，`duplicate_of_import_id` 在 flush 后回填。

### Trace 事件轮询优化

`poll_trace_events` 从基于 `seq` 改为基于 `id`（自增主键），避免唯一约束冲突。响应中同时返回 `id` 和 `seq` 字段保持向后兼容。

---

## 测试修复

### code_structure_reconstructor

修复了 `_fix_ocr_operators` 中的多个正则表达式问题：

- `_BROKEN_OP_PATTERNS` 不再要求操作符两侧有空格
- 新增 `+=`、`-=`、`/=`、%=` 操作符的修复规则
- 嵌套 for 循环拆分正则修正
- `reconstruct_code(None)` 返回空字符串而非 None

### OCR 测试策略

- numpy 缺失时跳过 `test_ocr_service.py` 中的图像预处理测试（numpy 属于 OCR 可选依赖）
- PaddleOCR-VL 未配置时跳过 OCR 回归测试
- 详细策略见 `docs/project/TESTING_POLICY.md`（注：文件在 2026-06-28 整理时丢失，需重新创建）

---

## 已知限制

1. **OCR 回归测试**：普通 CI 中约 6 个测试会因缺少 OCR 环境而 skip，需在 OCR 完整环境中单独验证。详见 `docs/project/TESTING_POLICY.md`（注：文件在 2026-06-28 整理时丢失，需重新创建）。
2. **SQLite 测试**：CI 使用 SQLite 内存模式，与生产 PostgreSQL 在并发行为和类型处理上有差异。
3. **bcrypt 版本**：锁定在 4.0.x，升级需同步验证 passlib 兼容性。
4. **历史数据**：如果生产环境有旧 `wrong_questions` 数据，必须在升级后运行修复脚本。

---

## 文件变更摘要

| 类别 | 文件 | 变更说明 |
|---|---|---|
| 模型 | `app/models/import_batch_job.py` | 移除 BatchJobTraceEvent 的 (job_id, seq) 唯一约束 |
| 服务 | `app/features/review_service.py` | flush 前不读 qi.id；批量 flush 优化 |
| 服务 | `app/features/batch_image_import_service.py` | poll_trace_events 改用 since_id |
| 安全 | `app/core/admin_security.py` | bcrypt 字节长度校验 |
| 迁移 | `alembic/versions/d1e2f3a4b5c6_*.py` | 删除 wrong_questions 的 SM-2 字段 |
| 迁移 | `alembic/versions/c07a8112c2f2_*.py` | 防御性删除 trace_events 唯一约束 |
| 测试 | `tests/test_features/test_batch_import_optimizations.py` | 适配新 flush 逻辑 |
| 测试 | `tests/test_services/test_ocr_service.py` | numpy 缺失时 skip |
| 测试 | `tests/ocr_regression/runner.py` | VL 未配置时 skip |
| 文档 | `docs/project/TESTING_POLICY.md` | 测试分级策略（文件在 2026-06-28 整理时丢失，需重新创建） |
| 文档 | `RELEASE_NOTES.md` | 本文件 |
| 文档 | `docs/project/RC_RELEASE_CHECKLIST.md` | 发布检查清单（文件在 2026-06-28 整理时丢失，需重新创建） |
| 文档 | `docs/project/SMOKE_TEST_CHECKLIST.md` | 冒烟测试清单（文件在 2026-06-28 整理时丢失，需重新创建） |
