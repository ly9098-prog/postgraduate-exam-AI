# 上一阶段完成情况（2026-07-16）

## 总体目标

从 **visual-v2.1 canary 修复** 过渡到 **Database-driven legacy visual migration audit**，完成全量遗留图片审计，不执行迁移。

## 已完成工作

### 1. 三条 Canary 修复（visual-v2.1 最终版本冻结）

| import_id | 问题 | 变更 |
|-----------|------|------|
| 450 (q369) | 四个图形选项 | 方案 B：option_group 图片 (1070×367px)，清空内部占位文本，保留 A-D 可点击键 |
| 452 (q371) | 纯文字题 | requires_content_image=false，删除 image segment，source_image_name=null |
| 461 (q380) | B+ 树图 | bbox 扩至 [170,107,370,193] 覆盖全部9个节点，题干改为"下图所示是一棵（ ）。" |

**代码变更**: `scripts/backfill_question_images.py`
- 新增 `--canary` 参数，只处理 369/371/380
- Plan B 选项清空：`apply_updates()` 中检测 option_group region 后清空 parsed_options
- `region_type` 传递到 region_results

### 2. 全量遗留图片审计（主交付物）

**新脚本**: `scripts/audit_legacy_question_visuals.py`（2159 行）

**核心特性**（覆盖 40 个需求章节）:
- SQLite 一致性快照（backup API）+ 只读验证
- 正交状态维度（非单一 legacy_status）: visual_schema_state, asset_state, placeholder_state, publication_state, contamination_state, protection_state
- 完整 asset reference graph（6 个扫描字段 per record）
- 按 asset 独立健康检查（local + HTTP + decode）
- SSRF 防护 + 路径穿越防护 + CSV formula injection 防护
- Mixed visual_schema_state 支持
- 多动作建议（List[ActionRecommendation]）
- 确定性优先级规则（P0-P4）
- Per-region + per-action 审批
- 结构化错误（AuditError）+ exit codes（0/1/2/3）
- CSP review.html（无远程资源）
- JSON Schema 输出
- HTML escape + CSV 安全转义

### 3. 审计结果（513 条 subject_id=7 记录）

| 维度 | 数量 |
|------|------|
| `visual_schema_state` — current | 2 (import 450, 461) |
| `visual_schema_state` — legacy | **19** (含 import 229, 369, 371, 378, 380, 388, 395, 397, 400, 402, 405, 407, 411, 412, 451, 457, 460, 472, 480) |
| `placeholder_state` — detected | **4** (import 302, 320, 433, 449) |
| `published_legacy` | **2** (import 407→q1, 480→q3) |
| `asset_state` — missing | **2** (407→q1, 480→q3 的旧图片在磁盘上已不存在) |
| `frozen` | 3 (450, 452, 461 — 全部 drift 未触发) |
| `migration_eligible` | 510 |
| `frozen_blocked` | 3 |

### 4. 测试（17 个全部通过）

`backend/tests/test_legacy_visual_audit.py`

覆盖：只读校验、Canary 状态、frozen drift 阻断、多维状态保留、placeholder Unicode 变体、CSV 注入、SSRF 阻断、路径穿越、格式检测、全量 513 条不静默跳过。

### 5. 诊断包

`artifacts/backfill/ds_sc/visual-v2.1/canary-v3/` — 7 文件
`artifacts/backfill/ds_sc/visual-v2.1/run_20260716_221101/legacy-audit/` — 9 文件（全量审计输出）

---

## 当前已知关键状态

### DB 图片引用图
- frozen canary 450/452/461: visual-v2.1 ✅
- import 229/369/371/378/380/... (19条): 旧 `ds_sc/q_*` 格式图片 segment，需迁移
- import 302/320/433/449: 四个图形选项占位符，需重建 option_group
- import 407→q1, 480→q3: 已发布但图片文件已不存在（dangling reference）
- import 700→q2: multi_blank_choice，无图片，不需处理

### 文件健康
- 24/26 asset 健康
- 2 个 missing（407/480 的旧 `ds_sc/q_*` 图片）
- 旧 orphaned-assets 文件未恢复，也不应直接移动

### 回滚逻辑缺陷（未修复）
- `backfill_question_images.py` 的回滚脚本在回滚时错误地移除了 DB 仍引用的文件
- 修复方案已记录在 `rollback-reference-test.json` 中
- 需要：先恢复 DB 引用，收集仍被引用的 URL，只清理引用数为 0 的资源

### storage backend 路径问题（未修复）
- `LocalFileStorage` 使用相对路径 `static/question-assets`，从 project root 运行时写入 `project_root/static/` 而非 `backend/static/`
- 已在 canary apply 时手动修复（复制文件），但脚本本身仍有此问题

---

## 下一阶段工作

### 第一阶段：三个新 Canary 迁移

从审计结果中选三条记录做 targeted migration：

1. **一个已发布旧图片题**: import_id=407（q326, question_id=1）
   - Kruskal MST 图
   - 当前图片文件不存在（dangling）
   - 需要同步更新 QuestionImport + Question
   - `Question.image_url` 需指向新资源

2. **一个 placeholder-only 图形选项题**: import_id=302（q201）或 import_id=320（q229）
   - 四个选项均为 `[图片选项A，原题图已内嵌]`
   - 需验证是否真的是图形选项（检查 PDF 页码 201/229）
   - 如果是：生成 option_group，清空占位符
   - 如果不是：恢复真实文字选项

3. **一个 pending 的普通 stem_diagram**: import_id=378（q295）
   - 旧 `ds_sc/q_*` 图片
   - 确定 requires_content_image 是否需要

### 第二阶段：执行策略

1. 生成新的 visual-v2.1 图片
2. 更新 cleaned stem
3. 同步 QuestionImport 和 Question
4. 验证 public URL
5. 学生端页面验证
6. 幂等性检查
7. 三条全部通过后才执行其余已批准记录

### 已知约束

- 只对 `migration_eligible=true` 的记录执行
- frozen 记录（450/452/461）不得自动覆盖
- 不得使用 `ALL_IMAGE_QNOS` 或"28 题"等硬编码列表
- 迁移前必须备份目标 QuestionImport 和 Question
- asset hash 变化时必须使用新的 storage key
- 不能简单 append 新 segment，需要替换旧的 content_image segment

### 参考文件
- `scripts/backfill_question_images.py` — 现有 backfill 逻辑（--canary / 方案 B / option clearing）
- `scripts/audit_legacy_question_visuals.py` — 审计脚本（只读，不更新 DB）
- `artifacts/backfill/ds_sc/visual-v2.1/run_20260716_221101/legacy-audit/records.json` — 全量审计结果
- `artifacts/backfill/ds_sc/visual-v2.1/run_20260716_221101/legacy-audit/approval.json` — 审批模板
- `artifacts/backfill/ds_sc/manual-bboxes-v2.json` — manual bbox 配置
- `backend/postgraduate.db` — 生产数据库（更改需谨慎）
- `backend/static/question-assets/202607/` — 静态图片目录
