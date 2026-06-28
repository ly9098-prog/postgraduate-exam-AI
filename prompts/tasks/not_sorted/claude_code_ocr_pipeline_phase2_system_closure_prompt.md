# Claude Code 任务：OCR Pipeline 第二阶段系统语义闭环与生产级不变量修复

你正在修改本地项目：

```text
/home/lmh/projects/postgraduate-ai/backend
```

本任务不是继续“修测试报错”，而是完成 OCR Pipeline 的系统语义闭环。必须以可执行不变量、数据库事务和真实状态机证明修复有效。

---

## 一、执行原则

### 1. 保护本地代码

开始前必须执行并记录：

```bash
git status --short
git diff --stat
git diff
```

要求：

- 不覆盖、回滚或格式化掉用户已有的未提交修改。
- 不执行 `git reset --hard`、`git checkout .`、`git clean -fd`。
- 不自动提交，不自动 push，除非用户随后明确要求。
- 修改前先阅读仓库内的 `CLAUDE.md`、`README`、测试配置、迁移规范和相关架构文档。
- 沿用项目现有代码风格、ORM、迁移工具和测试框架，不另造第二套基础设施。

### 2. 禁止制造“假绿灯”

禁止通过以下方式让测试变绿：

- 删除、跳过或弱化与本任务相关的测试。
- 把失败测试改成只验证当前错误行为。
- 用 `--ignore=scripts`、`-k 'not ...'` 等方式隐藏本应收集的错误。
- 恢复已废弃的 `_call_ocr_api` 或旧 `ocr_fallback` 作为兼容实现。
- 删除数据库唯一约束来掩盖幂等设计错误。
- 把严格断言改成 `assert result is not None` 一类无意义断言。
- 将真实失败标记为非严格 `xfail`。
- 捕获所有异常后静默降级并返回成功。
- 为了兼容错误数据而允许非法状态转移。

如果 `scripts/integration_test.py` 不是 pytest 测试，应通过规范的 `testpaths=tests` 或重命名明确其角色；不能靠命令行全局忽略目录。若它本应是测试，则修复其收集错误或迁移到 `tests/`。

### 3. 修改方式

- 先定位根因，再修改。
- 优先小而清晰的模块化改动，不重写整个 Pipeline。
- 每一个 P0 修复都必须有失败前可复现、修复后通过的测试。
- 数据库结构变化必须提供可回滚迁移。
- 所有状态值、事件值和转换规则必须集中定义，禁止继续散落字符串常量。

---

## 二、当前基线

上一阶段报告称：

```text
1180 passed
1 failed: test_ocr_regression[025_bugs_case5_listinsert]
0 errors（通过 --ignore=scripts 排除了 scripts/integration_test.py）
test_ocr_service.py: 39 passed
```

已完成的表面修改包括：

- item 新增 `reprocessing`
- job 新增 `merging`
- batch upload 新增 `image_ids[]`
- API OCR 模式不再应强制依赖本地 PaddleOCR
- SSE 不应在 merge 前发送 terminal event
- Trace Event status 不再写入 `completed`
- 数据库新增若干兼容字段

但以下核心问题尚未闭环：

1. OCRFixRouter 接受任意非空 adapter 输出，没有安全/质量拒绝后继续 fallback。
2. artifact resume 缺少“完整运行与恢复运行结果等价”的证明。
3. merge、SSE、状态机和数据库事务缺少崩溃恢复与幂等证明。
4. 多文件幂等只证明了 API 参数变化，尚未证明并发和数据库一致性。
5. `025_bugs_case5_listinsert` 仍失败，不得简单标记为“预存问题”。
6. 测试执行通过忽略目录规避了收集错误，测试工程仍不完整。

---

# 三、P0-1：实现质量感知的 OCRFixRouter 闭环

## 目标

将当前：

```text
adapter 返回非空文本 → 立即接受
```

改为：

```text
adapter candidate
→ validator / safety gate
→ ACCEPT：返回候选
→ REJECT_CONTINUE：记录拒绝原因并尝试下一 adapter
→ REJECT_STOP：保留原文或进入人工审核，不继续危险修改
```

## 实施要求

1. 阅读并复用现有：
   - `ai_safety.py`
   - `OCRFixRouter`
   - `PaddleOCRVLAdapter`
   - `DeepSeekFixer`
   - `RuleFixer`
   - 现有 risk flags、diff、代码符号、选项保护逻辑

2. 不要在 Router 内复制一套新的 safety 规则。建立清晰协议，例如：

```python
class CandidateDecision(str, Enum):
    ACCEPT = "accept"
    REJECT_CONTINUE = "reject_continue"
    REJECT_STOP = "reject_stop"

@dataclass(frozen=True)
class CandidateEvaluation:
    decision: CandidateDecision
    reason: str
    risk_flags: tuple[str, ...]
    score: float | None = None
```

名称可按项目风格调整，但语义必须明确。

3. Router 必须保留每次尝试的可审计信息：

```text
adapter_name
candidate_non_empty
validator_decision
reject_reason
risk_flags
latency
最终采用来源
```

4. 非空不等于有效。至少覆盖以下拒绝原因：

- 选项丢失、修改冻结选项或选项数量异常。
- 代码结构/关键代码符号被危险改写。
- 题干明显丢失或长度异常。
- 中文/乱码比例明显恶化。
- 现有 safety gate 判定不安全。

5. 允许 `confidence=0.0` 表示“上游未提供置信度”，但不能因此自动接受或自动拒绝；应进入实际 safety evaluation。

6. 当 VL 返回非空但不安全时，必须继续 DeepSeek；DeepSeek 也不安全时继续 Rule/original fallback。

7. 全部候选被拒绝时：

- 不得返回最后一个危险候选。
- 优先返回原始文本或明确的无修改 Rule 结果。
- 将最终结果标记为 degraded/manual-review-needed。
- 不得伪造成功的 AI 修复来源。

## 必须修改的旧测试

删除或重写当前验证错误行为的测试：

```text
test_vl_result_with_risk_flags_still_accepted
```

它应改为验证：危险 VL 候选被拒绝，Router 继续下一适配器。

## 必须新增的测试

至少覆盖：

1. VL 非空、安全 → 接受，DeepSeek 不调用。
2. VL 非空、危险 → 拒绝，DeepSeek 被调用并接受。
3. VL 抛异常 → DeepSeek 被调用。
4. VL 和 DeepSeek 均危险 → Rule/original 返回。
5. validator 抛异常 → fail-safe，不接受未经验证的候选。
6. risk flags、拒绝原因、最终来源写入 trace。
7. 选项冻结被破坏时必须拒绝。
8. 代码块被删除或关键 `{}`、`->` 被危险改写时必须拒绝。
9. 不允许无限重试或同一 adapter 重复执行。

---

# 四、P0-2：建立 artifact resume 等价性不变量

## 目标

对同一确定性输入：

```text
canonical(full_run(input))
== canonical(resume_from_artifact(input, stage))
```

至少对 `normalize_schema` 和 `repair` 两个 artifact 成立。

## 实施要求

1. 检查 artifact 的实际保存位置与内容，明确它代表：

```text
某个 stage 已完成后的输出
```

2. 禁止再手写容易漂移的 `preceding = {...}` 集合。跳过阶段必须从单一 stage registry 动态推导。

建议 artifact 元数据至少包括：

```text
pipeline_version
artifact_schema_version
completed_through_stage
completed_stage_index
source_sha256
config_hash / options_hash
model_or_prompt_version（如影响结果）
payload_checksum
created_at
```

3. 恢复时必须校验：

- source hash 一致
- pipeline/artifact schema 兼容
- stage 仍存在且顺序兼容
- 影响结果的关键配置兼容
- payload checksum 正确

不兼容时应拒绝恢复并完整重跑，不能静默加载旧 artifact。

4. 修复已知问题：

- `normalize_schema` artifact 保存于噪声清洗之前时，恢复不能跳过 `code_language_noise_clean`。
- `repair` artifact 保存于 `ai_validation`、`similarity_match` 之前时，恢复不能跳过这两个阶段。

5. canonical 比较应排除纯运行时字段，例如随机 UUID、时间戳、耗时；但不得排除业务结果和风险标记。

## 必须新增的测试

1. full run 与 `normalize_schema` artifact resume 等价。
2. full run 与 `repair` artifact resume 等价。
3. 恢复后 `code_language_noise_clean` 确实执行。
4. 恢复后 `ai_validation` 和 `similarity_match` 确实执行。
5. pipeline version/config hash 不一致时拒绝 artifact。
6. artifact 损坏/checksum 不一致时安全回退到完整运行。
7. 不允许重复写入 `question_imports`。
8. 恢复过程失败时不写部分 review 数据。

AI/远程服务可以使用确定性 fake adapter，但不得通过 mock 掉被验证的 stage 本身。

---

# 五、P0-3：正式化 Job、Item、Trace 状态机

## 目标

所有状态和合法转换集中定义，数据库、服务、API、SSE 和测试使用同一套语义。

## Job 状态建议

```text
queued → running → merging → completed
queued → failed
running → failed
merging → failed
running → completed_with_warnings（仅在允许部分成功且无需 merge 时）
merging → completed_with_warnings（merge 降级但有可用结果时）
```

根据现有业务可微调，但终态必须明确。

## Item 状态建议

```text
pending → processing → succeeded
pending → processing → failed
succeeded → reprocessing → succeeded/failed
failed → reprocessing → succeeded/failed
```

禁止直接：

```text
failed → failed
succeeded → succeeded
failed → succeeded
```

## Trace Event 语义

Trace event 必须与实体状态分离：

```text
step: upload / waiting / ocr / pipeline / merge / done / error / reparse
status: running / success / failed
```

若保留 `waiting`，更新文档和集中枚举；否则统一为合法 step。

不得将 `job.status="completed"` 直接写入 `event.status`。

## 实施要求

1. 建立集中定义模块或 enum。
2. 所有转换通过同一 helper 执行。
3. helper 应原子更新：状态、时间戳、错误信息和 trace。
4. 非法转换必须抛出领域异常，而不是数据库随机失败。
5. `queued_at`、`started_at`、`finished_at` 语义正确：创建 queued job 时不能把 `started_at` 当创建时间。
6. 更新数据库文档和 OpenAPI 枚举。

## 必须新增测试

- 所有允许转换参数化测试。
- 所有禁止转换参数化测试。
- reprocessing 成功和失败。
- merging 成功和失败。
- event.status 永远只出现合法值。
- SSE 只在真正终态结束。
- 终态不能重新进入 running，除非创建明确的新 attempt。

---

# 六、P0-4：使 merge 具备事务一致性、幂等和崩溃恢复

## 目标

Job 只有在 merge 完成并完成最终引用切换后才能进入 `completed`。

## 实施要求

1. 执行顺序必须是：

```text
所有 item 处理完成
→ job=merging
→ 创建或复用 merged review batch（pending/inactive）
→ 验证 merged batch
→ 原子更新所有 item.review_batch_id
→ 标记 merged batch active
→ 旧 batch 标记 superseded
→ job=completed
→ 写 done/success trace
```

2. 不要先删除旧 batch。增加或复用：

```text
superseded_by
superseded_at
merge_attempt / merge_key
```

若现有架构没有 review batch 主表，优先以最小可维护方式实现可追踪的 merge 元数据；不要用逐条删除制造不可恢复状态。

3. merge 必须幂等：同一个 job 重试 merge 不得创建多个最终批次。

可使用稳定 merge key：

```text
job_id + sorted(source_review_batch_ids) + merge_version
```

4. 在事务提交前不得向 SSE 发送 terminal event。

5. 若 merge 失败：

- job 进入 `failed` 或明确的 `completed_with_warnings`，按业务定义选择。
- 保存 merge_error。
- 保留可恢复的单图批次。
- 下一次 retry 能继续或安全重做。

6. 不允许半数 item 指向 merged batch、另一半指向旧 batch。

## 必须新增真实数据库测试

使用项目支持的 SQLite 测试数据库，并在可能时覆盖 PostgreSQL 语义：

1. 正常 merge 后所有 item 指向同一最终批次。
2. merge 执行两次，最终批次仍只有一个。
3. 在“创建 merged batch 后、切换引用前”模拟异常，数据库无半完成切换。
4. 在“更新部分 item 后”模拟异常，事务回滚。
5. retry 能完成。
6. 旧批次被标记 superseded，而非提前物理删除。
7. SSE 事件顺序为 `merging/running → done/success`，且 done 最后出现一次。

---

# 七、P0-5：完成多文件幂等和并发一致性

## API 规则

1. 多文件上传时：

- 若提供 `image_ids[]`，长度必须与文件数一致。
- `image_ids[]` 中不允许重复或空值。
- 旧 `image_id` 参数只允许单文件使用。
- 多文件同时传旧 `image_id` 必须返回 422，不能复制给全部文件。
- 未提供 image id 时，为每个文件生成稳定或唯一 ID。

2. `request_id` 表示整批请求，`image_id` 表示单图，不得混用。

3. 数据库唯一约束必须保留，不允许通过删除约束解决冲突。

## 内容级幂等

若现有字段允许，增加或使用：

```text
source_sha256
```

以区分：

- 同一个 image_id 重复提交相同内容：返回已有 item/job。
- 同一个 image_id 提交不同内容：409/422 冲突，不得静默覆盖。
- 不同 image_id 提交相同内容：按业务决定是否允许，但行为要明确并测试。

## 并发要求

创建 job/item 时必须使用数据库保证幂等，不能只靠“先查再插”。捕获唯一约束冲突后读取现有记录并返回一致结果。

## 必须新增测试

1. 两文件 + 两个不同 image_ids 成功。
2. 两文件 + 一个旧 image_id 返回 422。
3. image_ids 长度不一致返回 422。
4. image_ids 内部重复返回 422。
5. 两个并发相同请求只创建一个逻辑 job/item 集合。
6. 唯一约束竞争时返回既有结果，不产生 500。
7. 相同 image_id + 不同内容被拒绝。
8. 临时文件在重复请求、DB 异常和参数校验失败时均清理。

---

# 八、P0-6：修复 `025_bugs_case5_listinsert` 回归

不能继续把它写成“预存问题，与修改无关”。它属于 OCR 回归样本，必须完成以下工作：

1. 单独运行并记录：

```bash
pytest -q <准确测试路径>::<准确用例> -vv
```

2. 输出最小失败差异：

```text
输入 OCR 文本
期望 stem/options/answer
实际 stem/options/answer
首次产生偏差的 stage
```

3. 判断根因属于：

- original_raw_text merge
- noise clean
- option structure repair
- freeze registry
- classifier
- AI repair incomplete_options
- safety gate
- 其他

4. 在根因层修复，不得只为该 fixture 硬编码文字。

5. 新增一个同类但文本不同的泛化回归样本，证明规则不是 case-specific。

6. 最终该测试必须通过。除非证明测试期望本身错误，并用真实设计文档和其他样本证明；此时需修正 fixture 并详细说明，不得简单降低断言。

---

# 九、P0-7：修复测试工程和执行口径

## 目标

提供一个不靠隐藏目录、可重复运行的标准测试命令。

## 实施要求

1. 补齐或整理：

```text
pyproject.toml / pytest.ini
requirements-test.txt 或对应依赖组
pytest markers
```

2. 明确 `scripts/integration_test.py` 的角色：

- 若是脚本：通过 `testpaths=tests` 防止被错误收集，并可重命名为非测试命名。
- 若是测试：移动到 `tests/integration/` 并修复依赖。

不得在最终验收命令使用 `--ignore=scripts`。

3. 旧 OCR service 测试必须验证新架构，不恢复旧 API。

4. 所有 marker 必须注册，运行时不应有未知 marker 警告。

5. 若存在缺少的可选依赖，使用 marker + 明确 skip reason；不能在模块 import 阶段造成整个测试收集失败。

6. `xfail` 必须 `strict=True`，并写明确 issue/reason；本任务新增的测试不得 xfail。

---

# 十、P1：数据库约束与可观测性强化

完成 P0 后再执行，不得让 P1 阻塞 P0 交付。

## 1. 数据库迁移核查

上一阶段声称新增 12 个字段。逐一核查：

- ORM 与 migration 一致。
- upgrade 和 downgrade 可执行。
- 默认值和 nullable 与旧数据兼容。
- SQLite 与生产数据库均可运行。
- 文档同步。

## 2. 审核写入幂等

为 `question_imports` 增加或复用稳定幂等键，避免 worker retry、artifact resume、merge retry 重复写入。

建议由以下信息构成：

```text
pipeline/job id + source item id + question ordinal + stage/version
```

不建议仅使用 `batch_id + question_hash`，因为同批重复题可能需要保留并标记。

## 3. 正式题目并发去重

评估并实现数据库级：

```text
subject + question_hash + active state
```

唯一约束或等价的事务方案。应用层检查不能作为最终一致性保障。

若使用 PostgreSQL 部分唯一索引，要提供 SQLite 测试兼容策略。

## 4. 日志最小化

生产 INFO 日志不得默认记录 2000 字原始题目正文。改为：

```text
length
sha256 prefix
question count
noise metrics
risk flags
```

正文仅在显式 debug 开关下输出，且截断和脱敏。

---

# 十一、数据库迁移要求

使用仓库现有迁移框架。迁移必须：

1. 有明确 revision 名称。
2. 可在已有旧数据的数据库上 upgrade。
3. 可 downgrade。
4. 不在单个迁移中混入无关表结构重写。
5. 对新增非空字段先 nullable/default 回填，再收紧约束，避免生产迁移失败。
6. 若新增 check/unique/index，说明 SQLite 与生产数据库差异。
7. 添加迁移测试或至少使用临时数据库执行完整 upgrade/downgrade/upgrade。

---

# 十二、验收测试矩阵

按以下顺序执行，任何失败都要处理，不能只报告“预存”。

## 1. 静态与收集

```bash
python -m compileall <项目源码目录>
pytest --collect-only -q
```

要求：0 collection errors。

## 2. 定向测试

至少运行：

```text
OCRFixRouter + safety validator
artifact resume equivalence
batch image state machine
reparse from cache
multi-file idempotency
merge transaction + SSE
025_bugs_case5_listinsert
ocr_service 新架构测试
数据库 migration 测试
```

## 3. 完整测试

使用仓库标准命令，例如：

```bash
pytest -q
```

不得通过 `--ignore=scripts`、排除本任务模块或非严格 xfail 获得绿灯。

目标：

```text
0 failed
0 errors
0 unexpected xpass
```

合理的可选依赖 skip 可以存在，但必须列出数量和原因。

## 4. 数据库验证

- 新数据库：upgrade 到 head。
- 旧 schema fixture：upgrade 到 head。
- downgrade 一次再 upgrade。
- 并发唯一约束测试。
- merge rollback 测试。

## 5. 不变量验证

在测试报告中明确列出以下结果：

```text
Router: unsafe non-empty candidate never accepted
Resume: full_run == resume(normalize_schema)
Resume: full_run == resume(repair)
Merge: terminal state only after transaction commit
Merge: retry is idempotent
Batch IDs: one image id per file
Reparse: terminal item enters reprocessing before new attempt
Trace: event status domain is valid
```

---

# 十三、完成报告格式

完成后严格按以下结构输出，不要只给“测试通过”：

## 1. 根因与修复摘要

每个 P0 项说明：

```text
原始错误语义
根因
修改方式
为何不是 workaround
```

## 2. 修改文件

列出所有修改、新增和删除文件，并说明用途。

## 3. 数据库迁移

列出：

```text
revision
新增/修改字段和约束
upgrade 结果
downgrade 结果
兼容性影响
```

## 4. 测试证据

提供实际命令和完整摘要：

```text
collection
focused tests
full suite
migration tests
regression case 025
```

不得省略失败或警告。

## 5. 不变量证明

逐项给出对应测试名称和结果：

```text
full_run == resume_run
unsafe VL → fallback DeepSeek
merge retry → same merged batch
concurrent duplicate request → one logical job
SSE done only after merge commit
```

## 6. API/数据库兼容性

说明：

- 请求参数变化
- 响应/错误码变化
- 状态枚举变化
- 迁移顺序
- 前端是否需要更新
- 旧任务和旧数据如何处理

## 7. 剩余风险

只允许列出真正不属于本任务范围的风险。不得把本任务明确要求的 P0 项列为“未来再做”。

---

# 十四、停止条件

只有同时满足以下条件才算完成：

1. OCRFixRouter 已实现 validator 拒绝后继续 fallback。
2. `test_vl_result_with_risk_flags_still_accepted` 已改为正确安全语义。
3. artifact resume 等价测试通过。
4. merge 在事务提交后才进入 completed。
5. SSE terminal event 只出现一次且在 merge 后。
6. reprocessing 状态机真实可用。
7. 多文件 image IDs 和并发幂等通过数据库测试。
8. `025_bugs_case5_listinsert` 通过。
9. `pytest --collect-only` 无错误。
10. 完整测试 0 failed、0 errors，且没有通过隐藏目录制造绿灯。
11. 所有数据库迁移可 upgrade/downgrade。
12. 完成报告包含具体测试证据和剩余风险。

如果某项因客观依赖确实无法完成：

- 先完成所有不受阻部分。
- 给出准确阻塞证据、已尝试方案和最小剩余修改。
- 不得声称整个任务已完成。
