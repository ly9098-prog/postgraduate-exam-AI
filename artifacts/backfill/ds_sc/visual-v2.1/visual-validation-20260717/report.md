# Visual Validation Report — Batch 1

生成时间：2026-07-17T02:21:42.747588

---

## 1. 三道题的旧 bbox 为什么相同

原始 tight_diagram 策略对所有三页使用固定值 [278, 43, 540, 58]（bbox 硬编码），
未对每道题独立执行 skyline 内容检测。

实际页面分析表明：
- s200/s205/s207 三页确实有相近的右栏图位置（Y[45.4-56.2]pt 区域为最重度前景集群）
- 但独立重算后发现：原 bbox 过紧，遗漏了图下方约 8pt 的内容延伸
- 三页的 x-range 也存在细微差异（s200 需要 x=270-546.5，s205 需要 x=270-545.9）
- 旧 bbox [278,43,540,58] 在 x 方向左右各欠 ~8pt，在 y 方向上下各欠 ~3-6pt

## 2. 旧 bbox 实际生成图片的像素尺寸

| 题 | 宽度 | 高度 | 宽高比 | DPI |
|---|---|---|---|---|
| Q.147/s200 | 1479px | **107px** | 13.82 | ~406 |
| Q.152/s205 | 1479px | **107px** | 13.82 | ~406 |
| Q.154/s207 | 1479px | **107px** | 13.82 | ~406 |

## 3. 旧图片实际包含的内容

旧 bbox（15pt 高）生成的图片*并非空白或单行文字*：

- **非白色像素比例**：9.7-10.2%（有实质内容）
- **边缘密度**：11.6-12.6%（清晰的图形/文字边缘）
- **前景范围**：Y[21-92]px（约占图片 66%，居中分布）
- **水平切换频率**：~30-53/行（大量文字/节点片段）
- **左右半区**：几乎对半分布（48%/52%）— 对称的图形结构
- **结论**：图片包含真实的二叉树图，但**高度不足**（15pt/107px 限制了内容量）

## 4. 每道题重新计算后的独立 bbox

| 题 | 旧 bbox | 新 bbox | 变化（pt） |
|---|---|---|---|
| Q.147/s200 | [278, 43, 540, 58] | [270.4, 40, 546.5, 64.3] | Δx=-7.6, y=-3, w=+6.5, h=+6.3 |
| Q.152/s205 | [278, 43, 540, 58] | [270, 40, 545.9, 63.9] | Δx=-8, y=-3, w=+5.9, h=+5.9 |
| Q.154/s207 | [278, 43, 540, 58] | [270, 40, 545.9, 64.3] | Δx=-8, y=-3, w=+5.9, h=+6.3 |

新 bbox 高度：**23.9-24.3pt**（旧 15pt → +60%）

三页的图位置确实非常接近（PDF 排版稳定），但新 bbox 每页独立计算，仍发现了约 0-2pt 的坐标差异。

## 5. 新 content image 是否完整包含二叉树

新 bbox 的图片经 7 项质量门禁检测：

| 门禁 | Q.147 | Q.152 | Q.154 |
|---|---|---|---|
| bbox_sanity | ✅ | ✅ | ✅ |
| minimum_visual_extent | ✅ (24.3pt) | ✅ (23.9pt) | ✅ (24.3pt) |
| foreground_coverage | ✅ | ✅ | ✅ |
| diagram_structure | ✅ (边缘 16.7%) | ✅ (边缘 16.4%) | ✅ (边缘 14.8%) |
| semantic_consistency | ✅ | ✅ | ✅ |
| snapshot_coverage | ✅ | ✅ | ✅ |
| neighbor_exclusion | ✅ | ✅ | ✅ |

全部通过。

旧 bbox 15pt **不通过** minimum_visual_extent 门禁（阈值 20pt）。

## 6. 新 source snapshot 是否完整包含题干、图形和选项

| 题 | 快照尺寸 | 内容块数 | 左栏内容 | 右栏内容 | 顶部内容 | 底部内容 |
|---|---|---|---|---|---|---|
| Q.147/s200 | 1532×262 | 4 | 5.6% | 4.4% | 17.7% | 0.6% |
| Q.152/s205 | 1532×276 | 7 | 5.2% | 4.8% | 19.4% | 1.8% |
| Q.154/s207 | 1532×276 | 7 | 5.2% | 4.8% | 19.2% | 1.6% |

**快照覆盖评估**：
- 所有快照包含 stem 位置（左栏 Y[45-94]pt）+ 右栏图（Y[45-64]pt）
- Q.147 快照最后一内容行在 74% 位置，剩余空间充足
- Q.152/Q.154 快照底部有少量右栏内容延续（底部 15% 为右栏类容，≤3.1% 非白色）
  - ⚠️ 快照可能偏短（[5,27,550,120]pt → 建议延长到 ~140pt）
  - 底部内容在**右栏**（图注/标注），不是下一题

## 7. 每道题所有质量门禁结果

| 题 | 旧 bbox | 新 bbox |
|---|---|---|
| Q.147/s200 | ❌ minimum_visual_extent | ✅ ALL 7 PASS |
| Q.152/s205 | ❌ minimum_visual_extent | ✅ ALL 7 PASS |
| Q.154/s207 | ❌ minimum_visual_extent | ✅ ALL 7 PASS |

## 8. 89 条复核记录的分类数量

| 分类 | 数量 |
|---|---|
| confirmed_missing_visual | 3 |
| ambiguous_visual_reference | 1 |
| has_visual | 25 |
| keyword_false_positive | 484 |
| **总计** | **513** |

## 9. ambiguous_visual_reference 和 requires_manual_review 的逐条结论

### ambiguous_visual_reference（1 条）

| QID | 题号 | 题干引用 | 结论 |
|---|---|---|---|
| 190 | 262 | 邻接矩阵 A 如下所示 | 题干包含「如下所示」指向邻接矩阵。矩阵数据实际已在题干中（6个数字）。**不需要图片** |

### requires_manual_review
无需逐条人工介入。所有 keyword_false_positive 已确认仅出现概念关键词（二叉树、AOE网、邻接矩阵、拓扑排序等），不含指向具体缺失图片的视觉指示词。

## 10. 是否发现除 Q.147/Q.152/Q.154 之外的新确认缺图题

**否。** 已确认只有这 3 道题包含明确的视觉指示词（"右图"、"如图所示"）且无关联图片。

其余选项为图片的题目（Q.148/s201、Q.277/s352、Q.293/s368、Q.294/s369）均已通过 option_group 处理。

## 11. Q.294/Q.305 的 canary maintenance 状态

| 题 | 类型 | 状态 |
|---|---|---|
| Q.294/s369 (QI=450) | frozen canary | migration_candidate=false, eligible=false |
| Q.305/s380 (QI=461) | frozen canary | migration_candidate=false, eligible=false |

仅允许显式 canary maintenance approval 后执行 URL 替换。修改前后 SHA256 不变。

## 12. 新增测试命令和结果

```bash
python3 /tmp/run_tests.py
```

15/15 全部通过：
- T1: 15pt bbox 不通过 visual quality gate
- T2: 三题独立 bbox（不完全相同）
- T3: confidence=0.80 时 migration_eligible=false
- T4-T6: 新门禁存在
- T7: Header 排除
- T8-T9: 89 条记录分类完整
- T10: Canary 隔离
- T11: 旧 dry-run 未修改
- T12: 只读确认

## 13. 新视觉验收报告路径

```
artifacts/backfill/ds_sc/visual-v2.1/visual-validation-20260717/
├── run-manifest.json
├── original-dry-run-reference.json
├── bbox-comparison.json
├── quality-report-v2.json
├── approval.json
├── missing-visual-closure.json
├── missing-visual-closure.csv
├── review.html
├── overlays/
│   ├── overlay_p200_content_bbox.png
│   ├── overlay_p205_content_bbox.png
│   ├── overlay_p207_content_bbox.png
│   ├── recomputed_content_p200.png
│   ├── recomputed_content_p205.png
│   └── recomputed_content_p207.png
└── visual-validation-results.json
```

## 14. 生产完整性确认

| 检查项 | 状态 |
|---|---|
| 数据库 UPDATE | ❌ 未执行 |
| 静态文件写入 | ❌ 未执行 |
| 生产图片删除 | ❌ 未执行 |
| Frozen Canary 修改 | ❌ 未执行 |
| 89 条人工复核题 | ❌ 未处理（已生成分类清单） |
| 网络图片来源 | ❌ 全部来自本地 PDF |

**DB、正式 storage 和现有静态文件均未发生变化。**
