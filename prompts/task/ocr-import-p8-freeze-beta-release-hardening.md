# OCR 导题 P8 收口任务：功能冻结、真实试运行与发布前 Hardening

## 任务背景

P0～P7 已完成：

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
17. P6 已完成真实验收、性能 profile、失败归因、Dashboard 和 CI 策略。
18. P7 已完成观测沉淀、告警规则、cleanup、失败样本导出、运维页、preflight 和运维文档。

当前系统已经进入上线前阶段。P8 不再新增大功能，而是进行功能冻结、真实资料试运行、发布前检查、缺口修补和风险收口。

---

# 本轮总目标

P8 只做五件事：

```text
1. 功能冻结检查
2. 真实资料试运行
3. 发布前 Preflight 与回归验收
4. 安全 / 权限 / 清理 / resume 收口
5. 根据真实失败样本做小范围 bugfix
```

本轮不是重写 OCR pipeline，不换模型，不做大重构。

------

# 全局约束

请严格遵守：

1. 不新增大型 OCR 功能。
2. 不换 OCR 模型。
3. 不继续大拆 pipeline。
4. 不继续大拆 question_pipeline。
5. 不改小程序端主逻辑。
6. 不新增复杂数据库迁移。
7. 不缓存 LLM 输出。
8. 不根据主观感觉改规则。
9. 所有修复必须对应真实失败样本、测试失败或明确 bug。
10. 修复范围必须小。
11. 修复后必须补测试或更新 acceptance case。
12. 如果发现问题较大，先输出风险报告，不要强行重写。

------

# P8-1：功能冻结检查

## 目标

确认当前 OCR 导题系统已经进入功能冻结状态，后续只允许 bugfix 和样本驱动的小修。

## 需要检查

```text
backend/app/features/
backend/app/services/
backend/app/api/v1/admin_imports.py
admin-frontend/src/app/(admin)/imports/
docs/ocr/
tests/ocr_acceptance/
tests/ocr_regression/
```

## 输出要求

输出一份冻结清单：

| 模块 | 当前状态 | 是否冻结 | 允许改动类型 |
| ---- | -------- | -------- | ------------ |
|      |          |          |              |

至少覆盖：

```text
OCR extract
OCR correction
text_normalizer
question_splitter
math_image
table_markdown
ai_repair
complete/enrich
resume
artifact
ocr_cache
cleanup
alert
case_export
maintenance UI
preflight
acceptance
```

## 验收标准

1. 明确哪些模块冻结。
2. 明确哪些模块允许 bugfix。
3. 明确哪些模块禁止继续大改。

------

# P8-2：真实资料试运行

## 目标

用真实资料验证当前系统是否可以进入试运行。

## 试运行资料建议

至少准备以下本地样本，不强制提交仓库：

```text
1. 高数 PDF：50～100 页
2. 线代 / 概率统计 PDF：30～50 页
3. 408 PDF：50～100 页
4. 扫描图片：20～50 张
5. 水印资料：10～20 页
6. 多列选项资料：10～20 页
```

## 观察指标

每批导入后记录：

```json
{
  "total_questions": 120,
  "low_risk": 80,
  "medium_risk": 30,
  "high_risk": 10,
  "manual_review_rate": 0.33,
  "ai_answer_count": 3,
  "math_image_count": 18,
  "table_markdown_count": 6,
  "ocr_cache_hit_rate": 0.55,
  "slowest_stage": "ocr_correction",
  "alerts": [],
  "failed_stage": null,
  "duplicates_filtered": 0
}
```

## 重点验证

1. 低风险题能否批量通过。
2. 高风险题是否真的值得人工检查。
3. 公式截图是否可用。
4. 408 代码是否没有被 AI 改坏。
5. 表格题是否保留行列结构。
6. resume 是否不会重复入库。
7. cleanup dry-run 是否安全。
8. export-case 是否不会把 AI 答案写入 expected。
9. preflight 是否稳定输出 pass/warn/fail。

## 输出要求

输出试运行报告：

| 样本类型 | 页数/题数 | 低风险 | 需检查 | 高风险 | 主要失败类型 | 是否可接受 |
| -------- | --------- | ------ | ------ | ------ | ------------ | ---------- |
|          |           |        |        |        |              |            |

------

# P8-3：发布前 Preflight 与回归验收

## 目标

把发布前检查固定下来，确保上线前能稳定复现。

## 必须运行

```bash
python scripts/ocr_preflight_check.py --dry-run
pytest tests/ocr_regression
pytest tests/test_features/test_pipeline_e2e.py
pytest tests/test_features/test_pipeline_resume.py
pytest tests/test_features/test_pipeline_checkpoint.py
```

如果有本地真实样本：

```bash
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
```

如果改了前端：

```bash
cd admin-frontend
npm run typecheck
```

## 要求

1. preflight 允许缺少私有样本时 warning。
2. regression 必须通过。
3. resume / checkpoint 测试必须通过。
4. typecheck 必须通过。
5. 如果 acceptance strict 不通过，必须说明原因。

## 输出要求

输出：

| 命令 | 结果 | 失败原因 | 是否阻断发布 |
| ---- | ---- | -------- | ------------ |
|      |      |          |              |

------

# P8-4：安全、权限、cleanup、resume 收口

## 目标

上线前确认不会出现危险运维行为。

## 检查项

### 权限

```text
maintenance / cleanup / export-case / resume 接口必须仅 admin 可用
```

### cleanup

```text
dry-run 不删除文件
confirm=true 才允许真实删除
running / paused / failed-resumable artifact 不删除
```

### resume

```text
resume 不重复入库
resume 不重复发布
artifact 损坏时 fallback
```

### export-case

```text
expected_template 必须为空
raw_data 必须截断
不能导出完整 PDF / 图片
```

### alerts

```text
alert 缺字段不误报
import_failed 必须 error
高风险比例高必须 warning
```

## 验收标准

1. 相关接口有权限检查。
2. cleanup 安全。
3. resume 安全。
4. case export 安全。
5. alerts 不误报。

------

# P8-5：根据真实失败样本做小范围 bugfix

## 目标

只修真实试运行发现的问题。

## 允许修改范围

```text
backend/app/features/text_normalizer.py
backend/app/features/question_splitter.py
backend/app/features/visual_boundary_detector.py
backend/app/features/math_import_profile.py
backend/app/features/table_region_detector.py
backend/app/features/code_semantic_guard.py
backend/app/features/ocr_quality_gate.py
backend/app/features/ocr_alert_rules.py
backend/app/features/ocr_case_exporter.py
admin-frontend/src/app/(admin)/imports/
docs/ocr/
tests/
```

## 要求

1. 每个 bugfix 必须说明对应 failure_type。
2. 每个 bugfix 必须有测试或 acceptance case。
3. 不允许顺手重构。
4. 不允许大规模算法重写。
5. 不确定时只加 risk_flag，不自动修正文。

## 输出格式

| failure_type | 问题表现 | 修复文件 | 修复方式 | 新增测试 |
| ------------ | -------- | -------- | -------- | -------- |
|              |          |          |          |          |

------

# P8-6：上线候选状态判断

## 目标

最终给出是否可以进入试运行 / 上线候选。

## 判断标准

可以进入试运行：

```text
1. regression 全部通过
2. preflight 无 fail
3. typecheck 通过
4. cleanup dry-run 正常
5. resume 测试通过
6. 真实样本试运行没有阻断级问题
```

暂不进入试运行：

```text
1. resume 重复入库
2. cleanup 可能误删可恢复 artifact
3. 408 代码被 AI 改坏
4. 公式截图大面积失败
5. 高风险题比例异常高且无法解释
6. preflight 出现 fail
```

## 输出

```json
{
  "release_candidate": true,
  "status": "ready_for_beta",
  "blocking_issues": [],
  "warnings": [],
  "recommended_next_action": "进行小范围真实导题试运行"
}
```

------

# 测试要求

请至少运行：

```bash
python scripts/ocr_preflight_check.py --dry-run
pytest tests/ocr_regression
pytest tests/test_features/test_pipeline_e2e.py
pytest tests/test_features/test_pipeline_resume.py
pytest tests/test_features/test_pipeline_checkpoint.py
```

如果修改前端：

```bash
cd admin-frontend
npm run typecheck
```

如果有 acceptance 样本：

```bash
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
```

------

# 不做事项

本轮明确不做：

1. 不换 OCR 模型。
2. 不新增大功能。
3. 不继续大拆 pipeline。
4. 不继续大拆 question_pipeline。
5. 不改小程序端主逻辑。
6. 不缓存 LLM 输出。
7. 不新增复杂数据库迁移。
8. 不重写核心算法。
9. 不做没有真实失败样本支撑的优化。
10. 不自动生成 expected 答案。

------

# 最终输出格式

执行完成后，请输出：

## 1. P8 完成了哪些收口任务

逐项说明 P8-1 到 P8-6 是否完成。

## 2. 功能冻结清单

| 模块 | 是否冻结 | 后续允许改动 |
| ---- | -------- | ------------ |
|      |          |              |

## 3. 真实试运行结果

| 样本类型 | 页数/题数 | 低风险 | 需检查 | 高风险 | 主要失败类型 | 是否可接受 |
| -------- | --------- | ------ | ------ | ------ | ------------ | ---------- |
|          |           |        |        |        |              |            |

## 4. Preflight / 测试结果

| 命令 | 结果 | 是否阻断 |
| ---- | ---- | -------- |
|      |      |          |

## 5. 安全收口检查

| 项目 | 结果 | 说明 |
| ---- | ---- | ---- |
|      |      |      |

## 6. Bugfix 记录

| failure_type | 修复文件 | 测试 |
| ------------ | -------- | ---- |
|              |          |      |

## 7. Release Candidate 判断

输出：

```json
{
  "release_candidate": true,
  "status": "ready_for_beta",
  "blocking_issues": [],
  "warnings": [],
  "recommended_next_action": ""
}
```

## 8. 未完成事项

如果某项未完成，请说明原因。

## 9. 下一步建议

如果 P8 通过，下一步进入：

```text
1. 小范围真实导题试运行
2. 每周复盘 failure_type
3. 只做 bugfix，不做大改
4. 逐步冻结 OCR 导入主链路
```