# 数据结构题库补图 — 上下文摘要

> 生成日期：2026-07-16
> 当前干跑 tag：`visual-v2` | 最新输出：`artifacts/backfill/ds_sc/visual-v2/run_20260716_170714/`

---

## 当前状态

### 脚本主文件

`scripts/backfill_question_images.py` — 已完成 12 项生产前修正：

1. ✅ next_question 独立分区（短数字标号归入 next_question，不混入题干）
2. ✅ section_heading 移出题干白名单（`_STEM_ZONE_WHITELIST` 只剩 question_stem）
3. ✅ 标识字段澄清（`question_import_id`、`source_question_no`、`batch_id`、`is_published`、`bbox_source`）
4. ✅ qno=380 核对确认（是 B+ 树题，非 V1-V5 有向图）
5. ✅ 原始页/解析页双字段（`configured_pdf_page`、`db_source_page`、`resolved_pdf_page` + `page_resolution_strategy`）
6. ✅ 手工 bbox 迁移到版本化 JSON（`artifacts/backfill/ds_sc/manual-bboxes-v2.json`）
7. ✅ 图形完整性门禁（`check_visual_completeness`：前景边缘触碰、连通分量截断、visual_text 覆盖率）
8. ✅ 逐题三项审核清单（cleaned_stem / content_image / source_snapshot）
9. ✅ approval.json 模板 + `--apply` 强制读取，未批准跳过
10. ✅ 输出目录迁移到 `artifacts/backfill/ds_sc/visual-v2/<run_id>/`
11. ⏸️ Canary apply（待人工审核后执行）
12. ⏸️ 幂等性验证（待执行后再次干跑确认 0 变化）

### 测试

`backend/tests/test_backfill_dual_bbox.py` — 62 用例全部通过。

### 配置数据

- **JSON 区域清单**: `artifacts/data-structure-import/question-image-regions.json`（19 题，19 有 bbox）
- **手工 bbox 配置**: `artifacts/backfill/ds_sc/manual-bboxes-v2.json`（14 条手动校准，approved=false）
- **OCR 预计算结果**: `artifacts/data-structure-import/ocr_results.json`（第 379、380 页）

### 关键常量

| 常量 | 值 |
|---|---|
| CROP_VERSION | `"visual-v2"` |
| CONF_AUTO | 0.85 |
| CONF_REVIEW | 0.65 |
| CONTENT_MAX_BLANK_RATIO | 0.92 |
| OVERLAP_THRESHOLD | 0.6 |
| PDF_SHA256 | `0ede22748f2a00c3f36ef67c792d0de9ce004c3d046260e83835638af45893fb` |

---

## 最近一次干跑结果（28 题）

```
SUMMARY: total=28 auto=1 review=27 failed=0 gate_fail=0 stem_cleaned=2
```

需审核原因分布：
- 24 题 `confidence < 0.85`
- 7 题 `foreground_edge_touch`（前景触碰裁剪边缘）
- 2 题 `edge_component_truncated`（连通分量被截断）
- 自动通过：qno=397（conf=0.87，无完整性警告，snapshot OK）

### 页解析问题

JSON 清单中的 page 字段全部与 DB source_page_start 不一致，经 `_validate_content_page()` 确认后全部使用 DB 页（`strategy=db_page_has_content`）。

---

## 架构要点

```
regions_from_manifest(qno, page, entry, manual_map)
    ↑ 优先检查 manual_map（从 JSON 配置加载的手工 bbox）
    ↑ 其次使用 JSON 清单的 bbox
    ↑ 最后 fallback 到 auto_localized

process_one(target, regions_cfg, pdf_path, storage, ...)
    → 页解析（JSON page vs DB page → effective page + strategy）
    → 区域解析（manual > JSON > auto）
    → visual_bbox 前景分析（OCR 行 + foreground pixel）
    → 硬门禁（坐标/页眉/越界）
    → 图形完整性门禁（边缘触碰/截断/覆盖率）
    → 题干清理（visual_text 空间去重）
    → 截图渲染（content image + source snapshot）
    → 返回 QuestionReport（含所有标识和追踪字段）

apply_updates(db, targets, reports, storage)
    → 检查 approval.json（--apply 时强制读取）
    → 仅处理 approved 记录
    → 写入 segments + source_snapshot
    → 已发布题同步更新 Question
```

---

## 待人工操作

### 1. 逐题审核

打开最新报告的 `review.html`，查看每道题的：
- cleaned_stem（题干是否误删了真实文本）
- content_image（截图是否准确包住图形区域）
- source_snapshot（完整题目截图的可用性）

### 2. 编辑 approval.json

对通过的题，将三项 `approved` 改为 `true`：

```json
{
  "approved": {
    "cleaned_stem": true,
    "content_image": true,
    "source_snapshot": true
  },
  "all_approved": true
}
```

### 3. Canary apply（3 题）

挑选三类题各一个：
- 普通图题（如 qno=397，已自动通过）
- 曾发生 visual_text 污染的题（如 qno=379 或 380）
- 已发布题（目前 28 题均为 pending，无已发布）

```bash
source backend/.venv/bin/activate
cd backend

python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///./postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --only-question 397 \
  --apply \
  --approval-file artifacts/backfill/ds_sc/visual-v2/<run_id>/approval.json
```

### 4. API 验证

```bash
# 学生端
curl http://localhost:8000/api/v1/questions/397

# 管理端
curl http://localhost:8000/api/v1/admin/imports/397
```

检查返回数据中 `content.segments` 包含图片、`image_url` 不为空。

### 5. 全量 apply

```bash
python scripts/backfill_question_images.py \
  --db sqlite+aiosqlite:///./postgraduate.db \
  --pdf artifacts/data-structure-import/source/ds_sc.pdf \
  --apply \
  --approval-file <path>/approval.json
```

### 6. 幂等验证

全量后再次干跑：

```
created_assets=0
duplicate_segments_added=0
db_records_changed=0
idempotency_check=passed
```

---

## 已知限制

- OCR 预计算结果只有第 379、380 两页，其他页无 OCR → visual_bbox 只依靠 foreground pixel 分析，精度不如 OCR 辅助
- 手工 bbox 中 14 条 `approved=false`，当前全部为 `requires_review=True`
- JSON 清单的 page 字段与 DB 全不一致（可能由于历史 PDF 页码映射错误），当前通过 `_validate_content_page()` 运行时修正
- `ds_sc.pdf` 不在生产服务器上，正式 apply 需要在本地 i7+3060 执行后迁移数据
- 所有 28 题均为 pending 且无 published，canary 无法覆盖已发布题同步路径
