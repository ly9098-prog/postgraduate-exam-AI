# OCR 导题 P6 改造任务：真实验收、性能 Profile 与失败样本精调

## 任务背景

P0～P5 已完成：

1. OCR 主路径统一。
2. 内存治理、PDF bytes 落盘释放、消除双 OCR。
3. OCR 清洗统一。
4. AI safety gate、风险字段、审核页风险展示。
5. 公式截图、表格 Markdown、原图对照、低风险批量通过。
6. 真实公式截图 URL 闭环。
7. 低风险跳过 AI repair。
8. PaddleOCR 结果缓存。
9. stage checkpoint、resume 接口、真 artifact resume。
10. review 幂等入库。
11. 导入质量报告与真实样本验收脚本。
12. token budget 统一。
13. complete → enrich 风险门禁。
14. pipeline_orchestrator.py 已渐进拆分到 pipeline_stages/。
15. question_pipeline.py 已拆出 AI complete / enrich / draft / import writer。
16. acceptance gates、代码语义 guard、多列选项优化、文档更新已完成。

现在不要继续堆功能，也不要继续大规模重构。P6 目标是：用真实资料验证当前系统，找出剩余失败类型，并做小范围精准修复。

---

# 本轮总目标

P6 只做五件事：

```text
1. 扩充真实高数 / 408 验收样本
2. 对真实导入流程做性能 profile
3. 建立失败样本自动归因报告
4. 基于真实失败样本做小范围精调
5. 在管理端展示导题质量趋势 / dashboard
```

本轮不是重写 OCR pipeline，不换模型，不做大重构。

------

# 全局约束

请严格遵守：

1. 不重写 OCR pipeline。
2. 不改变现有 API 行为。
3. 不改变已有字段含义。
4. 不改小程序端，除非只是兼容已有字段显示 bug。
5. 不新增大规模数据库迁移。
6. 不引入新的 OCR 模型。
7. 不缓存 LLM 输出。
8. 不绕过 P0～P5 已有 safety guard。
9. 所有优化必须基于真实验收样本或明确测试失败。
10. 不做“感觉上可能更好”的大改。
11. 修改完成后必须运行相关测试和验收脚本。

------

# P6-1：扩充真实验收样本集

## 目标

当前 acceptance 已有基础，但需要覆盖真实刷题导入场景。

## 修改目录

```text
tests/ocr_acceptance/
tests/ocr_regression/
```

## 新增或整理样本类型

至少覆盖：

```text
1. 高数 PDF：积分、极限、分式、矩阵、分段函数
2. 线代题：矩阵、行列式、向量、特征值
3. 概率统计：公式 + 表格混合
4. 408 C 代码题：指针、数组、结构体、循环
5. 408 操作系统表格题：进程调度、页表、段表
6. 408 计组题：Cache、地址映射、流水线表格
7. 408 计网题：路由表、子网划分
8. 多列选择题：左右栏选项、跨页选项
9. 水印 / 页眉页脚干扰题
10. 扫描质量差的图片题
```

## 要求

1. 不能用当前 pipeline 输出作为 expected。
2. expected 必须人工标注或人工确认。
3. 如果真实样本不能提交仓库，创建 ignored 本地样本目录模板。
4. 每个样本标注：
   - subject_type: math / code / table / mixed
   - expected_question_count
   - expected_answer_count
   - expected_math_image_count
   - expected_table_count
   - expected_code_blocks
   - known_risks
5. README 写清楚如何本地放置真实样本。

## 验收标准

1. 至少有 8 类样本模板。
2. acceptance runner 能读取这些样本。
3. 缺少本地真实文件时，不影响 CI。
4. 本地有样本时能输出验收报告。

------

# P6-2：性能 Profile

## 目标

找出真实导入耗时主要来自哪里，避免盲目优化。

## 需要检查 / 修改

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/pipeline_stages/
backend/app/services/ocr_service.py
backend/app/features/ai_repair.py
backend/app/features/question_ai_complete.py
backend/app/features/question_ai_enrich.py
backend/app/features/pipeline_artifacts.py
backend/app/services/ocr_cache_service.py
```

## Profile 指标

每个 pipeline stage 记录：

```json
{
  "stage": "math_detect",
  "duration_ms": 1234,
  "input_count": 120,
  "output_count": 120,
  "cache_hit": 30,
  "cache_miss": 70,
  "ai_calls": 5,
  "tokens_used": 12000,
  "memory_mb_peak": 512
}
```

至少覆盖：

```text
extract
normalize
ocr_correction
split
match
normalize_schema
math_detect
table_detect
repair
review
artifact_write
quality_report
```

## 输出位置

优先写入：

```text
diagnostics.performance_profile
quality_report.performance_summary
```

## 要求

1. Profile 默认开启轻量模式。
2. 不引入明显性能损耗。
3. 不记录敏感题目内容。
4. 不记录完整原始文本。
5. 支持导出 JSON。

## 验收标准

1. 每次导入能看到 stage 耗时。
2. 能看出 OCR cache 命中率。
3. 能看出 AI 调用次数。
4. 能看出最慢 stage。
5. 不影响原导入结果。

------

# P6-3：失败样本自动归因报告

## 目标

导入失败或验收不达标时，自动归因，避免人工看日志猜原因。

## 建议新增

```text
backend/app/features/ocr_failure_analyzer.py
tests/ocr_acceptance/failure_classifier.py
```

## 失败类型

至少分类：

```text
ocr_text_missing
question_count_mismatch
option_count_mismatch
answer_missing
answer_mismatch
math_formula_uncertain
math_image_missing
code_symbol_changed
table_structure_lost
multi_column_order_uncertain
watermark_noise_remaining
ai_answer_generated
ai_modified_sensitive_field
resume_duplicate_detected
artifact_restore_failed
ocr_cache_corrupted
```

## 输出结构

```json
{
  "case_id": "math_pdf_001",
  "status": "warn",
  "failure_types": [
    "math_image_missing",
    "answer_missing"
  ],
  "suggested_action": [
    "人工检查公式截图",
    "答案缺失，需核对原文"
  ],
  "affected_questions": [3, 8, 12]
}
```

## 要求

1. 与 risk_flags 体系兼容。
2. 不重复造一套完全独立的风险系统。
3. 可用于 acceptance report。
4. 可用于管理端质量报告。
5. 不影响正常导入。

## 验收标准

1. 验收失败时能输出失败类型。
2. 管理端质量报告能看到主要失败原因。
3. 失败分类能指导下一步修复。

------

# P6-4：基于真实失败样本做小范围精调

## 目标

只修真实样本暴露的问题，不做大范围猜测式优化。

## 允许修改的范围

```text
backend/app/features/text_normalizer.py
backend/app/features/question_splitter.py
backend/app/features/visual_boundary_detector.py
backend/app/features/math_import_profile.py
backend/app/features/table_region_detector.py
backend/app/features/code_semantic_guard.py
backend/app/features/ocr_quality_gate.py
```

## 常见小修方向

```text
1. 水印规则补充
2. 页眉页脚过滤补充
3. 多列选项排序阈值微调
4. 表格 Markdown 行列阈值微调
5. 数学公式候选识别阈值微调
6. code semantic guard 误报 / 漏报修正
7. 答案区域提取规则微调
8. OCR cache 损坏 fallback 细节修正
```

## 要求

1. 每个修复必须对应一个真实失败 case。
2. 每个修复必须新增或更新回归样本。
3. 不允许大规模改写核心算法。
4. 不确定时只加 risk_flag，不强行修正。
5. 修复前后要输出 case 对比。

## 验收标准

1. 至少修复 3 类真实失败。
2. 每类失败有对应 regression / acceptance case。
3. 不引入旧 case 回归。
4. 修复说明清楚。

------

# P6-5：管理端导题质量 Dashboard

## 目标

让管理员导入后快速判断这批题能否放心使用。

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
backend/app/api/v1/admin_imports.py
backend/app/services/admin_import_service.py
```

## 展示内容

基于已有 `quality_report` 和新增 performance / failure report 展示：

```text
本次导入题数
低风险 / 需检查 / 高风险
AI 答案数量
公式截图数量
表格数量
代码题数量
OCR cache 命中率
失败 / 警告类型 Top 5
最慢 stage
建议操作
```

## 示例 UI 文案

```text
本次导入 126 题：
- 低风险 84 题，可批量通过
- 需检查 31 题
- 高风险 11 题
- AI 答案 3 题，请重点核对
- 公式截图 22 个，2 个截图失败
- 表格 8 个，3 个需核对
- OCR 缓存命中率 62%
- 最慢阶段：ocr_correction，耗时 38s
```

## 要求

1. 只展示已有报告字段，不重新计算重逻辑。
2. 缺字段时 graceful fallback。
3. 不影响审核页性能。
4. 支持点击跳转高风险题筛选。
5. 不改小程序端。

## 验收标准

1. 管理端能看到导题质量概览。
2. 能一键跳到高风险题。
3. 能看到最慢 stage。
4. 能看到主要失败原因。
5. TypeScript 检查通过。

------

# P6-6：验收门槛与 CI 策略整理

## 目标

把 acceptance gate 从“能跑”变成“能指导发布”。

## 修改文件

```text
tests/ocr_acceptance/run_acceptance.py
tests/ocr_acceptance/README.md
.github/workflows/
```

如果没有 CI 配置，只更新 README 和命令。

## 策略

```text
PR / CI 默认：
  跑轻量 regression，不要求真实样本

本地发布前：
  跑 acceptance samples，输出 warn/fail

严格发布前：
  run_acceptance.py --strict
```

## 要求

1. CI 不依赖私有真实样本。
2. 本地真实样本目录默认 gitignored。
3. strict 模式可用于发布前检查。
4. README 写清楚三种模式。

## 验收标准

1. 开发者知道什么时候跑什么测试。
2. 不会因为缺少真实样本导致 CI 失败。
3. 发布前有明确验收命令。

------

# 测试要求

请至少运行：

```bash
pytest tests/test_features/test_pipeline_e2e.py
pytest tests/test_features/test_pipeline_resume.py
pytest tests/test_features/test_pipeline_checkpoint.py
pytest tests/ocr_regression
```

如果修改前端：

```bash
cd admin-frontend
npm run typecheck
```

如果修改 acceptance：

```bash
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
```

------

# 不做事项

本轮明确不做：

1. 不换 OCR 模型。
2. 不继续大拆 pipeline。
3. 不继续大拆 question_pipeline。
4. 不改小程序端。
5. 不缓存 LLM 输出。
6. 不做复杂表格 OCR 引擎。
7. 不新增复杂数据库迁移。
8. 不重写核心算法。
9. 不做没有真实失败样本支撑的优化。

------

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P6 任务

逐项说明 P6-1 到 P6-6 是否完成。

## 2. 修改了哪些文件

用表格列出：

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
|      |          |          |

## 3. 新增验收样本 / 模板

说明：

| 样本类型 | 路径 | 是否需要本地真实文件 | 指标 |
| -------- | ---- | -------------------- | ---- |
|          |      |                      |      |

## 4. Performance Profile 示例

输出示例 JSON。

## 5. Failure Analyzer 示例

输出示例 JSON。

## 6. Dashboard 字段

列出前端展示字段及来源。

## 7. 真实失败修复记录

| failure_type | 修复文件 | 对应 case | 修复策略 |
| ------------ | -------- | --------- | -------- |
|              |          |           |          |

## 8. 测试结果

输出实际运行命令和结果。

## 9. 未完成事项

如果某项任务未完成，请说明原因。

## 10. 风险和注意事项

说明是否影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- resume
- artifact
- OCR cache
- AI complete
- AI repair
- 管理端审核
- acceptance runner

## 11. 下一轮建议

下一轮优先考虑：

1. 生产环境观测与告警。
2. 定期清理 OCR cache / artifact。
3. 真实样本持续扩充。
4. 按失败类型定期小修。

