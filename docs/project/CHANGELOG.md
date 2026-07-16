# 变更日志

> 记录项目重大变更。

---

## 2026-07-16

- **多空选择题前端性能审计与修复（Phase 6 完成）**
  - **quiz-runner 局部 setData 优化**：observer 通过 `_lastRenderModel` 引用比较区分题目切换与空选项更新；选项点击仅更新 `_blankOptionGroups` 路径，避免重新解析题干、代码块和图片。
  - **多空选项点击优化**：practice.js 和 review-today.js 的 `selectBlankOption` 改用路径精确 setData，合并多次调用为一次，移除 `_updateComputedFields` 等多余回调。
  - **修复多空选择题部分选项无法点击**：修正 touch/swipe 事件竞争条件，`swipeTapLockUntil` 锁定时长从 300ms 降至 100ms，避免误吞合法点击。
  - **修复多空选择状态更新抖动**：消除 observer 中 `_renderModel` 因引用变化触发的重复解析，确保仅选项选中状态变更时不影响题干和图片渲染。
  - **图片显示优化**：`computeExtraImages` 使用 SEGMENTS 模式图片去重，`wx.previewImage` 数据在题目变化时预准备，选项点击不触发图片重载。
  - **真机验证**：practice（连续点击/切题/提交）、review-today（加载下一批/逐空作答）、wrong-detail（只读详情/图片预览）全部通过。
  - 受影响文件：
    - `miniprogram/components/quiz-runner/quiz-runner.js`
    - `miniprogram/pages/practice/practice.js`
    - `miniprogram/pages/review-today/review-today.js`
    - `miniprogram/utils/question-runner-adapter.js`
    - `miniprogram/utils/answer.js`
  - 受影响文档：`docs/project/CHANGELOG.md`
  - 测试：446 项全部 PASS（含多空专项 45 项），JS 语法验证通过

- **多空选择题完整支持（Phase 1-4 完成）**
  - ...

## 2026-07-16

- **多空选择题上线前审计与修复（Phase 5 完成）**
  - **代码审计修复 3 项 Bug**
    - `answer_matcher.py`: 修复 `extract_explicit_answer` 对多空选择题圈号答案（①B、②D）的验证，此前 validation regex 拒绝以非 A-D 开头的内容，导致 OCR 多空答案从未被提取。新增圈号格式检测分支。测试：3 项。
    - `question_pipeline.py`: 修复 `normalize_answer` 对显式标记为 `multi_blank_choice` 的题目答案未规范化到 canonical 格式（①:B;②:D），此前非 auto-detect 路径保持原始格式，导致前端 `normalizeBlankAnswer` 解析失败。新增专有分支调用 `parse_multi_blank_answer` + `serialize_multi_blank_answer`。测试：3 项。
    - `answer.js`: 修复 `normalizeBlankAnswer` 仅支持 `slot:value` 格式，新增圈号对（①B、②D）、括号数字（(1)B、(2)D）、中文自然语言（第1空B）三种 fallback 解析器。测试：5 项新增。
  - **回填脚本安全强化**
    - `_assess_candidate` 新增 `ambiguous` 状态：空位数与答案槽位数不一致时标记为歧义并跳过，不再信任 answer 槽位定义。
    - 新增 OCR 圈号差异安全归一化（1 ↔ ①，匿名 ↔ 显式），仅当数量一致时允许。
    - 新增 `答案值不在组选项中` 检查。
    - 新增 CLI 参数：`--question-id`、`--import-id`（定点检查）、`--report-json`（机器可读报告）、`--yes`（非交互确认）。
    - apply 模式新增交互确认（除非 `--yes`）。
    - 新增 `_build_report` / `_print_report` 输出完整统计：扫描数、候选数、转换数、歧义数、跳过数。
    - 新增第二次 dry-run 幂等性验证提示。
  - **数据验证脚本**
    - 新增 `scripts/verify_multi_blank_choice_data.py`：只读扫描 10 种风险类别（missing_groups, duplicate_group_id, missing_answer_slot, extra_answer_slot, invalid_answer_option, legacy_answer_format, options_groups_conflict, hash_mismatch, suspected_misclassified, blank_count_mismatch）。
    - 高风险问题存在时返回非零退出码。
    - 支持 JSON 报告输出。
  - **小程序 practice-result 逐空展示**
    - 新增 `buildBlankResultsViewModel` 函数：按 blank_option_groups 顺序生成逐空视图模型（id, userKey, userText, correctKey, correctText, isCorrect, isAnswered）。
    - 逐空显示：错误状态高亮用户选错、未作答显示"未作答"、全部正确时显示"全部正确"。
    - 展示"答对 X/Y 空"统计。
    - WXML 新增 conditional 分支：`item._isMultiBlank` 触发多空布局。
    - WXSS 新增 80+ 行多空样式（圆角卡、颜色编码、状态标记）。
    - practice-result.js 内联 `normalizeBlankAnswer` 兼容 canonical 和圈号对格式。
  - **本地数据库回填演练说明**
    - 脚本已通过 Python 语法和导入验证
    - `_assess_candidate` 全部安全校验逻辑已在 Python 层测试通过
    - 执行完整回填需连接真实数据库（开发/测试环境），当前无可用 SQLite 测试数据库
  - **回归测试**
    - 后端 multi_blank_choice 专项：98 项全 PASS
    - 后端 service tests：1908 passed, 3 skipped
    - 后端 API tests：261 passed
    - 小程序 multi-blank 测试：45 项全 PASS
    - 后端 feature tests：12+ passed
  - **Runbook**
    - 新增 `docs/project/MULTI_BLANK_CHOICE_RELEASE_RUNBOOK.md`：发布前条件、数据库备份、部署顺序、回填 dry-run/apply/验证/幂等检查、API smoke test、小程序验收、监控、回滚步骤、禁止命令。
  - 审计发现的问题：3 项（均为 Bug）
  - 实际修复的问题：3 项（answer_matcher, question_pipeline, answer.js）
  - 受影响文件：
    - `backend/app/features/answer_matcher.py`
    - `backend/app/features/question_pipeline.py`
    - `backend/scripts/backfill_multi_blank_choice.py`
    - `backend/scripts/verify_multi_blank_choice_data.py`（新增）
    - `miniprogram/utils/answer.js`
    - `miniprogram/pages/practice-result/practice-result.js`
    - `miniprogram/pages/practice-result/practice-result.wxml`
    - `miniprogram/pages/practice-result/practice-result.wxss`
    - `miniprogram/tests/test-multi-blank-answer.js`
    - `backend/tests/test_services/test_multi_blank_choice.py`
    - `docs/project/CHANGELOG.md`
    - `docs/project/MULTI_BLANK_CHOICE_RELEASE_RUNBOOK.md`（新增）
  - 尚存风险：
    - 本地数据库回填演练因无可用的 SQLite 开发数据库无法执行；需在测试/开发 PostgreSQL 实例上运行 dry-run + apply + 二次 dry-run 完整流程
    - practice-result 页面使用内联 normalizeBlankAnswer 而非 answer.js 的版本（微重复）
    - wrong-detail 页尚未验证 per-blank 展示
  - **Phase 1 — 后端数据契约、答案解析、判题**
    - 新增 `backend/app/features/multi_blank_choice.py`：统一工具模块，提供 `extract_blank_slots`、`parse_multi_blank_answer`、`serialize_multi_blank_answer`、`build_blank_option_groups`、`validate_multi_blank_question`、`detect_shared_option_multi_blank`。
    - 答案兼容 12+ 种格式（canonical `①:B;②:D`、`①B、②D`、`第1空B`、位置型 `A,B` 等）。
    - 精确判题：槽位覆盖检查 + 多余槽位拒绝 + 顺序无关。
    - 发布校验：缺/多余槽位、非法选项、空组全部拒绝。
    - Hash 包含 `blank_option_groups`（`normalize_hash_blank_groups` 方法）。
    - 92 项单元测试通过。
  - **Phase 2 — 导入识别、审核与发布**
    - 导入管线自动检测共享选项多空题（2+ 空 + 选项 + 多槽位答案）。
    - `answer_matcher.py` 新增 `①B、②D` OCR 答案格式。
    - `admin_import_service.py` 保存时自动重建 `blank_option_groups`。
    - 管理端审核 UI：逐空选项按钮、可编辑选项文本、canonical answer 保存。
  - **Phase 3 — 小程序答题体验**
    - `answer.js`：`isAnswerCorrect` 拒绝多余槽位。
    - `practice.js`：`selectBlankOption` 使用 `isQuestionAnswered` 修正部分作答误标。
    - 小程序纯函数测试 37 项（parse/serialize/判题/多余槽位/旧格式兼容）。
  - **Phase 4 — 历史数据修复、端到端测试、文档**
    - `scripts/backfill_multi_blank_choice.py`：幂等回填脚本，扫描 `question_imports` + `questions` 中误分类的多空题（dry-run / apply）。
    - 端到端管道测试 22 项（11 用例矩阵 + 数据契约验证）。
  - 数据契约：`question_type=multi_blank_choice`、`options=null`、`parsed_options=null`、`answer="①:B;②:D"`、`content.blank_option_groups=[{"id":"①","options":[...]}]`。
  - 受影响文件：`backend/app/features/multi_blank_choice.py`（新增）、`backend/scripts/backfill_multi_blank_choice.py`（新增）、`backend/app/features/answer_matcher.py`、`backend/app/features/question_pipeline.py`、`backend/app/services/admin_import_service.py`、`backend/app/features/question_publish_service.py`、`admin-frontend/src/app/(admin)/imports/review/page.tsx`、`miniprogram/utils/answer.js`、`miniprogram/pages/practice/practice.js`、`miniprogram/tests/test-multi-blank-answer.js`（新增）。
  - 受影响文档：`docs/project/CHANGELOG.md`。## 2026-06-22

- **修复：OCR 代码块围栏断裂导致代码结构泄漏（BUG-001）**
  - `code_detector._fence_code_blocks()` 新增单行桥接规则：孤立低分行（score=0）相邻两行均为代码行（score≥1）时提升为 score=1，防止 OCR 单行乱码导致 ``` 围栏提前关闭。
  - 修改仅限 `code_detector.py` 5 行，不涉及 OCR 管线、清洗规则、code_integrity、AI repair。
  - 22 个 OCR 回归测试全部 PASS，实际图片端到端验证通过。
  - 受影响文件：`backend/app/features/code_detector.py`。
  - 受影响文档：`docs/BUGS.md`、`docs/BUGS_HISTORY.md`、`docs/project/CHANGELOG.md`。

## 2026-06-21

- **P8 功能冻结 + 回归加固 + 部署验证 + 种子数据完成**
  - 功能冻结检查：18 个模块全部冻结，仅允许 bugfix。
  - 回归测试加固：新增 52 个测试（ocr_alert_rules 28 tests + ocr_case_exporter 24 tests），覆盖 P7 新增模块。
  - pipeline_artifacts assertion 修复：cleanup_expired 返回值结构变更导致测试断言错误已修正。
  - 生产部署验证：5 容器健康 / 新模块加载正常 / HTTPS 可达 / API 端到端通过。
  - 清理 Dry-Run：scanned=18, would_delete=0，无异常。
  - subjects 种子数据：插入 10 条学科记录（4 一级 + 6 二级）。
  - Release Candidate 判断：`ready_for_beta`，无阻断问题。
  - 受影响文件：`backend/app/features/pipeline_artifacts.py`、`tests/test_pipeline_artifacts.py`、`tests/test_features/test_ocr_alert_rules.py`、`tests/test_features/test_ocr_case_exporter.py`。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P7 生产运维 — 观测沉淀 + 告警 + 清理 + 样本导出 + 运维文档完成**
  - 观测指标沉淀：`GET /imports/pipelines` 端点，API 层聚合 quality_report，无 DB migration。
  - 告警规则：`ocr_alert_rules.py` 7 条规则（import_failed / high_risk / manual_review / ai_answer / cache_hit / duration / ocr_fail），pipeline 完成自动评估。
  - 清理任务：OCR cache TTL 14d + artifact dry-run + 统一 `POST /maintenance/cleanup` 端点。
  - 失败样本导出：`ocr_case_exporter.py` raw_data 截断 2000 字符 + expected_template 全部为空 + 单题/批量端点。
  - 管理端运维页：健康摘要 + 告警展示 + Dry-Run/确认清理 UI + layout 新增"运维" tab。
  - Preflight 检查：`scripts/ocr_preflight_check.py` 离线 5 项 + 可选在线 3 项。
  - 运维文档：`docs/ocr/OPERATIONS.md` + `TROUBLESHOOTING.md` + `DEPLOY_CHECKLIST.md`。
  - 受影响文件：`backend/app/features/ocr_alert_rules.py`（新增）、`backend/app/features/ocr_case_exporter.py`（新增）、`backend/app/api/v1/admin_imports.py`、`scripts/ocr_preflight_check.py`（新增）、`admin-frontend/src/app/(admin)/imports/maintenance/page.tsx`（新增）。
  - 受影响文档：`docs/ocr/*`、`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P6 验收 + 性能 Profile + 失败归因 + 精调 + Dashboard + CI 策略完成**
  - 验收样本扩充：10 类样本模板（高数/线代/概率统计/408 代码/408 表格/多列/水印/计网/OS），含 case.json 元数据。
  - 性能 Profile：`PipelineStage` 内置 input_count/output_count/cache_hit/cache_miss/ai_calls/tokens_used，聚合到 diagnostics。
  - 失败自动归因：`ocr_failure_analyzer.py`（772 行）16 种失败分类 + 11 checker 函数。
  - 小范围精调：text_normalizer 扩充教育品牌水印 + 中文页码行过滤，code_detector 扩充 408 C/C++ 数据结构关键词。
  - 管理端 Dashboard：tasks 页面新增质量概览卡片（风险分布/AI 答案/公式截图/性能概览/高风险跳转）。
  - 三级测试策略：acceptance runner 支持 --strict 模式，CI 不依赖真实样本。
  - 受影响文件：`backend/app/features/ocr_failure_analyzer.py`（新增）、`backend/app/features/text_normalizer.py`、`backend/app/features/code_detector.py`、`admin-frontend/src/app/(admin)/imports/tasks/page.tsx`。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P5 管线拆分完成**
  - P5-2：`pipeline_orchestrator.py` 渐进拆分 → 7 个 `pipeline_stages/` 模块（match/math_detect/table_detect/normalize_schema/repair/review），文件行数 4454→4081。
  - P5-3：`question_pipeline.py` 拆出 4 个子模块（question_ai_complete.py / question_ai_enrich.py / question_draft_generator.py / question_import_writer.py），保留全部向后兼容重导出。
  - Qwen 清除：删除 qwen_adapter.py（309 行），路由链简化为 PaddleOCR-VL → DeepSeek → Rule。
  - Vision 消费端落地：添加 feature="vision" 到 FEATURE_VALUES + admin UI；pipeline _run_extract 接入 resolve_active_model(feature="vision") 作为 PaddleOCR-VL 回退。
  - 受影响文件：`backend/app/features/pipeline_stages/*`（新增）、`backend/app/features/question_ai_complete.py`（新增）、`backend/app/features/question_ai_enrich.py`（新增）、`backend/app/features/question_draft_generator.py`（新增）、`backend/app/features/question_import_writer.py`（新增）、`backend/app/features/ocr_fix/qwen_adapter.py`（删除）。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

## 2026-06-20

- **P4 真断点恢复 + 幂等入库 + 导题验收报告完成**
  - 新增 `pipeline_artifacts.py` 提供文件级 artifact 存储（`.backend_cache/pipeline_artifacts/{pipeline_id}/`），支持 split / normalize_schema / repair / math_detect / table_detect / review 共 6 种 artifact 类型。
  - 真断点恢复：resume 时自动检测 artifact，从 normalize_schema / repair / math_detect / table_detect 恢复 questions，跳过已完成 stage，不再重跑 OCR 和 AI 修复。
  - 幂等入库：`submit_to_review` 通过 `subject + question_hash` 全库去重，`duplicates_filtered` 写入 review_commit diagnostics。
  - 导入质量报告：`_build_quality_report()` 在 pipeline 完成后输出风险分布 / AI 答案 / 公式截图 / 表格 / 缓存 / 去重统计，通过 `quality_report` 字段返回。
  - 清理策略：新增 `POST /cleanup/expired` 端点（completed: 24h, failed: 7d），artifact 目录写入 `.completed` / `.failed` marker。
  - 验收脚本：`tests/ocr_acceptance/run_acceptance.py` 支持真实样本验收。
  - artifact store 单元测试 18 项通过。
  - 受影响文件：`backend/app/features/pipeline_artifacts.py`（新增）、`backend/app/features/pipeline_orchestrator.py`、`backend/app/api/v1/admin_imports.py`、`backend/app/schemas/import_review.py`、`tests/test_pipeline_artifacts.py`（新增）。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`、`prompts/task/ocr-import-p4-true-resume-idempotency-acceptance.md`。

## 2026-06-18

- **修复：`_extract_stem()` 无选项时误剥离圈号前缀行**
  - `question_normalizer.py` 中 `_extract_stem()` 的 `_OPTION_LINE_RE` 缺少 `option_lines` 前置守卫，当上游未检测到选项时仍匹配 `① A. n + 1` 类行并从题干中剥离。
  - 修复：在 `_OPTION_LINE_RE.match()` 前增加 `option_lines and` 守卫。
  - `test_partial_missing` 测试数据补齐 Q1 完整 A/B/C/D 选项。
  - 新增 `test_cross_path_consistency()` 跨路径一致性冒烟测试，防止两条标准化路径（Path A: module-level `normalize_question()` / Path B: `QuestionNormalizer.normalize()`）功能发散。
  - 受影响文件：`app/features/question_normalizer.py`、`tests/test_services/test_question_normalizer.py`、`tests/test_question_pipeline.py`。
  - 受影响文档：`docs/ai/STANDARDIZATION_FLOW.md`、`docs/project/CHANGELOG.md`。

## 2026-06-10

- **AI 解析设置页面 — 配置接口实施完成**
  - 新增 `AdminAiModelConfig` 表（`admin_ai_model_configs`）：模型配置，API key 使用 Fernet 加密存储。
  - 新增 `AdminAiConfig` 表（`admin_ai_configs`）：键值对配置表，存储 17 个 AI Prompt / OCR / 补全策略配置项。
  - 新增 `GET /api/admin/v1/ai-models` — 模型列表（不含 api_key，含 `api_configured: bool`）。
  - 新增 `PATCH /api/admin/v1/ai-models/{id}` — 更新模型字段（api_key="****" 时不修改，设为 default 时自动清除其他 default）。
  - 新增 `GET /api/admin/v1/ai-configs` — 扁平 JSON 键值对读取。
  - 新增 `PATCH /api/admin/v1/ai-configs` — 部分更新（不存在的 key 忽略，prompt 字段 max_length=5000）。
  - 权限控制：使用已有 `ai_setting:read` / `ai_setting:write` 权限。
  - 审计日志：PATCH 操作记录 `severity=normal`，action=`ai_config.update` / `ai_model_config.update`。
  - 前端 ModelCards / OcrAccordion / AiCompletionPreview 三个组件对接后端 API，骨架屏加载态、错误态保留上次数据。
  - 模型卡片提示"当前版本实际使用模型为 DeepSeek V4 Flash，此处配置仅作为记录"；配置区域提示"配置已保存，将在后续版本中生效"。
  - 修复：prompt 字段 max_length=5000 校验、TypeScript 类型修正、文案修正 (DeepSeek → DeepSeek V4 Flash)、错误态保留上次值、配置区域提示文案补全。
  - 受影响文档：`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md`、`docs/admin/ADMIN_ARCHITECTURE.md`、`docs/project/CHANGELOG.md`。

## 2026-06-02

- **真实题库相似匹配纠错层接入导入管线**
  - 新增 `backend/app/features/similarity_matcher.py`，位于 repair 与 review 之间。
  - 加载同科目已有正式题目，使用 difflib 计算相似度比率，阈值 >= 0.85 时附加 `similarity_suggestion` 字段。
  - 仅作为建议，不自动覆盖或纠正，结果供人工审核参考。
  - `pipeline_orchestrator` 已插入 `similarity_match` 阶段并输出诊断信息。
  - 19 项回归测试通过。
  - 提交：`affa30e feat: add similarity matching correction layer to import pipeline`。
  - 变更原因：为 OCR 导入提供基于已有题库的相似题建议，提升人工审核效率。

- **AI OCR Correction Layer 接入导入管线**
  - 新增 `backend/app/features/ocr_correction.py`，位于 `normalize_text` 与 `analyze_structure` 之间。
  - 自动检测 OCR 噪声信号（乱码字符、短行、缺失题号、选项碎片化），噪声超阈值时调用 DeepSeek AI 修复。
  - 使用独立 token budget，auto 模式下仅在检测到噪声时触发，AI 不可用时静默降级。
  - `pipeline_orchestrator` 已插入 `ocr_correction` 阶段并输出诊断信息。
  - 新增 `ocr_correction` system prompt（`backend/app/ai/prompts.py`）。
  - 20 项回归测试通过。
  - 提交：`e88a33b feat: add AI OCR Correction Layer to import pipeline`。
  - 变更原因：提升 OCR 导入成功率，修复换行错乱、选项错位、题号缺失等噪声问题。

- **OCR 结构分析接入导入主链路完成**
  - `DocumentStructureAnalyzer` 已接入图片导入管线，结构结果会传给 `split_questions(..., structure=structure)` 与 `match_answers(..., structure=structure)`。
  - `SEPARATED` 场景下，切题阶段会跳过纯答案页，避免答案页被重新切成假题目。
  - `answer_pages` 统一返回真实页码 `page`，不再使用 `block_index`，以便答案匹配与页码语义一致。
  - 结构分析补齐空输入诊断字段：`diagnostic_reason`、密度统计、OCR 噪声计数与布尔型存在标记。
  - 相关回归测试已补充并通过。
  - 变更原因：同步已完成的 OCR 结构分析与导入链路增强；本次仅更新文档，不改业务代码。

## 2026-06-01

- **OCR 图片导入诊断与失败分类完成**
  - 图片上传入队前校验 `OCR_ENABLED` 与 PaddleOCR 依赖可用性，避免后台任务延迟失败。
  - 图片导入状态保留 OCR 运行时诊断、原始/清洗文本预览、长度/行数差值、OCR stats 与切题诊断。
  - 切题诊断新增 `normalized_block_count`、`text_block_count`、`raw_question_count`、`raw_questions_preview`、`failure_reason`，fallback 区分 `text_present_but_no_question_boundary` / `no_text_blocks` 并标记 `fallback_created`。
  - 图片管线失败分类为 `ocr_empty_text`、`text_present_but_split_failed`、`missing_options`、`pipeline_failed`，审核边界不变：仍全部进入 `question_imports` 后人工确认。
  - 变更原因：同步已完成的 OCR image import diagnostics classification；本次仅更新文档，不改业务代码。

- **OCR 图片导入可靠性 P0/P1 完成**
  - 图片导入状态响应现在会返回 OCR 诊断与切题诊断：原始/清洗后文本长度、行数、预览、长度差值；清洗后为空时会标记 `ocr_empty_after_cleaning`。
  - 管线在“有规范化文本但找不到题号边界”时会生成低置信度 fallback 审核项，避免整批静默丢失。
  - 题目切分增强支持圈号前缀选项、紧凑 inline 选项与连续题号边界识别，文本标准化会更保守地保留结构化选项行。
  - OCR 图像预处理补充 `ImageOps.exif_transpose()`，减少手机拍照方向异常导致的识别偏差。
  - 变更原因：同步已完成的图片导入可靠性增强与回归验证结果；本次仅更新 OCR / 导入相关文档，不改业务代码或测试。

## 2026-05-31

- **文档整理与关键文档同步**
  - 对齐 `CLAUDE.md` 与当前 docs 索引，明确 App 仍坚持微信 openid + JWT、无传统账号系统；Admin RBAC 属于后台管理域，不改变 App 登录模型。
  - 同步 `question_imports` 当前字段：审核元数据、AI 辅助导题字段与数学公式图片化 `math_regions`，并强调 AI 结果必须进入暂存区人工审核。
  - 同步 AI 学习引擎端点：`/ai/explain`、`/ai/recommend`、`/ai/report`、`/ai/analyze-mistake`，记录 token 限额与基础 AI 服务剩余缺口。
  - 更新 OCR/导入文档中 Level 1 题目去重与文件级去重边界，避免把已实现题目 hash 去重误写成未实现。
  - 未删除文档：本次未发现可在当前证据下安全删除且不影响索引的明确冗余文档；保留不确定文档并通过索引限定用途。
  - 变更原因：执行 docs 目录整理任务，优先编辑现有关键文档，不修改业务/配置/测试代码。

- **Redis-backed 图片导入状态完成**
  - `GET /api/v1/import/pipelines/{pipeline_id}` 按 legacy `get_pipeline_status` → Redis `import:image:pipeline:{pipeline_id}` → 同进程 `_image_pipeline_store` 查询，只有 legacy 与 image 状态都缺失时返回 404。
  - 图片状态写入先更新内存，再 best-effort 写入 Redis，TTL 86400 秒；Redis 支持跨 worker 短期状态共享与 TTL 内重启恢复。
  - `REDIS_URL` 未配置或 Redis 不可用时回退为同进程内存状态，不保证跨 worker / 重启恢复。
  - 图片导入终态为 `completed` / `failed`，非终态包括 `queued` / `ocr_running` / `parsing`；前端仅应在终态停止轮询。
  - 生产 Docker Compose 默认注入 `REDIS_URL=redis://redis:6379/0`。
  - 变更原因：同步已完成的 Redis-backed image import status 实现；受影响文档为 `docs/backend/API_SPEC.md`、`docs/architecture/OCR_FLOW.md`、`docs/ai/OCR_STRATEGY.md`。

## 2026-05-30

- **题库 Level 1 完全重复检测完成**
  - 导入阶段 `question_imports` 新增 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id` 字段；正式题库 `questions` 新增 `question_hash`。
  - 发布 / 审核通过阶段按 `subject + question_hash` 做完全匹配拦截，避免重复题进入正式题库。
  - 新增 Alembic migration `j1f2a3b4c5d6_add_duplicate_question_hash_fields.py`，并补充启动补列逻辑。
  - 审核队列、批次详情与 admin import schema 返回重复相关字段；日志统一使用 `[DuplicateCheck]`。
  - 变更原因：同步题库去重已实现状态；受影响文档为 `docs/backend/DB_SCHEMA.md`、`docs/ai/STANDARDIZATION_FLOW.md`、`docs/architecture/OCR_FLOW.md`、`docs/backend/API_SPEC.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/REVIEW_FLOW.md`。

- **Admin Phase 7: 后台 AI 解析设置与全局月度额度完成**

- **Admin Phase 6: Next.js Admin Dashboard 前端主要实现完成**
  - 新增 `admin-frontend`，使用 Next.js 16、React 19、React Query、TanStack Table、Zustand、Recharts 与 Tailwind CSS 4。
  - 页面覆盖 `/dashboard`、`/login`、`/app-users`、`/admin-users`、`/questions`、`/review`、`/roles`、`/audit-logs`。
  - Phase 6 前端仅消费 `/api/admin/v1`，不修改后端 API、DB schema 或权限语义。
  - 修复 build/lint 问题，并同步 audit-log 查询参数别名：`pageSize`、`resourceType`、`from`、`to`。
  - 已通过 `npm --prefix admin-frontend run lint` 与 `npm --prefix admin-frontend run build`。
  - 变更原因：同步 Admin Phase 6 前端实现状态与文档边界；受影响文档为 `docs/admin/README.md`、`docs/admin/PHASE_PLAN.md`、`docs/frontend/ADMIN_UI_RULES.md`。

## 2026-05-29

- **Admin Phase 5: 审计日志与统计后端完成**
  - 新增 `GET /api/admin/v1/audit-logs` 与 `GET /api/admin/v1/audit-logs/{id}`，支持多维过滤、分页、默认近 183 天与 1 年跨度限制。
  - 新增 `GET /api/admin/v1/dashboard/overview`、`/daily`、`/questions-stats`，覆盖总览、每日趋势与题目分布统计。
  - Dashboard overview 使用现有 FastAPI `app.core.cache`，支持 TTL 抖动与防穿透锁；Redis 不可用时降级直查 DB。
  - 变更原因：同步 Admin Phase 5 后端实现状态与实际 FastAPI/SQLAlchemy 方案；受影响文档为 `docs/admin/*` API、审计日志与 Redis 规划。

## 2026-05-24

- **Stage 11: 刷题系统重构** — PracticeRecord 从会话级改为逐题记录
  - 新增 `GET /practice/questions` 支持随机/顺序模式 + 知识点筛选
  - 新增 `POST /practice/submit` 单题提交（大小写不敏感判题）
  - 新增 `POST /practice/batch-submit` 批量提交
  - 新增 `GET /practice/stats` 刷题统计（含连续天数）
  - 新增 `GET /questions/{id}/detail` 含答案详情（答后可见）
  - 答错自动同步错题本，错题重做触发 SM-2 更新
  - 小程序刷题页支持随机/顺序模式切换
- 文档结构重构：将 `/docs` 和 `/prompts` 按职责分类，建立 AI 工程化文档体系
- 新增导入管线开发 Prompt（stage1-9）
- 新增 features/ 目录架构设计

## 2026-05-22

- CURRENT_ARCHITECTURE.md 基于代码真实状态更新
- 记录 API 端点总数（47个）和已知技术债务

## 更早

- MVP 核心功能开发完成
- 各阶段开发文档归档到 `docs/achieve/`
