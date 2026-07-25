继续推进 Sprint 3H：生产集成审计、资产回滚安全与外部验证准备。

当前基线：

- 遗留图片迁移第二阶段已完成：
  - import_id=407：补齐 `source_snapshot_url` 和 `crop_version`
  - import_id=302：补齐缺失的 text segment
  - import_id=320：option_group 图片和内容完整
- 3F-A ModuleResult / Adapter 已提交：
  - commit：`cc452bb`
  - 71 个文件
  - 20,081 行新增
  - 164 项专项测试通过
- 已实现：
  - `ModuleResult[T]`
  - `OcrAdapter` / `DocumentTransformAdapter`
  - `OCRRequest`
  - `AdapterRegistry` / `AdapterSelector`
  - circuit breaker
  - BenchmarkRunner
- LocalFileStorage 根路径问题已修复
- PaddleOCR、GPU、API Token 和预发布验证尚未执行
- 已知未修复问题：
  - 资产回滚流程可能在仍有 DB 引用时删除物理文件
  - 该问题属于数据一致性和设计级风险

本轮不新增 OCR 算法和模型能力，优先完成以下事项：

# 一、审计 commit cc452bb 的真实生产接入

专项测试通过不代表生产主链路已经完成迁移。请对 `cc452bb` 做完整集成审计。

## 1. 建立调用链清单

列出以下对象的所有生产调用点：

```text
ModuleResult
OcrAdapter
DocumentTransformAdapter
OCRRequest
AdapterRegistry
AdapterSelector
AdapterCapabilities
CircuitBreaker
BenchmarkRunner
```

输出：

```text
reports/sprint3h/adapter_call_sites.json
reports/sprint3h/adapter_call_sites.md
```

每个调用点记录：

```text
文件
函数
调用阶段
输入类型
输出类型
是否生产路径
是否兼容路径
是否仍读取后端私有字段
是否有 fallback
是否写入 artifact
是否支持 resume
```

## 2. 验证生产 Pipeline 是否真正使用新契约

重点检查：

```text
local PaddleOCR 路径
PaddleOCR-VL 路径
OCRFixRouter
AI repair
code structure reconstruct
reading order
cross-page linking
structure freeze
artifact restore
batch image import
PDF import
```

禁止出现以下情况：

```text
新 Adapter 只在测试中使用
生产路径仍直接调用旧 OCR service
ModuleResult 创建后立即丢弃 error/warnings
业务层继续解析 rec_texts / dt_polys / layoutParsingResults
新旧 Router 同时执行导致双 OCR
fallback 绕过 AdapterRegistry
```

## 3. 增加后端私有字段边界扫描

新增或完善：

```text
tests/test_backend_private_field_boundaries.py
scripts/audit_backend_private_fields.py
```

Adapter、client 和测试 fixture 目录之外禁止引用：

```text
rec_texts
dt_polys
layoutParsingResults
errorMsg
markdown.text
供应商特有 result 字段
```

输出：

```text
0 production boundary violations
```

如存在遗留调用，必须逐项迁移或列入明确兼容清单。

## 4. 新旧选择路径 Shadow 对比

暂时不要直接删除旧 Router。

增加：

```text
ADAPTER_SELECTION_MODE=legacy | shadow | adapter
```

默认保持：

```text
legacy
```

`shadow` 模式：

```text
旧路径决定实际执行
新 AdapterSelector 同时生成候选顺序
只比较，不改变实际结果
```

记录：

```json
{
  "legacy_candidates": ["paddle_local", "paddle_vl", "rule"],
  "adapter_candidates": ["paddle_local", "paddle_vl", "rule"],
  "order_match": true,
  "capability_match": true,
  "selection_reason_codes": []
}
```

验收：

```text
候选集合一致
候选顺序差异有解释
shadow 不触发第二次真实 OCR
shadow 不增加外部 API 调用
shadow 不改变业务输出
```

# 二、修复资产回滚的引用安全问题

这是本轮最高优先级的数据安全任务。

当前问题：

```text
回滚过程中可能先删除物理文件，
但 Question.content、question_imports、review 数据或其他题目仍然引用该资产。
```

必须实现“引用确认后删除”，禁止直接按照 URL 或 storage key 删除。

## 1. 建立统一资产引用解析器

建议新增：

```text
app/services/asset_reference_service.py
```

接口示例：

```python
@dataclass
class AssetReference:
    entity_type: str
    entity_id: str
    field_name: str
    json_path: str | None
    asset_url: str
    storage_key: str


@dataclass
class AssetReferenceReport:
    storage_key: str
    references: list[AssetReference]
    reference_count: int
    safe_to_delete: bool
    reason_codes: list[str]
```

必须检查的引用来源至少包括：

```text
Question.content
Question parsed_content segments
source_snapshot_url
option_group image segments
question_imports
review records
pipeline artifact
题图关联表
历史版本或 revision 表
其他包含图片 URL/storage key 的 JSON 字段
```

不得只检查当前 Question 表。

## 2. 建立安全删除状态机

建议状态：

```text
planned
reference_checked
detached
grace_period
deleting
deleted
retained
failed
cancelled
```

禁止：

```text
DB 事务提交前删除文件
引用数量未知时删除文件
扫描失败时默认 safe_to_delete=true
删除失败后仍标记 deleted
```

## 3. 使用事务 + Outbox

推荐流程：

```text
事务内：
1. 锁定目标导入记录或做版本检查
2. 更新/撤销 DB 引用
3. 写入 asset_deletion_outbox
4. 提交事务

事务提交后：
5. worker 再次检查引用
6. reference_count == 0 才删除物理文件
7. 记录删除结果
```

不得在数据库事务未提交时删除 Local/COS 文件。

## 4. 支持三种模式

```text
dry-run
detach-only
delete-unreferenced
```

默认：

```text
dry-run
```

行为：

### dry-run

只输出：

```text
将修改哪些 DB 记录
哪些文件可能删除
引用数量
阻塞原因
```

不修改 DB，不删除文件。

### detach-only

只撤销本次导入产生的引用，不删除物理文件。

### delete-unreferenced

只有二次引用检查为零时，才删除物理文件。

## 5. 幂等性要求

同一 rollback request 重复执行：

```text
不重复修改 DB
不重复删除文件
不产生重复 outbox
不导致状态倒退
```

增加：

```text
rollback_request_id 唯一约束
asset_deletion_idempotency_key
```

## 6. 并发要求

必须测试：

```text
回滚同时另一个任务引用同一图片
两个回滚同时处理同一 storage key
回滚期间 Question 被人工编辑
删除 worker 重试
COS 超时
Local delete 成功但状态写入失败
DB 提交失败
```

物理删除前必须再次查询引用。

## 7. 回滚清单和恢复证据

每次操作生成：

```text
rollback_plan.json
rollback_result.json
asset_reference_report.json
database_changes.jsonl
deleted_assets.jsonl
retained_assets.jsonl
errors.jsonl
report.md
```

至少记录：

```text
rollback_request_id
import_id
question_ids
storage keys
操作前引用
操作后引用
文件 hash
DB revision/version
执行模式
执行人或任务来源
开始/结束时间
```

# 三、审计 LocalFileStorage 历史错位文件

由于之前使用 `os.getcwd()`，历史文件可能写入：

```text
project_root/static/
```

而不是：

```text
backend/static/
```

请新增：

```text
scripts/audit_storage_root_mismatch.py
scripts/migrate_misplaced_assets.py
```

## 审计要求

扫描：

```text
project_root/static/
backend/static/
数据库中的本地图片 URL
Question.content 中的图片 URL
question_imports 中的图片 URL
```

识别：

```text
仅旧目录存在
仅新目录存在
两处均存在且 hash 相同
两处均存在但 hash 不同
DB URL 指向不存在文件
文件存在但 DB 无引用
路径穿越或非法路径
```

输出：

```text
storage_root_audit.json
missing_files.jsonl
duplicate_files.jsonl
hash_conflicts.jsonl
orphan_files.jsonl
migration_plan.json
report.md
```

迁移脚本必须支持：

```text
--dry-run
--copy
--move
--verify-checksum
--update-db
--rollback-manifest
```

默认只允许：

```text
--dry-run
```

禁止自动覆盖 hash 不同的同名文件。

# 四、为三个已迁移 Import 建立自动验收

不要只依赖人工总结。

新增回归检查，覆盖：

```text
import_id=407
import_id=302
import_id=320
```

每个案例验证：

```text
Question 记录存在
Question.content 可解析
所有图片 URL 可解析为 storage key
对应物理文件存在
图片可读取
图片 hash 稳定
crop_version=visual-v2.1
source_snapshot_url 存在（适用时）
option_group segment 完整（适用时）
text segment 完整（适用时）
无重复 image segment
display 顺序正确
重复执行迁移后内容不变化
```

新增：

```text
tests/test_legacy_visual_v21_migration.py
scripts/validate_visual_v21_migration.py
```

输出：

```text
visual_v21_validation.json
visual_v21_validation.md
```

# 五、审计 ModuleResult Artifact 体积和兼容性

71 个文件、20,081 行新增属于较大改动，需要检查 artifact 和日志膨胀。

统计：

```text
迁移前 artifact 平均体积
迁移后 artifact 平均体积
ModuleResult.raw 占比
ModuleError.details 占比
warnings 占比
每页平均 ModuleResult 数量
100 页文档预测 artifact 体积
```

验证：

```text
raw capture mode 生效
raw 总大小限制生效
敏感信息已脱敏
截断后仍为合法 JSON
旧 artifact 可恢复
新 artifact 在旧模式下不会导致崩溃
resume 后不重复执行外部 Adapter
```

建议输出：

```text
reports/sprint3h/module_result_artifact_size.json
reports/sprint3h/module_result_artifact_size.md
```

如 artifact 增长超过 30%，必须说明原因并提出瘦身方案。

# 六、执行离线 Adapter Replay

在没有 Paddle/GPU 环境时，仍需使用现有 fixture、历史 artifact 和 mock raw response 做离线 Replay。

比较：

```text
旧 local OCR 结果 → DocumentIR
新 PaddleOCRLocalAdapter → DocumentIR

旧 VL 解析结果 → DocumentIR
新 PaddleOCRVLDocumentAdapter → DocumentIR
```

比较指标：

```text
page 数量
region 数量
line 数量
文本
bbox/polygon
reading order
confidence
layout type
stable ID
provenance
model/component fingerprint
warning/error
```

硬要求：

```text
不丢页
不丢 region
不丢 line
文本无非预期变化
坐标无非预期变化
stable ID 可复现
artifact round-trip 一致
```

新增：

```text
scripts/replay_adapter_contract.py
tests/test_adapter_replay_equivalence.py
```

# 七、建立外部验证执行包

Option C 当前是环境阻塞项。请把它从“跳过”升级为“一键可执行验证包”。

新增或完善：

```text
scripts/preflight_paddle_environment.py
scripts/run_external_ocr_validation.py
docs/ocr/EXTERNAL_VALIDATION.md
```

Preflight 检查：

```text
PaddleOCR import
PaddlePaddle import
CUDA 可见
GPU 型号
cuDNN
权重文件
权重 checksum
API Token 是否存在（只检查存在，不输出值）
外部 API 连通性
预发布服务连通性
存储读写
数据库测试连接
```

状态必须使用：

```text
passed
failed
not_executed_missing_dependency
not_executed_missing_credentials
not_executed_missing_environment
```

禁止笼统使用一个：

```text
skipped
```

外部验证命令至少包括：

```bash
PYTHONPATH=. python scripts/preflight_paddle_environment.py

PYTHONPATH=. python ../scripts/validate_ocr_process_pool.py \
  --quality \
  --input-manifest tests/ocr_bench/manifest.jsonl \
  --output reports/external/process_pool

PYTHONPATH=. python scripts/run_module_benchmarks.py \
  --modules ocr_detection,ocr_recognition,preprocess,pdf_render \
  --output reports/external/module_benchmarks

PYTHONPATH=. python scripts/run_external_ocr_validation.py \
  --output reports/external/full_validation
```

# 八、Benchmark Baseline 收口

执行当前无需 Paddle 的模块基准：

```text
reading_order
structure_freeze
cross_page_linking
question_splitter
text_normalizer
```

要求：

```text
固定 fixture hash
固定 random seed
独立 subprocess cold start
warmup >= 5
iterations >= 30
记录 process-tree RSS
记录输出 digest
记录正确性
```

生成正式 baseline：

```text
benchmarks/baselines/module_benchmark_<commit>.json
reports/sprint3h/module_benchmark/
```

禁止只报告：

```text
测试通过
```

必须提供实际指标：

```text
cold start
warm p50
warm p95
throughput
RSS
output digest
environment fingerprint
```

# 九、拆分和审计大提交

`cc452bb` 包含 71 个文件和 20,081 行新增，需要进行变更风险分类。

输出：

```text
reports/sprint3h/cc452bb_change_inventory.json
reports/sprint3h/cc452bb_risk_review.md
```

按类别统计：

```text
核心生产路径
兼容 wrapper
测试
benchmark
schema
artifact
配置
脚本
文档
```

逐项标记：

```text
P0/P1/P2/P3 风险
是否有测试
是否进入生产路径
是否需要外部环境
是否可回滚
```

如果发现无关变更、重复实现或死代码，应在独立 commit 中清理，不要重写历史提交。

本轮建议拆成独立提交：

```text
1. production adapter integration audit/fixes
2. rollback reference safety
3. storage root audit/migration
4. visual-v2.1 validation
5. external validation package
6. benchmark baseline and docs
```

# 十、工程约束

1. 不新增 OCR 模型或算法
2. 不开始多 GPU Router
3. 不启用 Quality Gate enforce
4. 不把全局 Freeze 默认切换为 IR
5. 不在引用未知时删除物理资产
6. 不在 DB 提交前删除物理文件
7. 不把“文件不存在”视为删除成功而忽略 DB 残留
8. 不覆盖 hash 冲突文件
9. 不使用 `os.getcwd()` 推导生产存储根目录
10. 不伪造 Paddle/GPU/API/预发布结果
11. 不用 mock 结果标记外部验证 passed
12. 不删除 legacy Adapter 路径
13. 不让 shadow selection 触发第二次真实 OCR
14. 不将原始 Token 或签名 URL 写入报告
15. 不只运行新增测试，必须运行受影响的完整测试集

# 十一、测试要求

至少新增：

```text
tests/test_asset_reference_service.py
tests/test_asset_safe_delete.py
tests/test_asset_rollback_idempotency.py
tests/test_asset_rollback_concurrency.py
tests/test_asset_deletion_outbox.py
tests/test_storage_root_resolution.py
tests/test_storage_root_migration.py
tests/test_legacy_visual_v21_migration.py
tests/test_adapter_production_integration.py
tests/test_adapter_shadow_selection.py
tests/test_backend_private_field_boundaries.py
tests/test_adapter_replay_equivalence.py
tests/test_module_result_artifact_size.py
tests/test_external_validation_status.py
```

重点性质测试：

```python
assert referenced_asset_is_never_deleted
assert unreferenced_asset_is_deleted_once
assert rollback_retry_is_idempotent
assert db_failure_does_not_delete_file
assert concurrent_new_reference_blocks_delete
assert hash_conflict_is_not_overwritten
assert storage_root_is_independent_of_cwd
assert adapter_shadow_does_not_call_backend_twice
assert old_and_new_adapter_outputs_are_equivalent
assert old_artifact_can_resume
```

运行：

```bash
cd backend

PYTHONPATH=. pytest \
  tests/test_module_result.py \
  tests/test_ocr_adapter.py \
  tests/test_adapter_production_integration.py \
  tests/test_adapter_shadow_selection.py \
  tests/test_backend_private_field_boundaries.py \
  tests/test_adapter_replay_equivalence.py \
  tests/test_asset_reference_service.py \
  tests/test_asset_safe_delete.py \
  tests/test_asset_rollback_idempotency.py \
  tests/test_asset_rollback_concurrency.py \
  tests/test_asset_deletion_outbox.py \
  tests/test_storage_root_resolution.py \
  tests/test_storage_root_migration.py \
  tests/test_legacy_visual_v21_migration.py \
  tests/test_module_result_artifact_size.py \
  tests/ocr_bench \
  -q

PYTHONPATH=. python scripts/smoke_test.py
PYTHONPATH=. python scripts/validate_bench_cases.py
PYTHONPATH=. python scripts/audit_backend_private_fields.py
PYTHONPATH=. python scripts/validate_visual_v21_migration.py
PYTHONPATH=. python scripts/audit_storage_root_mismatch.py --dry-run
```

同时运行全部受影响的 Pipeline、artifact、storage、review、import、OCR executor 和 persistence 测试。

最低验收：

```text
0 failed
0 unexpected xfailed
Smoke 13/13
Import boundary 0 violations
Backend private field boundary 0 violations
所有引用中的资产均不会被删除
回滚重复执行无副作用
DB 失败不会造成文件提前删除
storage root 不依赖 cwd
三个 visual-v2.1 案例自动验收通过
Adapter shadow 不增加 OCR/API 调用
旧新 Adapter 离线输出等价
旧 artifact resume 通过
外部未执行项有精确状态
```

# 十二、本轮交付总结格式

完成后输出：

1. 修改文件清单
2. commit `cc452bb` 生产接入审计结果
3. 新 Adapter 的真实生产调用路径
4. 仍保留的 legacy 路径
5. 后端私有字段边界扫描结果
6. Adapter Shadow 对比结果
7. ModuleResult artifact 体积变化
8. 资产引用解析范围
9. 安全删除状态机
10. DB transaction + outbox 流程
11. 回滚幂等和并发测试结果
12. Local/COS 删除行为
13. 历史 storage root 错位文件数量
14. 文件迁移和 hash 冲突结果
15. import_id 407/302/320 自动验收结果
16. Adapter 离线 Replay 结果
17. Module Benchmark 实际指标
18. 外部验证 Preflight 状态
19. PaddleOCR / GPU / API / 预发布未执行事项
20. pytest、smoke、boundary 结果
21. 是否已修复资产回滚设计缺陷
22. 是否具备进入 Stage 0 Replay / Stage 1 Observation 的条件
23. 仍然阻塞真实 Canary 的事项

执行顺序：

```text
1. 审计 cc452bb 生产集成
2. 修复资产引用安全和回滚删除
3. 审计并迁移历史 storage root
4. 自动验证三个 visual-v2.1 案例
5. 执行 Adapter 离线 Replay
6. 生成模块 Benchmark baseline
7. 完成外部验证执行包
8. 全量测试和交付总结
```

直接开始执行，不需要再次询问先做哪一项。

没有 Paddle、GPU、API Token 或预发布环境时，完成全部离线任务和执行包，并将真实环境状态明确标记为未执行；不得将“代码准备完成”表述为“真实验证通过”。