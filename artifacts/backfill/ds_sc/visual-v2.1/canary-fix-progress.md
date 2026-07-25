# Canary Rollback & Fix — Progress Report

## ✅ 已完成 — 第 1 阶段：回滚

### 回滚操作
- 三条 canary 记录（import_id=450, 452, 461）的 `parsed_content` 和 `source_image_name` 已从备份恢复
- 6 个错误的 visual-v2.1 资源文件已移至 `rollback_20260716/orphaned-assets/`
- `question_id` 原本即为 `None`（canary 未创建 Question 记录），无需额外清理
- 回滚报告：`artifacts/backfill/ds_sc/visual-v2.1/rollback_20260716/rollback-report.json`

### 第 2 节 — 题目映射（已完成，见回滚报告）

---

## 🔍 第 3 节 — requires_content_image 判定

### import_id=452 (q371)
| 字段 | 值 |
|------|-----|
| `requires_content_image` | **false** |
| `content_image_reason` | `none` |
| 选项 | A.95,22,91,24,94,71 / B.92,20,91,34,88,35 / C.21,89,77,29,36,38 / D.12,25,71,68,33,34 |
| 当前内容 | OCR 显示纯文字题干+A-D 数字序列选项，**无任何树图/表格/公式** |
| 处理方式 | 学生端不得显示 content image；结构化 A-D 文字选项+题干完整展示 |

### import_id=461 (q380)
| 字段 | 值 |
|------|-----|
| `requires_content_image` | **true** |
| `content_image_reason` | `stem_diagram` |
| 当前问题 | bbox `[240, 115, 360, 190]` 切断左侧节点 05、10 及其连线 |
| 节点覆盖 | "05"在 x≈183pt，"28"在 x≈355pt，当前 x0=240 漏掉左侧全部 |
| 目标 bbox | 约 `[170, 100, 370, 195]`，覆盖全部 9 个节点+完整连线 |

### import_id=450 (q369)
| 字段 | 值 |
|------|-----|
| `requires_content_image` | **true** |
| `content_image_reason` | `option_images` |
| 当前问题 | bbox `[170, 72, 420, 155]` 从中间开始，漏掉**选项 A 的 BST 图** |
| 正确内容 | 4 个 BST 二叉排序树图分别对应 A/B/C/D |

---

## 📋 第 4 节 — 修复方案

### 待修改：`manual-bboxes-v2.json`

```jsonc
// q369 — 选项均为图形 → 方案 B：option_group 覆盖全部 4 图
// 原 bbox [170, 72, 420, 155] → 改为宽 bbox [90, 55, 430, 180]

// q371 — 纯文字题，不需要 content image
// 需添加新字段：requires_content_image: false
// 或从 manual config 移除，但通过其他机制跳过

// q380 — bbox 扩大到覆盖全树
// 原 bbox [240, 115, 360, 190] → [170, 100, 370, 195]
```

### 需要修改
1. `manual-bboxes-v2.json` — 更新 q369/q371/q380 配置
2. `backfill_question_images.py` — 支持 `requires_content_image` 跳过
3. 添加视觉语义门禁（border completeness, text contamination 等）
