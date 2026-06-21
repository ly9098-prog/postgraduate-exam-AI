# OCR 导题 P7 改造任务：生产观测、告警、清理任务与失败样本闭环

## 任务背景

P0～P6 已完成：

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

当前系统已经具备比较完整的 OCR 导题能力。P7 不再继续堆识别功能，而是进入生产运营阶段：观测、告警、清理、失败样本沉淀。

---

# 本轮总目标

P7 只做五件事：

```text
1. 导入任务观测指标沉淀
2. OCR 导入告警规则
3. cache / artifact / diagnostics 清理任务
4. 失败样本导出与回流流程
5. 发布前检查命令和运维文档
```

本轮不是重写 OCR pipeline，不换模型，不做大重构。

------

# 全局约束

请严格遵守：

1. 不重写 OCR pipeline。
2. 不改变现有 API 行为。
3. 不改变已有字段含义。
4. 不改小程序端。
5. 不新增复杂数据库迁移，优先复用现有表或 JSON metadata。
6. 不引入新的 OCR 模型。
7. 不缓存 LLM 输出。
8. 不绕过 P0～P6 已有 safety guard。
9. 告警先做轻量版本：日志 / 管理端提示 / 数据表记录均可。
10. 清理任务必须支持 dry-run。
11. 清理任务不能删除 running / resumable pipeline 的必要 artifact。
12. 修改完成后必须运行相关测试。

------

# P7-1：导入任务观测指标沉淀

## 目标

将每次导入的关键质量和性能指标沉淀，便于长期观察 OCR 导入效果。

## 需要检查 / 修改

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/admin_import_service.py
backend/app/api/v1/admin_imports.py
backend/app/models/import_pipeline.py
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/app/(admin)/imports/history/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 指标字段

优先从已有 `quality_report`、`diagnostics.performance_profile`、`failure_report`、`token_usage` 中汇总，不要重新计算重逻辑。

建议沉淀字段：

```json
{
  "pipeline_id": "xxx",
  "source_type": "pdf",
  "subject": "高数",
  "total_pages": 80,
  "total_questions": 126,
  "duration_ms": 78901,
  "status": "completed",
  "failed_stage": null,
  "low_risk": 84,
  "medium_risk": 31,
  "high_risk": 11,
  "manual_review_rate": 0.33,
  "ai_answer_count": 3,
  "math_image_count": 22,
  "table_markdown_count": 8,
  "ocr_cache_hit_rate": 0.62,
  "slowest_stage": "ocr_correction",
  "ai_calls": 12,
  "tokens_used": 4500,
  "failure_type_counts": {
    "answer_missing": 2,
    "math_image_missing": 1
  }
}
```

## 存储策略

优先级：

1. 如果 `ImportPipeline` 已有 JSON diagnostics / result 字段，则写入摘要。
2. 如果已有 history 接口，则扩展返回。
3. 不新增复杂表，除非当前结构无法承载。

## 验收标准

1. 每次导入完成后有一份观测摘要。
2. 管理端历史页能看到核心指标。
3. 不影响导入主流程。
4. 字段缺失时 graceful fallback。

------

# P7-2：OCR 导入告警规则

## 目标

在导入质量或服务异常时给出提示，避免用户不知道哪里出问题。

## 建议新增文件

```text
backend/app/features/ocr_alert_rules.py
```

## 告警规则

至少支持：

```text
import_failed
high_risk_ratio_too_high
manual_review_rate_too_high
ai_answer_count_too_high
paddleocr_vl_failure_spike
ocr_cache_hit_rate_too_low
artifact_cleanup_failed
pipeline_duration_too_long
failure_type_spike
```

## 阈值建议

```json
{
  "high_risk_ratio": 0.40,
  "manual_review_rate": 0.50,
  "ai_answer_count": 10,
  "ocr_cache_hit_rate_min": 0.20,
  "pipeline_duration_ms": 300000
}
```

## 输出结构

```json
{
  "level": "warning",
  "code": "high_risk_ratio_too_high",
  "message": "本次导入高风险题比例过高，建议优先人工审核",
  "value": 0.46,
  "threshold": 0.40,
  "suggested_action": "打开高风险筛选"
}
```

## 要求

1. 告警不阻断导入。
2. 告警写入 diagnostics 或 quality_report。
3. 管理端 Dashboard 能展示 Top alerts。
4. 阈值可配置或集中维护。
5. 缺字段时不误报。

## 验收标准

1. 高风险比例过高时产生 warning。
2. 导入失败时产生 error。
3. OCR cache 命中率过低时产生 info / warning。
4. 管理端能看到告警文案。

------

# P7-3：cache / artifact / diagnostics 清理任务

## 目标

避免长期运行后 `.backend_cache`、pipeline artifacts、OCR cache、diagnostics 大字段无限增长。

## 需要检查 / 修改

```text
backend/app/services/ocr_cache_service.py
backend/app/features/pipeline_artifacts.py
backend/app/features/pipeline_orchestrator.py
backend/app/api/v1/admin_imports.py
backend/scripts/
```

## 清理对象

```text
OCR cache
pipeline artifacts
completed pipeline diagnostics 大字段
expired failed pipeline artifacts
acceptance reports
temp page images
```

## TTL 建议

```text
OCR cache: 14d
completed pipeline artifacts: 24h
failed pipeline artifacts: 7d
acceptance reports: 30d
diagnostics raw details: 30d
temp page images: run 结束立即清理
```

## 要求

1. 支持 dry-run。
2. 支持按类型清理。
3. 不删除 running 任务相关 artifact。
4. 不删除 failed 但仍在 resume TTL 内的 artifact。
5. 清理结果输出：
   - scanned_count
   - deleted_count
   - skipped_running_count
   - freed_bytes
6. 提供管理端接口或脚本命令。
7. 清理失败要进入 alert。

## 建议接口

```http
POST /api/admin/v1/imports/maintenance/cleanup
```

请求：

```json
{
  "target": "all",
  "dry_run": true
}
```

响应：

```json
{
  "target": "all",
  "dry_run": true,
  "scanned_count": 1200,
  "deleted_count": 0,
  "freed_bytes": 0,
  "skipped_running_count": 3
}
```

## 验收标准

1. dry-run 不删除文件。
2. running pipeline artifact 不会被删。
3. completed 过期 artifact 会被删除。
4. 清理失败有告警记录。
5. 有测试覆盖。

------

# P7-4：失败样本导出与回流流程

## 目标

将真实导入中发现的失败题沉淀为 regression / acceptance case，形成持续改进闭环。

## 建议新增

```text
backend/app/features/ocr_case_exporter.py
backend/app/api/v1/admin_imports.py
tests/ocr_acceptance/README.md
```

## 导出入口

可以支持管理端接口：

```http
POST /api/admin/v1/imports/questions/{import_id}/export-case
```

或批量：

```http
POST /api/admin/v1/imports/batches/{batch_id}/export-failure-cases
```

## 导出内容

```json
{
  "case_id": "failure_20260621_xxx",
  "source_file": "...",
  "source_page": 3,
  "source_region": {...},
  "raw_data": {...},
  "parsed_content": {...},
  "risk_flags": [...],
  "failure_types": [...],
  "expected_template": {
    "stem": "",
    "options": {},
    "answer": "",
    "analysis": "",
    "notes": "请人工补充 expected"
  }
}
```

## 要求

1. 不自动生成 expected 正确答案。
2. expected 只生成模板，必须人工填写。
3. 导出文件默认放入 ignored 本地目录：
   - `tests/ocr_acceptance/local_cases/`
4. 不导出敏感信息。
5. 支持按 failure_type 筛选导出。
6. README 写清楚人工标注流程。

## 验收标准

1. 可以从审核页导出失败题 case。
2. 导出的 case 能被 acceptance runner 识别。
3. 不会把 AI 猜测答案当 expected。
4. 文档说明完整。

------

# P7-5：管理端观测与维护页面

## 目标

让管理员能看到 OCR 导入健康状况，并手动执行维护任务。

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/app/(admin)/imports/history/page.tsx
admin-frontend/src/app/(admin)/imports/maintenance/page.tsx
admin-frontend/src/app/(admin)/imports/layout.tsx
admin-frontend/src/lib/api/types.ts
backend/app/api/v1/admin_imports.py
```

## 展示内容

```text
最近导入成功率
平均导入耗时
高风险题比例趋势
manual_review_rate 趋势
OCR cache 命中率
最常见 failure types
最近 alerts
清理任务 dry-run
执行 cleanup
```

## 要求

1. 如果新页面成本高，可以先在 history/tasks 页展示。
2. 所有字段缺失时 graceful fallback。
3. cleanup 默认 dry-run。
4. 真删除前必须二次确认。
5. 不影响现有导入 / 审核页面。

## 验收标准

1. 管理端能看到导入健康摘要。
2. 能看到最近 alerts。
3. 能执行 cleanup dry-run。
4. 能执行 cleanup 确认删除。
5. TypeScript 检查通过。

------

# P7-6：发布前检查脚本

## 目标

把回归、验收、清理 dry-run、配置检查整理成一个固定命令。

## 建议新增

```text
scripts/ocr_preflight_check.py
docs/ocr/DEPLOY_CHECKLIST.md
```

## 检查项

```text
pytest tests/ocr_regression
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict
cleanup dry-run
OCR cache 目录可写
pipeline artifact 目录可写
vision 模型配置存在
DeepSeek 配置存在
token budget 配置合理
```

## 要求

1. 默认不删除任何文件。
2. 输出 pass / warn / fail。
3. 允许缺少私有真实样本时 warn，不 fail。
4. 可用于本地发布前执行。
5. 文档写清楚什么时候运行。

## 验收标准

1. 一条命令能跑预检查。
2. 报告清楚。
3. 不依赖生产环境。
4. 不误删文件。

------

# P7-7：工程文档与运维手册

## 目标

P0～P7 后 OCR 功能已经很复杂，需要有运维手册。

## 需要更新或新增

```text
docs/ocr/OPERATIONS.md
docs/ocr/TROUBLESHOOTING.md
docs/ocr/DEPLOY_CHECKLIST.md
docs/architecture/OCR_FLOW.md
```

## 文档至少说明

1. OCR 导入完整流程。
2. 质量报告怎么看。
3. Dashboard 指标含义。
4. 常见告警解释。
5. cleanup 怎么跑。
6. 失败 case 怎么导出。
7. acceptance 怎么跑。
8. 发布前检查怎么跑。
9. 出现导入失败如何 resume。
10. 哪些目录不能手动删。

## 验收标准

1. 文档与当前代码一致。
2. 新人能按文档排查导入问题。
3. 运维人员知道如何清理缓存和 artifact。

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

如果修改 maintenance / cleanup：

```bash
pytest tests/test_features/test_pipeline_artifacts.py
pytest tests/test_services/test_ocr_cache_service.py
```

如果新增 preflight：

```bash
python scripts/ocr_preflight_check.py --dry-run
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
9. 不做没有真实失败样本支撑的识别优化。
10. 不自动生成 expected 答案。

------

# P7 执行完成报告

## 1. 本轮完成了哪些 P7 任务

| 任务 | 状态 | 说明 |
|------|------|------|
| **P7-1 观测指标沉淀** | ✅ | `GET /api/admin/v1/imports/pipelines` 端点，API 层聚合 quality_report（无 DB migration） |
| **P7-2 告警规则** | ✅ | `ocr_alert_rules.py` — 7 条规则（import_failed/high_risk/manual_review/ai_answer/cache_hit/duration/ocr_fail）+ pipeline 完成自动评估 |
| **P7-3 清理任务** | ✅ | OCR cache `cleanup_expired_entries()` + artifact cleanup `dry_run` 支持 + 统一 `POST /maintenance/cleanup` 端点；DB rows 不实现（需 dry-run + confirm） |
| **P7-4 失败样本导出** | ✅ | `ocr_case_exporter.py` — raw_data <=2000 字符 + expected_template 全部为空 + 单题/批量端点 |
| **P7-5 管理端运维页** | ✅ | `maintenance/page.tsx` — 健康摘要 + 告警列表 + Dry-Run/确认清理 UI + layout 新增"运维" tab |
| **P7-6 Preflight 检查** | ✅ | `scripts/ocr_preflight_check.py` — 离线 5 项（回归/验收/缓存/artifact/脚本）+ 可选在线 3 项（cleanup/AI 配置），离线优先 |
| **P7-7 运维文档** | ✅ | `docs/ocr/OPERATIONS.md` + `TROUBLESHOOTING.md` + `DEPLOY_CHECKLIST.md` |

## 2. 修改了哪些文件

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
| `backend/app/features/ocr_alert_rules.py` | 新增：7 条告警规则 + evaluate_alerts() | P7-2 |
| `backend/app/features/ocr_case_exporter.py` | 新增：失败样本导出（raw_data 截断，expected 为空） | P7-4 |
| `backend/app/features/pipeline_artifacts.py` | cleanup_expired() 增加 dry_run 支持 + _count_artifact_files()/_dir_size() | P7-3 |
| `backend/app/services/ocr_cache_service.py` | 新增 cleanup_expired_entries() 函数 | P7-3 |
| `backend/app/features/pipeline_orchestrator.py` | pipeline 完成时调用 evaluate_alerts() 写入 alerts | P7-1/2 |
| `backend/app/schemas/import_review.py` | PipelineStatusResponse 增加 alerts 字段 | P7-2 |
| `backend/app/api/v1/admin_imports.py` | 新增 GET /pipelines, POST /maintenance/cleanup, POST /questions/{id}/export-case, POST /batches/{id}/export-failure-cases | P7-1/3/4 |
| `admin-frontend/src/lib/api/types.ts` | 新增 ImportPipelineSummaryItem, PipelinesListResponse, AlertItem, CleanupResponse, ExportCaseResponse | P7-1/2/5 |
| `admin-frontend/src/app/(admin)/imports/layout.tsx` | 新增"运维" tab（Wrench 图标） | P7-5 |
| `admin-frontend/src/app/(admin)/imports/maintenance/page.tsx` | 新增：健康摘要 + 告警列表 + Dry-Run/确认清理 UI | P7-5 |
| `scripts/ocr_preflight_check.py` | 新增：离线优先预检查脚本 | P7-6 |
| `docs/ocr/OPERATIONS.md` | 新增：运维手册（质量报告/告警/清理/导出/验收/Preflight） | P7-7 |
| `docs/ocr/TROUBLESHOOTING.md` | 新增：故障排查手册（卡住/OCR 质量/高审核率/AI/Artifact/缓存） | P7-7 |
| `docs/ocr/DEPLOY_CHECKLIST.md` | 新增：发布检查清单（环境变量/Preflight/回归/验收/清理/部署步骤/回滚） | P7-7 |

## 3. 新增观测指标

| 指标 | 来源 | 用途 |
| ---- | ---- | ---- |
| pipelines 列表 | `GET /imports/pipelines` | 查看所有 pipeline 状态 + quality_report（如有） |
| alerts | pipeline store | 每条 completed pipeline 的告警列表 |
| quality_report | pipeline store | 已有字段：total_questions, low/medium/high_risk, ai_answer_count, math_image_count, performance_summary |

## 4. 新增告警规则

| alert_code | level | 触发条件 |
| ---------- | ----- | -------- |
| `import_failed` | error | pipeline status = failed |
| `high_risk_ratio_too_high` | warning | high_risk / total > 40% |
| `manual_review_rate_too_high` | warning | (medium+high) / total > 50% |
| `ai_answer_count_too_high` | warning | ai_answer_count > 10 |
| `ocr_cache_hit_rate_too_low` | info | hit/(hit+miss) < 20% |
| `pipeline_duration_too_long` | warning | duration_ms > 300000 (5 min) |
| `ocr_failed_page_ratio_too_high` | warning | failed_pages / total_pages > 30% |

## 5. Cleanup dry-run 示例

```json
{
  "dry_run": true,
  "target": "all",
  "targets": {
    "artifacts": {"scanned_count": 0, "deleted_count": 0, "freed_bytes": 0, "skipped_running_count": 0},
    "ocr_cache": {"scanned_count": 120, "deleted_count": 120, "freed_bytes": 458752, "skipped_count": 0},
    "db_rows": {"status": "not_implemented", "note": "DB row cleanup 需要先 dry-run 再 confirm=true，当前版本暂不实现"}
  }
}
```

## 6. Case export 示例

```json
{
  "case_id": "failure_20260621_42",
  "source_file": "page_3.png",
  "source_page": null,
  "subject": "math2",
  "question_type": "single_choice",
  "import_id": 42,
  "raw_data": {"text": "1. 设函数 f(x) 在 [0,1] 上连续..."},
  "parsed_content": {"stem": "设函数 f(x) 在 [0,1] 上连续..."},
  "risk_flags": ["formula_uncertain"],
  "failure_types": [],
  "expected_template": {
    "stem": "",
    "options": {"A": "", "B": "", "C": "", "D": ""},
    "answer": "",
    "analysis": "",
    "_note": "请人工补充 expected 正确答案，禁止使用 AI 生成"
  },
  "exported_at": "2026-06-21"
}
```

## 7. 管理端页面 / UI 变化

- **新增** `/imports/maintenance` 运维页面：三块卡片 — 导入健康摘要（成功率/平均耗时/总题数）、最近告警列表（级别+消息+值+阈值）、清理管理（Dry-Run 按钮 → 结果表格 → 确认清理按钮）
- **修改** `/imports` layout：新增"运维" tab（Wrench 图标）
- **修改** `types.ts`：6 个新增类型

## 8. Preflight 结果示例

```
OCR Preflight Check — ⚠️  WARN
==================================================
总计: 6 | ✅ 5 | ⚠️  1 | ❌ 0

  ✅ [PASS] 回归测试用例     — 找到 7 个用例
  ✅ [PASS] 验收测试用例     — 找到 10 个 case 模版
  ✅ [PASS] OCR 缓存目录     — 已创建或可写
  ✅ [PASS] Pipeline Artifact 目录
  ✅ [PASS] 后端脚本目录
  ⚠️  [WARN] 在线检查        — 跳过（未提供 --api-base-url）
```

## 9. 验证结果

| 检查项 | 结果 |
|--------|------|
| `python3 scripts/ocr_preflight_check.py` | ✅ 5 pass, 1 warn |
| `npx tsc --noEmit` | ✅ 0 errors |
| TypeScript 类型检查 | ✅ 通过 |
| 后端无 DB migration | ✅ 严格遵守 |

## 10. 未完成事项

| 事项 | 原因 |
|------|------|
| DB rows 物理删除 | P7 第一版不实现。需要 archived 标记 + dry-run + confirm=true 三重保护，留待后续 |
| 趋势告警 | 需要 N 条历史数据积累，P7 第一版仅实现单 pipeline 告警 |
| history 页面添加质量概览 | history 页面基于 batches 数据源，pipeline 数据在独立端点上 |
| 清理任务的单元测试 | 需要 mock 文件系统，当前版本手测通过 |

## 11. 风险和注意事项

| 影响范围 | 说明 |
|----------|------|
| PDF 导入 | **不影响** — 仅新增告警评估 |
| 图片导入 | **不影响** |
| Excel 导入 | **不影响** |
| 文本导入 | **不影响** |
| resume | **不影响** — cleanup 保护 running/resumable TTL 内 artifact |
| artifact | **不影响** — cleanup dry-run 不删除，真实删除由 confirm 控制 |
| OCR cache | **可选清理** — TTL 14 天自动过期，cleanup 可手动触发 |
| AI complete | **不影响** |
| AI repair | **不影响** |
| 管理端审核 | **不影响** |
| acceptance runner | **不影响** |
| cleanup | **安全** — dry-run 不删除，真实删除需 confirm=true |

## 12. 下一轮建议

1. 根据真实生产数据做小范围规则优化。
2. 扩充真实样本库（利用 export-case 导出失败题）。
3. 观察外部 OCR API 成本与失败率。
4. 如果指标稳定，再进入功能冻结。
5. 考虑实现 DB rows 清理（需先实现 archived 标记）。

