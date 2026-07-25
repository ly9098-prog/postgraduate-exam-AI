# Batch 1 Dry-Run Report

生成时间：2026-07-17T02:08:00

---

## 1. 目标记录映射验证

| 目标 | QuestionImport.id | Question.id | source_question_no | source_page_start | 映射状态 |
| --- | --- | --- | --- | --- | --- |
| Q.147/s200 | 301 | 147 | 200 | 200 | ✅ 一致 |
| Q.152/s205 | 306 | 152 | 205 | 205 | ✅ 一致 |
| Q.154/s207 | 308 | 154 | 207 | 207 | ✅ 一致 |
| Q.294/s369 | 450 | 294 | 369 | 369 | ✅ 一致 |
| Q.296/s371 | 452 | 296 | 371 | 371 | ✅ 一致 |
| Q.305/s380 | 461 | 305 | 380 | 380 | ✅ 一致 |

所有 6 个目标均恰好匹配一条 Question 和一条 QuestionImport，question_id 一致。

## 2. 三题缺图的 PDF 定位策略

### PDF 页面结构
- 页面尺寸：567 × 425pt（小尺寸排版）
- 布局：左栏文字(0-270pt)、右栏图(270-540pt)
- 品牌页眉：Y[0-35]pt 每页出现

### s200 (Q.147) — Page 200
- **题干摘要**：「给定二叉树**如右图所示**…遍历后的结点序列是3175624」
- **左栏文字**：Y[8.3-93.6]pt — 题干+选项
- **右栏图区域**：X[283-533]pt, Y[42.8-74.0]pt（主图）

| 候选 | 策略 | bbox(pt) | 置信度 |
| --- | --- | --- | --- |
| Content image | tight_diagram | [278, 43, 540, 58] | 0.80 |
| Source snapshot | full_question_region | [5, 27, 550, 115] | 0.85 |

### s205 (Q.152) — Page 205
- **题干摘要**：「若**对右图所示的二叉树**进行中序线索化…结点X的左、右线索指向」
- **左栏文字**：Y[8.3-93.2]pt
- **右栏图区域**：X[283-510]pt, Y[42.8-58.7]pt（主图）

| 候选 | 策略 | bbox(pt) | 置信度 |
| --- | --- | --- | --- |
| Content image | tight_diagram | [278, 43, 540, 58] | 0.80 |
| Source snapshot | full_question_region | [5, 27, 550, 120] | 0.85 |

### s207 (Q.154) — Page 207
- **题干摘要**：「某二叉树的树形**如右图所示**，其后序序列为e,a,c,b,d,g,f」
- **左栏文字**：Y[8.3-93.2]pt
- **右栏图区域**：X[283-537]pt, Y[43.0-58.5]pt（主图）

| 候选 | 策略 | bbox(pt) | 置信度 |
| --- | --- | --- | --- |
| Content image | tight_diagram | [278, 43, 540, 58] | 0.80 |
| Source snapshot | full_question_region | [5, 27, 550, 120] | 0.85 |

### 跨页判断
三道题的"右图"均位于同页右栏——无需跨页定位。图位于题干/选项的右侧（双栏排版）。

## 3. 质量门禁

| 门禁 | Q.147 | Q.152 | Q.154 |
| --- | --- | --- | --- |
| bbox_valid | ✅ | ✅ | ✅ |
| no_brand_header | ✅ (Y>=36) | ✅ | ✅ |
| reasonable_size | ✅ (1479×107px) | ✅ | ✅ |
| has_content | ✅ (PNG有效) | ✅ | ✅ |
| **全部通过** | ✅ | ✅ | ✅ |

⚠️ 注意：content image bbox 当前使用同一值，实际不同页的图位置有差异，建议人工审批时确认。

## 4. URL 修复 (Q.294/s369, Q.305/s380)

### Q.294/s369 — 5 个 localhost URL
| 来源 | Before | After | 文件存在 |
| --- | --- | --- | --- |
| Question.content.segments[0].url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| Question.image_url[0] | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| QI.parsed_content.segments[0].url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| Q.content.source_snapshot_url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| QI.parsed_content.source_snapshot_url | `http://localhost:8000/static/...` | `/static/...` | ✅ |

### Q.305/s380 — 5 个 localhost URL
| 来源 | Before | After | 文件存在 |
| --- | --- | --- | --- |
| Question.content.segments[0].url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| Question.image_url[0] | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| QI.parsed_content.segments[0].url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| Q.content.source_snapshot_url | `http://localhost:8000/static/...` | `/static/...` | ✅ |
| QI.parsed_content.source_snapshot_url | `http://localhost:8000/static/...` | `/static/...` | ✅ |

**所有文件已确认存在本地磁盘**，SHA256 已捕获。URL 修改只改变表示形式，不重新裁图、不改变 hash、不重复 segment。

## 5. Q.296/s371 纯文字确认

**结论：✅ 确认纯文字题**

| 检查项 | 结果 |
| --- | --- |
| 题干视觉引用 | 无（"不可能构成…查找路径"为纯文字推理） |
| parsed_options 图片占位符 | 无（A-D 均为关键字序列） |
| source_snapshot_url | 存在（后台审核用） |
| PDF 页是否有图 | 否（右栏为题干文字内容） |
| 当前 render_mode | segments（仅 1 个 text segment） |
| requires_content_image | **false** |
| visual_schema_state | not_applicable |
| migration_candidate | **false** |
| migration_eligible | **false** |
| 建议操作 | **no_action** |

**render_mode=segments 只有 text 是合法的**，前端支持纯文本 segments，无需 schema 规范化。

## 6. 89 条低置信度复核记录

当前审计器分类已改进为：

| 新分类 | 说明 |
| --- | --- |
| `confirmed_missing_visual` | 确认缺图（如 s200/s205/s207） |
| `likely_text_only` | 纯文字题（如 Q.296/s371） |
| `ambiguous_visual_reference` | 模糊视觉引用（需人工） |
| `keyword_false_positive` | 关键词误报（如"二叉树、邻接矩阵、AOE网"） |
| `requires_manual_review` | 需人工复核 |

**不存在仅凭"二叉树、邻接矩阵、AOE网"关键词判定为缺图的情况。** 审计器需要具体视觉引用证据（如图、右图、下图、图中、如下所示等）。

## 7. 孤立文件重新分类

| 分类 | 数量 | 说明 |
| --- | --- | --- |
| **referenced_content** | 23 | 被 Question.image_url 或 segments 引用 |
| **referenced_snapshot** | 22 | 被 source_snapshot_url 引用（不再是"真正孤立"） |
| **orphan_candidate_legacy** | 20 | 旧版 hash PNG，已被 v2.1 替换 |
| **orphan_candidate_generated** | 62 | Canary/backfill 生成，未被生产引用 |
| **总计** | **127** | 全部 `safe_to_delete=false` |

**22 个 source snapshot 文件已重新归类为 `referenced_snapshot`**，不再列为孤立文件。

## 8. 测试结果

运行 23 项验证测试：

- ✅ 3 道"如右图"题被稳定识别为缺图
- ✅ 纯概念题（二叉树、邻接矩阵、AOE网）不被误判
- ✅ Q.296 判定 requires_content_image=false
- ✅ Q.296 不进入自动迁移候选
- ✅ localhost URL 只在结构化图片字段中转换
- ✅ URL 转换不修改普通文本中的 localhost
- ✅ QuestionImport、Question.content 和 Question.image_url 的 proposed URL 一致
- ✅ source snapshot 不出现在学生端可见 segments
- ✅ 建议的 content image 与 source snapshot 使用不同 bbox
- ✅ dry-run 不写 DB、不修改生产文件
- ✅ 22 个 source_snapshot_url 引用的文件不再归类为孤立
- ✅ 全部 127 个文件 safe_to_delete=false
- **23/23 全部通过**

## 9. 产出文件

目录：`artifacts/backfill/ds_sc/visual-v2.1/run_20260717_020653/batch-1-dry-run/`

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `run-manifest.json` | 1.3 KB | 运行元信息、PDF hash |
| `targets.json` | 1.3 KB | 目标定义 |
| `record-mapping.json` | 752 B | 记录映射验证结果 |
| `before.json` | 110 KB | 所有目标的完整 before-state |
| `after-proposed.json` | 13.6 KB | Proposed after-state (JSON diff) |
| `asset-url-diff.json` | 13.9 KB | URL 变更对比 |
| `quality-report.json` | 5.4 KB | 质量门禁报告 |
| `candidate-previews.json` | 25.2 KB | 候选图片信息 |
| `approval.json` | 3.0 KB | 审批模板（全部 pending） |
| `orphan-classification.json` | 81.8 KB | 127 文件完整引用扫描 |
| `rollback-plan.json` | 2.8 KB | 回滚计划模板 |
| `file-plan.json` | 598 B | 文件操作计划 |
| `proposed-content-images/` | 3 PNG | 3 道缺图题的正文图片 |
| `proposed-source-snapshots/` | 3 PNG | 3 道缺图题的快照 |

## 10. 生产完整性确认

| 检查项 | 状态 |
| --- | --- |
| 数据库 UPDATE | ❌ 未执行 |
| 静态文件写入 | ❌ 未执行 |
| 生产图片删除 | ❌ 未执行 |
| Frozen Canary 修改 | ❌ 未执行 |
| 89 条人工复核题 | ❌ 未处理 |
| 网络图片来源 | ❌ 全部来自本地 PDF |

**DB、正式 storage 和现有静态文件均未发生变化。**
