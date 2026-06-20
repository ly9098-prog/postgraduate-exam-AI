你是资深 Python/FastAPI 后端工程师与 AI Pipeline 架构师。请基于当前项目代码，按照《OCR Pipeline 全量工程审计报告》（ocr-pipeline-full-engineering-audit.md）中的待完成任务，对 OCR 导入管线进行渐进式修改。

目标不是重写整个系统，而是优先完成 P0 阶段任务：稳定性、路径统一、清洗逻辑归并、AI 幻觉防护、真实回归基线。请严格遵守以下原则：

1. 不要一次性大规模重构。
2. 不要改变现有 API 的入参和出参，除非必须。
3. 不要破坏现有 PDF、图片、Excel 导入能力。
4. 每次修改后运行相关测试。
5. 对每个修改点说明：修改了哪些文件、为什么改、如何验证。
6. 如果发现审计报告与实际代码不一致，以实际代码为准，但要在总结中说明差异。
7. 优先完成 P0，P1/P2 只做低风险、独立、收益明显的任务。
8. 所有 AI/LLM 调用必须加保护，不允许无条件信任模型输出。
9. 所有大字段、大 bytes、大 OCR 中间结果都不能长期驻留内存。
10. 保留可回滚能力，避免把 OCR 错误通过 AI 修复链路二次放大。

## P0 任务进度

| 任务 | 状态 | 提交 |
|------|------|------|
| 任务 1: 释放 PDF bytes | ⚠️ 部分完成 | file_path/mmap 已做，tempfile 清理未完成 |
| 任务 2: 消除双 OCR | ❌ 未开始 | — |
| 任务 3: _pipeline_store 剥离大字段 | ✅ 完成 | (待提交) |
| 任务 4: 统一 OCR 纠错路径 | ✅ 完成 | edcfd0c |
| 任务 5: 统一 OCR 清洗与字符映射 | ✅ 完成 | cc419dd |
| 任务 6: AI diff 记录与版本回退 | ✅ 完成 | (待提交) |
| 任务 7: 建立真实图片回归基线 | ⚠️ 部分完成 | 3 real cases added，metrics system 未增强 |

请先阅读并定位以下关键模块：

- features/pipeline_orchestrator.py
- features/question_pipeline.py
- features/ocr_correction.py
- features/ocr_quality_gate.py
- features/text_normalizer.py
- features/question_splitter.py
- features/ai_repair.py
- features/llm_text_structurer.py
- features/token_budget.py
- features/ocr_fix/router.py
- features/ocr_fix/qwen_adapter.py
- features/ocr_fix/deepseek_adapter.py
- features/ocr_fix/rule_adapter.py
- services/ocr_service.py
- api/v1/imports.py
- models/question_import.py
- 相关 tests 目录

请按照以下阶段执行。

# ============================================================ 阶段 1：P0 稳定性与路径统一

任务 1：释放 PDF bytes，避免大 PDF 内存崩溃

目标：

- 上传后的 PDF bytes 不应在 pipeline 生命周期中长期保存。
- 提取后应立即落盘到 tempfile 或受控临时目录。
- 后续 OCR、渲染、结构分析都使用文件路径。
- 用完后清理临时文件。

请检查 pipeline_orchestrator.py 中是否存在 file_content、pdf_bytes、uploaded_bytes 等大对象长期保存在 state、store、diagnostics、job context 中的情况。

需要实现：

- 新增或复用临时文件管理函数，例如 save_upload_to_tempfile。
- 将 file_content 写入 tempfile 后立即 del file_content，并在合适位置 gc.collect。
- pipeline state 中只保存 file_path / temp_path，不保存原始 bytes。
- 如果已有清理机制，接入现有 cleanup；如果没有，添加 finally 清理。
- 不要破坏图片导入和 Excel 导入。

验收标准：

- 代码中不再将大 PDF bytes 长期放入 _pipeline_store、diagnostics、raw_data。
- PDF 导入功能仍能正常运行。
- 失败时临时文件不会永久堆积。

------

任务 2：消除 EXERCISE_DETECTION 双 OCR

目标：

- 如果当前流程先做 lightweight exercise detection，又做全量 OCR，请改为共享一次 OCR 推理结果。
- 不允许同一页 PDF 在同一 pipeline 中被 PaddleOCR 重复识别两次。

需要实现：

- 查找 exercise detection / lightweight scan / full OCR 的调用链。
- 将第一次 OCR 结果保存为 OcrPageResult[] 或等价结构。
- 后续阶段复用同一个 OCR result。
- 如果 detection 只需要文本，可以从 OCR result 中提取轻量 text view。
- 避免缓存大图片本体，只缓存结构化 OCR 文本和 boxes。

验收标准：

- 同一 PDF 页面不重复调用 PaddleOCR。
- 原有 exercise detection 逻辑结果保持一致或更稳定。
- 相关测试通过。

------

任务 3：_pipeline_store 剥离大字段

目标：

- _pipeline_store 不应保存 raw_blocks、normalized_blocks、corrections、raw_questions_preview、大 diagnostics 等大字段。
- store 只保存任务状态、阶段进度、小摘要、引用路径或 ID。

需要实现：

- 搜索 _pipeline_store 写入位置。
- 将大字段迁移到临时 KV 文件、临时 JSON、DB 临时表或受控 artifact store。
- _pipeline_store 中只保存 large_payload_ref。
- 设置 TTL 或 cleanup 机制。
- diagnostics 中的预览字段限制长度，例如最多 20 条、每条最多 500 字符。

验收标准：

- _pipeline_store 单任务体积明显下降。
- 不影响前端查询进度。
- 不影响错误诊断的基本信息展示。

------

任务 4：统一 OCR 纠错路径，清理旧版 ocr_correction.py 主流程

目标：

- OCR AI 纠错只保留 features/ocr_fix/router.py 作为唯一主路径。
- 旧版 features/ocr_correction.py 不再作为主流程调用。
- 旧版中仍有价值的逻辑，例如 _filter_sensitive_content、噪声检测、结构异常检测，可以迁移到新版 router 或 quality gate。

需要实现：

- 查找所有 correct_ocr_blocks、_call_ai_correction、ocr_correction.py 的调用点。
- 将调用点切换为 OCRFixRouter。
- 配置统一为：Qwen-VL → DeepSeek → RuleFixer。
- Qwen-VL 只在有原图或低质量 OCR 时调用。
- DeepSeek 只作为文本回退，不做伪视觉 OCR。
- RuleFixer 作为最终 no-op fallback，不应抛出致命异常。
- 如果不能完全删除 ocr_correction.py，请至少将其标记 deprecated，并确保主流程不可再调用。
- 将旧版敏感内容过滤逻辑迁移到新版路径。

验收标准：

- 同一 OCR 文本不会先走旧版 DeepSeek 再走新版 Qwen/DeepSeek。
- enable_ai_correction 与 enable_ai_repair 的语义清晰，不再控制两套重复 OCR 纠错路径。
- 旧版路径不再被主 pipeline 调用。
- 所有相关测试通过。

------

任务 5：统一 OCR 清洗与字符映射逻辑

目标：

- clean_ocr_text、字符映射、乱码过滤、箭头修复、水印过滤、代码保护，只能集中维护在 features/text_normalizer.py。
- services/ocr_service.py、question_splitter.py、pipeline_orchestrator.py 不应再各自维护一套不同的 OCR 清洗逻辑。

需要实现：

- 在 text_normalizer.py 中提供唯一入口，例如：
  - normalize_ocr_text(text: str, context: Optional[str] = None) -> str
  - 或复用现有 ImportTextNormalizer.normalize
- 合并以下规则：
  - 换行规范化
  - 空格规范化
  - 全角/半角标点规范化
  - Unicode 乱码字符移除
  - OCR 数字/字母混淆修正
  - C 指针箭头修复，例如 ->、-＞、一> 等
  - 水印和页码过滤
  - LaTeX 清理
  - 代码围栏保护
  - CJK 字符保护，不能误删中文、日文、韩文字符
- 其他模块只调用 text_normalizer，不再内联 re.sub 和 replace。
- 如果某些模块确实需要局部格式处理，请命名为局部结构处理，不要再叫 OCR clean。

验收标准：

- clean_ocr_text 只剩一个权威实现。
- CJK 字符不会丢失。
- 代码符号不会被错误替换。
- question_splitter 中只保留结构分割逻辑，不负责 OCR 通用清洗。

------

任务 6：AI 纠错和 AI 修复之间添加 diff 记录与版本回退

目标：

- 所有 AI 修改都必须可追踪。
- OCR 纠错 → AI 修复 → AI 补全 → AI 丰富之间不能无保护串联。
- 如果 AI 输出疑似破坏原文，应自动回滚或标记人工审核。

需要实现：

- 新增统一的 AI edit trace 结构，例如：
  {
  "stage": "ocr_fix",
  "model": "qwen-vl",
  "before": "...",
  "after": "...",
  "diff": "...",
  "risk_flags": [],
  "accepted": true/false,
  "rollback_reason": null
  }
- 新增 safe_accept_ai_result(before, after, context, quality_report)。
- 至少实现以下保护：
  - after 为空：拒绝
  - after 长度小于 before 0.5 倍或大于 2 倍：拒绝
  - 题干明显丢失：拒绝
  - 选项数量减少：拒绝
  - 答案被无依据修改：标记风险
  - 代码场景中 ->、==、!=、<=、>=、*、& 等关键符号数量异常变化：拒绝或标记人工审核
  - 水印文字被 AI 保留：标记风险
- 在 ocr_fix/router、ai_repair、complete_import、enrich_import 等 AI 介入点记录 trace。
- trace 不要无限塞进 _pipeline_store，大字段走 large_payload_ref 或 DB。

验收标准：

- 每次 AI 修改都能看到 before/after/diff。
- 高风险修改会自动回滚。
- AI 纠错不会静默覆盖原始 OCR 文本。
- 失败时可定位是哪个模型、哪个阶段改坏了文本。

------

任务 7：建立真实图片回归基线

目标：

- 禁止用 pipeline 当前输出作为 expected。
- 至少建立 5 张真实 OCR 失败图片的人工标注 ground truth。
- 回归测试必须能衡量真实效果，而不是同义反复。

需要实现：

- 检查 tests/ocr_regression/runner.py、metrics.py、classifier.py。
- 修复 --baseline 模式，禁止自动把当前输出直接写成 expected，除非显式使用 update-snapshot 且带人工确认说明。
- 新增 real_cases 目录结构，例如：
  tests/ocr_regression/real_cases/
  case_001.png
  case_001_expected.json
- expected.json 至少包含：
  - questions
  - number
  - stem
  - options
  - answer
  - must_not_contain
  - known_failure_types 可选
- 指标至少包括：
  - 题号召回率
  - 题干相似度
  - 选项完整率
  - 答案匹配率
  - 水印残留率
  - 代码符号保持率
  - AI 修改破坏率
- 如果当前仓库没有真实图片，不要凭空生成图片；先搭建测试框架和示例 expected 模板。

验收标准：

- 真实样本测试不依赖当前 pipeline 输出自证正确。
- runner 能清楚输出每个 case 的失败原因。
- 后续改造可用这些 case 防止回归。

# ============================================================ 阶段 2：P1 低风险优化

完成 P0 后，再选择以下低风险 P1 任务。

任务 8：AI 补全和丰富并行化

目标：

- 当前如果 complete/enrich 对 50 题串行调用 LLM，请改为 asyncio.gather + Semaphore。
- 并发数可配置，默认 3～5。

需要实现：

- 对 complete_import、enrich_import 或对应函数做并发包装。
- 单题失败不能导致全批失败。
- 保持输出顺序与输入题目顺序一致。
- 增加限流、重试和异常记录。

验收标准：

- 批量补全耗时明显下降。
- 单题失败会进入 warning，不影响其他题。
- API 限流时能降级或重试。

------

任务 9：高置信度题目跳过 ai_repair

目标：

- normalize_schema 或 question_normalizer 已给出高置信度的题目，不再进入 AI 修复。
- 默认阈值 0.95，可配置。

需要实现：

- 在 ai_repair 前过滤 high_confidence questions。
- 只对低置信度、有 risk_flags、结构不完整的题目调用 AI。
- 被跳过的题目记录 skipped_reason。

验收标准：

- 高质量题不被 AI 改写。
- repair 调用次数下降。
- 结果一致性提高。

------

任务 10：合并 token budget

目标：

- llm_text_structurer 不再使用独立进程级预算。
- 统一接入 features/token_budget.py。

需要实现：

- 查找所有独立预算计数。
- 替换为共享 token_budget。
- 保持原有预算上限配置兼容。

验收标准：

- 所有 LLM 调用共享统一预算。
- 不会出现一个模块超限另一个模块不知道的情况。

# ============================================================ 阶段 3：P1/P2 架构拆分，仅在 P0 稳定后执行

任务 11：拆分 pipeline_orchestrator.py

目标：

- 不要一次性重写。
- 先建立 pipeline_stages/ 目录，把 OCR、normalize、quality_gate、ai_fix、split、repair、persist 等阶段逐步抽出。
- 原 ImportPipeline 保留为编排器。

建议结构：
features/pipeline_stages/
extract_stage.py
ocr_stage.py
normalize_stage.py
quality_gate_stage.py
ai_fix_stage.py
split_stage.py
match_stage.py
repair_stage.py
persist_stage.py

验收标准：

- 每个 stage 可单独测试。
- 原有 pipeline API 不变。
- 旧测试通过。

------

任务 12：拆分 question_pipeline.py

目标：

- 将 question_pipeline.py 拆分为 normalizer、enricher、writer。
- 不要改变外部 process_question_pipeline 行为。

建议结构：
features/question_processing/
normalizer.py
enricher.py
writer.py
drafts.py

验收标准：

- process_question_pipeline 仍可作为兼容入口。
- DB 写入逻辑与 AI 丰富逻辑分离。
- Excel 导入不受影响。

# ============================================================ 最终输出要求

请按以下格式输出你的修改结果：

1. 本次完成了哪些任务
2. 修改了哪些文件
3. 每个文件的关键修改点
4. 是否存在与审计报告不一致的地方
5. 运行了哪些测试
6. 哪些测试通过，哪些失败
7. 仍未完成的任务
8. 下一步建议

如果某个任务风险较高，请不要强行修改，先说明原因，并给出最小安全改法。
