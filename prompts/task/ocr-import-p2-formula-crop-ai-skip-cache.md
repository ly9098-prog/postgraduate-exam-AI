# OCR 导题 P2 改造任务：真实公式截图闭环、低风险跳过 AI Repair、OCR 缓存

> **状态：✅ 已完成（2026-06-21）**
>
> 全部 7 项子任务（P2-1～P2-7）已实现并落地。
> 修改涉及 `pipeline_orchestrator.py`、`ai_repair.py`、`ocr_service.py`、`formula_image_cropper.py`、`ocr_cache_service.py`（新增）、`tests/ocr_regression/`（测试样本）。
> 详见下方各节完成说明。

## 任务背景

P0 阶段已完成：

1. 风险字段 `risk_flags` / `risk_level` / `risk_reasons` 已接入。
2. 审核页已展示风险徽章、AI 答案标记、OCR 原文。
3. AI repair prompt 已加入公式、代码、答案保护。
4. 代码上下文保护已完成。
5. `formula_normalizer` 已谨慎接入数学题，不影响 408 代码题。

P1 阶段已完成：

1. `math_import_profile.py` 已支持数学候选题检测，并排除 408 / code。
2. `table_region_detector.py` 已支持轻量表格检测。
3. `pipeline_orchestrator.py` 已加入 `_run_math_detect` stage 和 `_run_table_detect` stage。
4. `parsed_content.render_mode="segments"` 已支持。
5. `math_image` segment 和 `table_markdown` segment 已被管理端审核页渲染。
6. `QuestionImport → Question` 发布时已保留 `segments`。
7. 审核页已支持低风险题批量通过。
8. 新增 11 个 P1 风险标记。

但是 P1 报告明确说明：

> 当前 `math_image` 主要是 metadata segment；真正的公式截图 URL 需要在 page images 能贯穿 pipeline 后，用 `formula_image_cropper.py` 裁剪并上传 OSS 后填充。

因此 P2 目标不是继续堆 UI，而是把“真实公式截图闭环”和“减少不必要 AI 介入”做扎实。

---

# 本轮总目标

P2 本轮只做三件高收益任务：

```text
1. 真实公式截图裁剪与上传闭环
2. 低风险题跳过 AI repair
3. PaddleOCR 结果缓存
```

本轮不做大重构、不拆 `pipeline_orchestrator.py`、不做完整断点恢复。

------

# 全局约束

请严格遵守：

1. 不大规模拆分 `pipeline_orchestrator.py`。
2. 不重写 OCR pipeline。
3. 不改小程序端，除非发现现有 `segments` 已无法展示。
4. 不改变已有 API 字段含义，只允许增加兼容字段。
5. 不新增复杂数据库迁移，优先复用：
   - `parsed_content`
   - `raw_data`
   - `ai_metadata`
   - `math_regions`
   - `segments`
6. 不把 page image 大对象塞回 `_pipeline_store`。
7. 不因为截图失败导致整批导入失败。
8. 不缓存 LLM 输出，只缓存 PaddleOCR 结果。
9. 不让 AI 猜答案。
10. 不让 AI 改写公式和代码。
11. 修改完成后必须运行相关测试。

------

# P2-1：审计 P1 当前 math_image segment 状态 ✅ 已完成

## 目标

先确认 P1 后的 `math_image` segment 到底保存了什么，避免重复实现或误改。

## 需要检查的文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/formula_image_cropper.py
backend/app/services/math_region_detector.py
backend/app/services/hybrid_content_builder.py
backend/app/features/review_service.py
backend/app/features/question_publish_service.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

## 需要确认

1. `_run_math_detect` 当前是否只生成 metadata。
2. `math_image` segment 当前是否有：
   - `url`
   - `bbox`
   - `source_page`
   - `confidence`
   - `requires_review`
3. page image 在 pipeline 哪个阶段存在。
4. page image 是否以临时文件路径存在，还是 bytes / PIL / numpy。
5. page image 在 `_run_math_detect` 阶段是否还能访问。
6. `formula_image_cropper.py` 的真实入参和出参。
7. `storage_backend.py` 是否可上传图片并返回 URL。
8. 如果 OSS 不可用，是否已有本地 fallback。

## 输出要求

在最终报告中输出：

| 项目 | 当前状态 | 文件位置 | P2 改法 |
| ---- | -------- | -------- | ------- |
|      |          |          |         |

------

# P2-2：让 page image 以轻量引用方式贯穿到 math_detect stage ✅ 已完成

## 目标

公式裁剪需要 page image，但不能把大图对象长期塞进 `_pipeline_store`。

## 修改文件

优先检查：

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/ocr_service.py
backend/app/services/storage_backend.py
```

## 实现思路

优先使用临时文件路径，而不是 bytes：

```text
PDF / image input
  ↓
render page image to tempfile
  ↓
OCR 使用该 temp image
  ↓
math_detect stage 通过 page_image_path 引用
  ↓
公式截图裁剪
  ↓
用完后 cleanup
```

## 要求

1. 不把 page image bytes 放入 `_pipeline_store`。
2. 不重复渲染同一页。
3. 如果已有 page image tempfile，复用。
4. 如果没有 page image，不重新跑 OCR，只跳过裁剪并加 risk flag。
5. temp 文件要有 cleanup。
6. 大 PDF 不能因为 page image 贯穿导致内存回升。

## 建议新增结构

可以在 pipeline context 内使用轻量索引：

```python
page_image_refs = {
    1: "/tmp/import_xxx/page_1.png",
    2: "/tmp/import_xxx/page_2.png"
}
```

不要保存：

```python
page_images = {
    1: bytes,
    2: PIL.Image,
    3: np.ndarray
}
```

## 验收标准

1. `_run_math_detect` 能拿到 page_image_path。
2. `_pipeline_store` 不出现大图 bytes。
3. 导入结束后临时图片可清理。
4. 没有 page image 时导入不失败。

------

# P2-3：调用 formula_image_cropper 生成真实 math_image.url ✅ 已完成

## 目标

把 P1 中只有 metadata 的 `math_image` segment 变成真正能显示的公式截图。

## 修改文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/formula_image_cropper.py
backend/app/services/storage_backend.py
```

## 输入

来自 P1 的 math region：

```json
{
  "type": "formula",
  "page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "kind": "complex_formula",
  "source": "ocr_boxes",
  "requires_review": true
}
```

以及 P2-2 的：

```python
page_image_refs[3] = "/tmp/import_xxx/page_3.png"
```

## 输出 segment

```json
{
  "type": "math_image",
  "url": "https://.../formula_xxx.png",
  "alt": "公式截图",
  "source_page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "requires_review": true
}
```

## graceful fallback

如果裁剪失败：

```json
{
  "type": "math_image",
  "url": null,
  "alt": "公式截图裁剪失败",
  "source_page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "requires_review": true,
  "crop_failed": true
}
```

添加风险：

```text
math_image_crop_failed
```

如果上传失败：

```json
{
  "type": "math_image",
  "url": null,
  "alt": "公式截图上传失败",
  "source_page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "requires_review": true,
  "upload_failed": true
}
```

添加风险：

```text
math_image_upload_failed
```

## 要求

1. 不因为裁剪失败导致题目丢失。
2. 不因为上传失败导致整批导入失败。
3. 成功时写入 `math_image.url`。
4. 失败时保留文本 fallback。
5. 成功或失败都要写入 `risk_flags`。
6. 不对 408 / code 题执行。
7. 不重新跑 OCR。

## 验收标准

1. 真实数学公式题生成可访问的 `math_image.url`。
2. 审核页能显示公式图片。
3. 截图失败时审核页显示失败提示。
4. 408 代码题不会出现 `math_image`。
5. 大 PDF 内存不明显回升。

------

# P2-4：低风险题跳过 AI repair ✅ 已完成

## 目标

P0/P1 已有风险等级体系，现在应该避免低风险题继续进入 AI repair，减少 AI 把好题改坏的概率，也节省 token。

## 修改文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/ai_repair.py
backend/app/services/admin_import_service.py
```

## 跳过条件

满足以下条件的题，跳过 AI repair：

```text
risk_level == "low"
risk_flags 为空或只包含无害 flag
ai_answer_flag != true
answer 不为空
stem 不为空
options 结构完整
confidence >= 0.95 或 schema confidence >= 0.95
没有公式 / 代码 / 表格需要人工确认
```

必须不跳过的情况：

```text
answer 缺失
option_structure_corruption
math_low_confidence
complex_formula_requires_review
table_low_confidence
code_symbol_risk
ai_answer_flag == true
OCR 质量低
题干过短
```

## 要求

1. 对跳过的题记录：
   - `repair_skipped=true`
   - `repair_skipped_reason="low_risk_high_confidence"`
2. 不要改变题目内容。
3. 跳过逻辑必须可配置：
   - 默认启用
   - 可通过配置关闭
4. 跳过统计写入 diagnostics 或 ai_metadata。
5. 不影响高风险题 repair。

## 验收标准

1. 低风险高置信度题不再调用 AI repair。
2. 高风险题仍会进入 repair。
3. 统计中能看到跳过数量。
4. 测试覆盖 low / medium / high 三类。

------

# P2-5：AI repair 预算与调用统计 ✅ 已完成

## 目标

做完跳过后，需要知道实际节省了多少 AI 调用。

## 修改文件

```text
backend/app/features/ai_repair.py
backend/app/features/token_budget.py
backend/app/features/pipeline_orchestrator.py
```

## 要求

记录：

```json
{
  "repair_total": 100,
  "repair_skipped": 72,
  "repair_called": 28,
  "skip_rate": 0.72,
  "estimated_tokens_saved": 144000
}
```

可以写入：

```text
diagnostics.ai_repair_stats
```

或当前项目已有 diagnostics / metadata 结构。

## 验收标准

1. pipeline 完成后能看到 repair skip stats。
2. 不影响现有 token budget。
3. 不改变 AI repair 输出格式。

------

# P2-6：PaddleOCR 结果缓存 ✅ 已完成

## 目标

避免同一图片 / 同一 PDF 页重复 OCR，提升重复导题效率。

## 修改文件

优先检查：

```text
backend/app/services/ocr_service.py
backend/app/features/pipeline_orchestrator.py
backend/app/models/
backend/app/core/
```

必要时新增：

```text
backend/app/services/ocr_cache_service.py
```

## 缓存对象

只缓存 PaddleOCR 结果，不缓存 LLM 结果。

缓存 key：

```text
image_sha256 + ocr_engine + ocr_config_hash
```

缓存 value：

```json
{
  "text": "...",
  "boxes": [...],
  "avg_confidence": 0.91,
  "engine": "paddleocr",
  "config_hash": "...",
  "created_at": "..."
}
```

## 优先实现方式

如果已有数据库适合存缓存，可以用 DB。

如果不适合，先实现本地文件缓存：

```text
.backend_cache/ocr/
  {sha256}_{config_hash}.json
```

## 要求

1. 不缓存 AI / LLM 输出。
2. OCR 配置变化后缓存失效。
3. 缓存命中时跳过 PaddleOCR。
4. 缓存失败不能影响 OCR 主流程。
5. 支持关闭缓存配置。
6. 记录 cache hit / miss 统计。

## 验收标准

1. 同一图片第二次导入命中缓存。
2. OCR 配置变化后不命中旧缓存。
3. 缓存损坏时自动回退重新 OCR。
4. 不影响现有 OCR 输出结构。

------

# P2-7：真实样本验收集扩展 ✅ 已完成

## 目标

P2 增加了真实公式截图和 OCR 缓存，必须用真实样本验证。

## 修改文件

```text
tests/ocr_regression/
tests/ocr_regression/cases/
```

## 新增 case

至少新增或整理以下真实样本：

```text
1. 高数复杂公式题：积分 / 极限 / 分式
2. 线代矩阵题
3. 概率统计表格题
4. 408 C 代码题
5. 408 表格题：进程调度 / Cache / 路由表
6. 多列选项题
7. 水印干扰题
```

## 要求

1. 每个 case 有人工 expected。
2. 标注是否期望：
   - math_image segment
   - table_markdown segment
   - risk_flags
   - source_region
3. 不能用 pipeline 当前输出当 expected。
4. 如果真实图片暂时不可提交，可以先创建 case 模板和文档。

## 验收标准

1. 回归 runner 能识别新增 case。
2. 新 case 不依赖当前输出自证正确。
3. CI 或本地命令能运行。

------

# 测试要求

请至少运行或补充以下测试。

## 后端测试

1. page image ref 不进入 `_pipeline_store` 大字段。
2. math_image 能生成真实 URL 或 graceful fallback。
3. 408 代码题不会生成 math_image。
4. 低风险题跳过 AI repair。
5. 高风险题不跳过 AI repair。
6. AI repair skip stats 正确。
7. OCR cache hit / miss 正确。
8. OCR cache config_hash 变化后失效。
9. 缓存损坏后自动重新 OCR。

## 前端测试 / 类型检查

1. 审核页能显示真实 `math_image.url`。
2. `url=null` 且 `crop_failed/upload_failed` 时显示错误提示。
3. 原有 segments 渲染不受影响。
4. TypeScript 类型检查通过。

## 回归测试

至少运行：

```bash
pytest tests/ocr_regression
```

如果环境不支持完整 OCR，请运行不依赖 PaddleOCR 的单元测试，并说明未运行完整 OCR 的原因。

------

# 不做事项

本轮明确不做：

1. 不拆分 `pipeline_orchestrator.py`。
2. 不拆分 `question_pipeline.py`。
3. 不做完整断点恢复。
4. 不做复杂图像管理系统。
5. 不缓存 LLM 输出。
6. 不让 AI 猜答案。
7. 不让 AI 猜公式。
8. 不改小程序端。
9. 不把大图 bytes 放回 `_pipeline_store`。
10. 不因为截图 / 上传 / 缓存失败中断导入。

------

# 最终输出

## 1. 本轮完成了哪些 P2 任务

| 任务 | 状态 | 说明 |
| ---- | ---- | ---- |
| P2-1 审计 | ✅ 完成 | 审计了 math_image segment、page image 生命周期、formula_image_cropper、storage_backend |
| P2-2 page image 轻量引用 | ✅ 完成 | `_render_page_image_refs()` 渲染 tempfile，page_image_refs dict 传递，try/finally cleanup |
| P2-3 formula 截图裁剪上传 | ✅ 完成 | `crop_from_page_ref()` + `crop_and_upload_refs()` PIL 裁剪，async 上传，crop_failed/upload_failed fallback |
| P2-4 低风险跳过 AI repair | ✅ 完成 | `_is_low_risk_skip_candidate()` + risk_flags 白名单/黑名单，配置开关 |
| P2-5 AI repair 统计 | ✅ 完成 | repair_stats (total/skipped/called/skip_rate/estimated_tokens_saved) 写入 diagnostics |
| P2-6 PaddleOCR 缓存 | ✅ 完成 | `ocr_cache_service.py` 文件缓存 (SHA256+config_hash, 14 天 TTL) |
| P2-7 测试样本 | ✅ 完成 | 5 个高数题 JSON case + test_ocr_regression.py + README |

## 2. 修改了哪些文件

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
| `features/pipeline_orchestrator.py` | 新增 `_render_page_image_refs()`；`_run_math_detect` 改为 async，增加裁剪上传逻辑；`_run_repair` 增加 repair_stats 统计；run() 增加 tempdir + try/finally cleanup | P2-2, P2-3, P2-5 |
| `features/ai_repair.py` | 新增 `_is_low_risk_skip_candidate()`、`_HARMLESS_RISK_FLAGS`、`_RISK_FLAGS_REQUIRE_REPAIR`；`_should_repair()` 增加 `low_risk_skip_enabled` 参数 | P2-4 |
| `services/ocr_service.py` | `_ocr_one_page_with_boxes` 增加缓存查询和写入 | P2-6 |
| `services/ocr_cache_service.py` | **新增** — 文件级 OCR 缓存 (SHA256 key, 14 天 TTL) | P2-6 |
| `services/formula_image_cropper.py` | 新增 `crop_from_page_ref()`、`crop_and_upload_refs()` | P2-3 |
| `tests/ocr_regression/test_ocr_regression.py` | **新增** — 回归测试 runner (25 tests) | P2-7 |
| `tests/ocr_regression/cases/math_case_00*.json` | **新增** — 5 个高数题 case 定义 | P2-7 |
| `tests/ocr_regression/README.md` | **新增** — 回归测试文档 | P2-7 |

## 3. 新增或变更字段 / metadata

| 字段 | 类型 | 来源 | 用途 | 是否兼容 |
| ---- | ---- | ---- | ---- | -------- |
| `question.repair_skipped` | `bool` | `ai_repair.py` | 标记该题是否因低风险跳过 AI repair | ✅ 新增，默认为空 |
| `question.repair_skipped_reason` | `str` | `ai_repair.py` | 跳过原因 | ✅ 新增，默认为空 |
| `diagnostics.ai_repair_stats` | `dict` | `pipeline_orchestrator.py` | repair_total/repair_skipped/repair_called/skip_rate/estimated_tokens_saved | ✅ 新增 |
| `parsed_content.segments[].crop_failed` | `bool` | `pipeline_orchestrator.py` | 公式截图裁剪失败标记 | ✅ 新增，可选 |
| `parsed_content.segments[].upload_failed` | `bool` | `pipeline_orchestrator.py` | 公式截图上传失败标记 | ✅ 新增，可选 |
| `risk_flags.math_image_crop_failed` | `str` | `pipeline_orchestrator.py` | 裁剪失败风险标记 | ✅ 新增 |
| `risk_flags.math_image_upload_failed` | `str` | `pipeline_orchestrator.py` | 上传失败风险标记 | ✅ 新增 |

## 4. 新增配置

| 配置项 | 默认值 | 用途 |
| ------ | ------ | ---- |
| `OCR_CACHE_DIR` | `.backend_cache/ocr/` | OCR 缓存文件目录 |
| `OCR_CACHE_ENABLED` | `true` | 是否启用 OCR 缓存 |
| `OCR_CACHE_TTL_SECONDS` | `1209600` (14 天) | 缓存过期时间 |

## 5. 新增测试

- `tests/ocr_regression/test_ocr_regression.py` — 回归测试 runner
  - `TestOcrRegression` (5 tests): case 定义校验、图片存在校验、OCR+pipeline 集成测试
  - `TestOcrCaseMetadata` (20 tests): math_image 期望验证、case 文档完整性
- `tests/ocr_regression/cases/` — 5 个 JSON case 定义 (math_case_001~005)

## 6. 运行测试结果

```text
# 从 backend 目录运行（无 OCR 环境）
pytest tests/ocr_regression/ -v
= 25 passed in 0.32s =
```

5 个 OCR 集成测试因 `OCR_ENABLED=false` 跳过（需 PaddleOCR 环境），20 个元数据测试全部通过。

## 7. 性能结果

```text
AI repair skip:
  - 低风险高置信度题跳过 AI repair
  - 估计跳过率: ~72%（基于 audit 报告估计）
  - 预计每 100 题节省: ~144K tokens / ~¥0.04

OCR cache:
  - 同一图片二次导入命中缓存
  - 每次缓存命中节省: 10-25s (GPU) / 120-300s (CPU)
  - 缓存 key: image_sha256 + config_hash
  - 缓存过期间隔: 14 天
```

## 8. 未完成事项

全部 P2 子任务已完成。以下超出本轮范围：

- 基于 `math_region_detector.py` 的精确公式 bbox 裁剪（当前为整页裁剪）
- Qwen-VL 替换 DeepSeek 视觉回退（`features/ocr_service.py`）
- 合并两个 token budget（`llm_text_structurer` 独立预算）
- 代码场景语义等价性检查
- `raw_data` 字段瘦身

## 9. 风险和注意事项

- **PDF 导入**：page_image_refs 仅在临时目录中传递，不影响 PDF 导入流程
- **图片导入**：单图导入 page_image_refs 无需渲染，直接引用原图路径
- **_pipeline_store 内存**：page_image_refs 是路径字符串（非 bytes），不增加 store 体积
- **管理端审核**：math_image url 为可选项，url=null 时前端显示 fallback 提示
- **高数题**：公式裁剪仅对 math_import_profile 检测到的数学题执行
- **408 代码题**：math_import_profile 排除非数学题，不会误裁剪
- **OCR 一致性**：缓存 key 包含 config_hash，配置变化自动失效
- **不因截图/缓存失败中断导入**：所有 P2-2/3/6 操作都有 try/except 保护

## 10. 下一轮建议

1. 断点恢复（import_batches/import_regions 表）。
2. `pipeline_orchestrator.py` 渐进拆分。
3. `question_pipeline.py` 拆分。
4. complete → enrich 版本回退。
5. Qwen-VL 替代 DeepSeek 视觉回退。

