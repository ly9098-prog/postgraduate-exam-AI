# Claude Code 下一阶段任务 Prompt：测试全绿、Merge 原子性、025 真修复

你正在修改本地项目：

```text
/home/lmh/projects/postgraduate-ai/backend
```

本阶段不是继续做表面修补，而是完成上一阶段遗留的系统闭环。

当前已知状态：

```text
Collection: 1437 tests collected
Full suite: 1399 passed, 4 failed, 4 xpassed, 30 xfailed
Regression:
- 025_bugs_case5_listinsert → xfailed
- 029_generalized_codelist → passed
```

当前已知剩余风险：

1. `test_pipeline_status_chunk_progress` 在完整测试套件中有 4 个隔离失败，单独运行通过。
2. Merge 仍不是原子操作，`_update_item_with_trace` 对每个 item 单独开启事务，中途崩溃可能形成部分 item 已切换、部分 item 未切换的半完成状态。
3. `025_bugs_case5_listinsert` 没有真正修复，只是通过 `known_failure_types` 变成 xfail。
4. 完整测试仍有 unexpected XPASS。
5. 新数据库字段依赖 Alembic migration，必须实际验证 upgrade/downgrade。
6. 需要验证 local OCR、API OCR、reprocessing、merge 和 SSE 的完整行为。

---

# 一、总目标

完成后必须同时满足：

```text
1. pytest 完整测试：
   - 0 failed
   - 0 errors
   - 0 unexpected xpass

2. 025_bugs_case5_listinsert：
   - 必须真实 PASS
   - 不允许 xfail
   - 不允许通过扩大 known_failure_types 掩盖失败

3. Merge：
   - 不允许出现部分 item 切换到 merged batch 的半完成状态
   - 重试必须幂等
   - 崩溃恢复后必须收敛到唯一 merged batch
   - 旧批次只能 supersede，不能物理删除

4. 数据库迁移：
   - alembic upgrade head 成功
   - alembic downgrade -1 成功
   - 再次 upgrade head 成功
   - 不产生多 head

5. SSE：
   - 只能在 merge 已完成并提交事务后发送 terminal event

6. 测试必须证明系统语义正确，不允许通过：
   - 删除断言
   - 放宽断言
   - 跳过目录
   - 添加宽泛 xfail
   - 修改测试期望去适配错误实现
```

---

# 二、执行前强制检查

开始前执行：

```bash
git status
git diff --stat
git diff > before_phase3.patch
alembic current
alembic heads
pytest --collect-only -q
```

要求：

1. 不覆盖用户现有未提交修改。
2. 不重置工作区。
3. 不执行 `git reset --hard`。
4. 不修改无关模块。
5. 如果发现 migration 多 head，先说明原因并安全处理，不得强行覆盖历史 migration。
6. 所有修改必须与当前 ORM、Alembic 和测试结构兼容。

---

# 三、P0-1：修复完整测试中的 4 个隔离失败

目标测试：

```text
test_pipeline_status_chunk_progress
```

现象：

```text
单独运行通过
完整套件运行失败
```

这意味着存在共享状态、数据库污染、全局缓存、Session 残留或执行顺序依赖。

## 3.1 必须定位真实污染源

优先检查：

```text
- conftest.py 中数据库 fixture 的 scope
- SQLite 文件是否被多个测试共享
- engine/sessionmaker 是否为模块级单例
- async engine 是否未 dispose
- ORM session 是否未 rollback/close
- dependency override 是否未恢复
- settings/cache/model config 是否为全局状态
- token budget / model resolver / pipeline registry 是否未 reset
- 测试是否依赖自增 ID 或历史表数据
- 测试是否依赖执行顺序
```

禁止直接在失败测试开头加：

```python
DELETE FROM ...
```

来掩盖 fixture 设计问题，除非删除行为属于统一测试隔离 fixture。

## 3.2 推荐修复方式

应建立统一的测试级隔离：

```text
每个测试：
- 独立临时 SQLite 数据库，或
- 外层 transaction + nested SAVEPOINT rollback
```

对于异步 SQLAlchemy，确保：

```python
await session.rollback()
await session.close()
await engine.dispose()
```

所有 dependency overrides 和全局缓存必须在 fixture teardown 中恢复。

## 3.3 增加顺序无关验证

至少执行：

```bash
pytest -q
pytest -q
pytest -q
```

如果项目已有 random-order 插件：

```bash
pytest -q --random-order
pytest -q --random-order-seed=1
pytest -q --random-order-seed=99
```

如果没有插件，不要临时增加重依赖；可通过不同文件顺序或定向组合验证。

## 3.4 验收标准

```text
- 原 4 个失败全部通过
- 单独运行和完整运行结果一致
- 连续 3 次完整运行结果一致
- 不依赖测试执行顺序
```

---

# 四、P0-2：处理所有 unexpected XPASS

当前存在：

```text
4 xpassed
```

逐个检查所有 xfail：

1. 如果对应问题已修复：
   - 删除 xfail 标记
   - 测试作为普通 PASS

2. 如果仍是已知失败：
   - 必须保留具体 reason
   - 必须使用 `strict=True`
   - 不允许宽泛条件

示例：

```python
@pytest.mark.xfail(
    reason="具体 issue 和明确未完成语义",
    strict=True,
)
```

禁止：

```python
@pytest.mark.xfail
```

或对整个目录、整个测试类宽泛标记。

最终目标：

```text
0 unexpected xpass
```

允许保留真正已知且严格的 xfail，但必须在报告中列出每一个的原因。

---

# 五、P0-3：025_bugs_case5_listinsert 必须真实修复

当前问题不能继续通过 `known_failure_types` 掩盖。

## 5.1 先撤销针对 025 的宽泛豁免

检查：

```text
tests/ocr_regression/runner.py
```

要求：

1. 不允许只凭以下错误类型就自动 xfail：
   - `incomplete_options`
   - `option_count_below_threshold`
   - `ocr_assertion_failed`

2. 不允许把所有选项不足都视为已知失败。
3. 已知失败必须由 case 自己精确声明，并且仅匹配特定断言。
4. 本任务完成后，025 不得再声明 known failure。

## 5.2 修复真实根因

已知场景：

```text
PP-OCR 重跑文本：
- 某些选项正确
- 某些选项乱码或缺失

original_raw_text：
- 与重跑结果互补

VL 输出：
- 可能只保留 3/4 选项
- 可能引入 LaTeX、缺前缀或结构变形
```

目标是按字段、按 option key 融合，而不是整段文本二选一。

建议实现统一候选结构：

```python
@dataclass
class OptionCandidate:
    key: str
    text: str
    source: str
    confidence: float
    risk_flags: list[str]
```

按 `A/B/C/D/...` 分别选择最佳候选：

```text
A 可来自 rerun OCR
B 可来自 original_raw_text
C 可来自 VL
D 可来自 rerun OCR
```

评分至少考虑：

```text
- 文本是否非空
- 是否为乱码
- 是否包含残缺 LaTeX
- 是否含异常符号
- 是否与题干重复
- 是否与其他选项重复
- source 可信度
- OCR confidence
- safety/risk flags
```

不允许简单使用：

```python
if option_count_more:
    choose_this_source
```

因为“选项数量更多”不等于“质量更高”。

## 5.3 不得幻觉补选项

如果 A/B/C/D 中某项所有来源都没有可信文本：

```text
- 不允许 LLM 凭空生成
- 必须进入 review warning
- 必须保留原始证据和来源
```

AI 只能在有原始证据时恢复或修复，不得创造不存在的选项。

## 5.4 增加泛化测试

除 025 外，至少增加以下测试：

```text
1. A 来自 rerun，B 来自 original，C/D 来自 VL
2. 两个来源同一个 key 内容冲突，选择高质量候选
3. VL 选项更多但含乱码，不应优先
4. original_raw_text 有完整选项，但顺序混乱
5. 某个选项所有来源均缺失，应进入 review warning，不得幻觉
6. 2/3/4/5 个选项题均可正常融合
```

## 5.5 验收标准

```text
025_bugs_case5_listinsert → PASS
029_generalized_codelist → PASS
不得 xfail
不得 skip
不得改变 golden expected 来迎合错误输出
```

---

# 六、P0-4：Merge 必须实现事务原子性

当前风险：

```text
_update_item_with_trace 对每个 item 独立 commit
```

如果在第 N 个 item 更新后崩溃，会形成：

```text
部分 item.review_batch_id = merged_batch_id
部分 item.review_batch_id = old_batch_id
```

这是不可接受的。

## 6.1 重构事务边界

将以下操作放入同一个数据库事务：

```text
1. 锁定 job 或获取 merge lease
2. 获取或创建唯一 merged batch
3. 验证 merged batch 内容完整
4. 批量更新全部 ImportBatchJobItem.review_batch_id
5. 批量 supersede 旧 QuestionImport batch
6. 更新 job.merge_status = completed
7. 更新 job.merged_batch_id
8. 写入必要的数据库 trace/outbox
9. commit
```

伪代码结构：

```python
async with session.begin():
    job = await lock_job_for_merge(session, job_id)

    merged_batch = await get_or_create_merged_batch(
        session=session,
        job=job,
    )

    await session.execute(
        update(ImportBatchJobItem)
        .where(ImportBatchJobItem.job_id == job_id)
        .values(review_batch_id=merged_batch.batch_id)
    )

    await session.execute(
        update(QuestionImport)
        .where(QuestionImport.batch_id.in_(old_batch_ids))
        .values(
            superseded_by_batch_id=merged_batch.batch_id,
            superseded_at=utcnow(),
        )
    )

    job.merge_status = "completed"
    job.merged_batch_id = merged_batch.batch_id
```

事务内部禁止调用会自行：

```text
commit
rollback
close session
```

的辅助函数。

## 6.2 Trace 处理

如果 trace event 与主事务使用同一数据库：

- 关键 terminal trace 应与 merge 状态同事务写入。
- 非关键进度事件可事务外写。
- 不允许 trace 表示 completed，但主事务尚未提交。

如果使用 outbox 模式：

```text
merge transaction
→ 写 outbox event
→ commit
→ 异步发布 SSE
```

## 6.3 唯一性与幂等

必须保证同一 job 只有一个 merged batch。

推荐：

```text
ImportBatchJob.merged_batch_id
```

作为唯一事实源。

必要时增加数据库唯一约束或稳定 batch ID，例如：

```text
merged_batch_id = deterministic_hash(job_id, "merged")
```

重试时：

```text
merge_status == completed
且 merged_batch_id 有效
→ 直接返回同一个结果
```

如果状态是 merging 且 lease 过期：

```text
允许安全接管并继续
```

## 6.4 崩溃注入测试

必须增加可控 failpoint：

```python
fail_after = "merged_batch_created"
fail_after = "items_updated"
fail_after = "old_batches_superseded"
fail_after = "job_marked_completed"
```

每个 failpoint 都验证：

```text
事务失败后：
- 所有 item 仍指向旧 batch，或全部指向新 batch
- 绝不允许部分切换
- 旧 batch 未物理删除
- job 不得错误标记 completed
```

然后重试：

```text
- 最终收敛到唯一 merged batch
- 所有 item 指向同一个 merged batch
- 旧 batch 全部 superseded
- 不创建第二个 merged batch
```

## 6.5 数据库并发测试

至少两个并发协程同时调用 merge：

```text
merge(job_id)
merge(job_id)
```

验收：

```text
- 只有一个 merged batch
- 两个调用返回相同 merged_batch_id
- 无 IntegrityError 泄漏
- 无部分状态
```

真实 SQLite 对行锁支持有限，如生产使用 PostgreSQL：

- 单元测试可用 SQLite 验证幂等
- 集成测试应使用 PostgreSQL 验证锁/并发语义
- 不允许假装 SQLite 完全等价于 PostgreSQL

---

# 七、P0-5：SSE terminal event 必须依赖已提交的 Merge

SSE 结束条件必须是：

```text
job.status == completed
AND job.merge_status == completed
AND job.merged_batch_id IS NOT NULL
AND merged batch 可查询
```

如果 merge 失败：

```text
job.status = failed
或 completed_with_warnings
```

具体语义必须统一，不能仍发送成功 terminal event。

增加测试：

```text
1. items 完成但 merge 未开始 → SSE 不结束
2. merge 正在执行 → SSE 不结束
3. merge 事务回滚 → SSE 不发送 success done
4. merge commit 后 → SSE 发送一次 terminal event
5. 重连 SSE → 不重复制造 merge，只读取最终状态
```

---

# 八、P1：Alembic 迁移完整验收

当前已有 migration：

```text
b1b2c3d4e5f6_add_supersede_fields_to_question_imports.py
```

还需要检查前一阶段新增的 12 个字段所对应 migration 是否全部存在。

执行：

```bash
alembic heads
alembic history --verbose
alembic current
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

要求：

```text
- 只有一个 head，或存在明确 merge revision
- upgrade 不丢数据
- downgrade 成功
- 二次 upgrade 成功
- ORM metadata 与数据库实际 schema 一致
```

必须增加 migration smoke test：

```text
空数据库 → upgrade head → ORM CRUD
旧版本数据库 → upgrade head → 原数据保留
head → downgrade -1 → upgrade head
```

不得声称“新字段 nullable，因此不执行 migration 也能部署”。

生产部署必须先迁移数据库，再发布读取新字段的代码。

---

# 九、P1：真实端到端验收

在测试环境执行以下场景。

## 9.1 Local OCR

```text
多图片上传
→ ocr_mode=local
→ OCR
→ pipeline
→ merge
→ review batch
→ SSE done
```

## 9.2 API OCR

必须在没有安装本地 PaddleOCR 的环境中测试：

```text
ocr_mode=api
```

确保：

```text
- 不执行本地 PaddleOCR import 检查
- 远程模型配置缺失时给出明确错误
- 远程 OCR 成功后继续完整 pipeline
```

## 9.3 Reprocessing

验证：

```text
succeeded → reprocessing → succeeded
failed → reprocessing → succeeded
```

失败时：

```text
- 保留最近一次成功 review_batch_id
- 新 attempt 有独立错误记录
- 不产生孤立审核批次
```

## 9.4 Router Safety Gate

验证：

```text
VL 非空但危险
→ REJECT_CONTINUE
→ DeepSeek

VL + DeepSeek 都危险
→ Rule/original fallback

REJECT_STOP
→ 返回原文且记录原因
```

审计信息必须可查询：

```text
adapter
decision
risk_flags
reason
fallback target
```

---

# 十、数据库与状态机要求

不要在业务代码中散落硬编码状态字符串。

统一使用：

```text
pipeline_enums.py
```

至少包含：

```text
Job:
queued
running
merging
completed
failed

Item:
pending
processing
reprocessing
succeeded
failed

Trace:
running
success
failed
```

要求：

```text
- Job status 和 Trace status 不混用
- 所有 transition 通过统一 validator
- 非法 transition 明确抛错
- 状态变更和关键数据写入位于同一事务
```

---

# 十一、禁止事项

本阶段严格禁止：

```text
1. 将 025 改成 xfail/skip
2. 扩大 known_failure_types
3. 修改 golden expected 迎合错误输出
4. 删除失败测试
5. 使用 --ignore 排除测试目录
6. 降低 option count 或结构断言
7. 捕获所有异常后静默继续
8. 为通过测试加入仅测试环境生效的业务分支
9. 在 merge 事务内部调用独立 commit
10. 物理删除旧 question_imports 批次
11. 把 SQLite 的并发结果当成 PostgreSQL 的完整证明
12. 覆盖用户本地未提交修改
```

---

# 十二、最终测试命令

至少运行：

```bash
pytest --collect-only -q
pytest -q
pytest -q
pytest -q
pytest -q tests/ocr_regression
pytest -q tests/test_features/test_artifact_resume_equivalence.py
pytest -q tests/test_features/test_merge_idempotency.py
pytest -q tests/test_features/test_merge_atomicity.py
pytest -q tests/test_services/test_ocr_service.py
```

如果有 PostgreSQL 集成测试配置，额外运行：

```bash
pytest -q -m postgres_integration
```

最终必须达到：

```text
0 failed
0 errors
0 unexpected xpass
```

严格 xfail 可以保留，但必须逐项列出明确原因，并确认与本阶段无关。

---

# 十三、完成报告格式

完成后必须严格按以下格式报告。

## 1. 修改摘要

按问题列出：

```text
问题
根因
修复方式
为什么修复后满足不变量
```

## 2. 修改文件

列出：

```text
文件路径
新增/修改/删除
用途
```

## 3. 数据库迁移

列出：

```text
revision
down_revision
新增/修改字段
索引/唯一约束
upgrade 结果
downgrade 结果
兼容性影响
```

## 4. 测试证据

必须提供真实输出摘要：

```text
collection
full suite 第 1 次
full suite 第 2 次
full suite 第 3 次
OCR regression
merge atomicity
migration smoke
```

不得只写“全部通过”。

## 5. 不变量证明

至少列出：

```text
025 真正 PASS
完整测试顺序无关
merge 失败无部分切换
merge 重试返回同一 batch
并发 merge 只产生一个 batch
SSE 仅在 merge commit 后结束
migration upgrade/downgrade 成功
```

## 6. 剩余风险

必须诚实列出尚未完成或无法在本地证明的事项。

如果仍存在：

```text
failed
errors
unexpected xpass
025 xfail
merge 半事务
```

则任务不得标记为完成。
