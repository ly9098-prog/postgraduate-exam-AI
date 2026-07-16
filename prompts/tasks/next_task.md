不要执行 A6“全量 apply 28 题”。下一步先完成 Audit Acceptance Gate、候选集收敛和分批迁移准备。当前仍然禁止修改正式数据库和正式存储。

# ==================== 一、先复核当前审计报告中的三个异常

当前 run：

artifacts/backfill/ds_sc/visual-v2.1/run_20260716_221101/legacy-audit/

请读取并交叉核对：

- records.json
- records.csv
- segments.csv
- assets.csv
- summary.json
- published-diff.json
- approval.json
- run-manifest.json

必须首先解释并修正以下问题。

1. migration_eligible=510 明显过宽

当前数据中有：

- current=2
- legacy=19
- not_applicable=492
- frozen=3
- migration_eligible=510

纯文字、无需 content image 的 not_applicable 记录不应是迁移候选。

请区分：

- migration_candidate：
  未来确实存在视觉迁移动作的记录。
- migration_eligible：
  已通过所有阻断条件、预览和审批，可进入某个迁移批次的记录。
- no_action：
  不需要迁移的正常记录。

建议规则：

- visual_schema_state=not_applicable：
  migration_candidate=false
  migration_eligible=false
  suggested_actions=[no_action]
- visual_schema_state=current 且无漂移：
  migration_candidate=false
  migration_eligible=false
  suggested_actions=[no_action]
- legacy/missing/mixed/published_diverged：
  才可能 migration_candidate=true。
- 尚未生成预览、尚未审批、存在 blocker：
  migration_eligible=false。

修正后重新生成 summary，不能再使用“所有非 frozen 记录都 eligible”的逻辑。

1. 复核 4 条 placeholder-only

逐条检查：

- import_id=302
- import_id=320
- import_id=433
- import_id=449

输出每条记录的：

- 题干；
- parsed_options；
- Question.options，如已发布；
- placeholder 命中 field_path；
- requires_content_image；
- visual_schema_state；
- visual_kind；
- page；
- 是否存在可恢复的原始图形区域；
- 推荐动作。

若 placeholder 表示图形选项被替换为文本占位符，则不得判定为：

requires_content_image=false
visual_schema_state=not_applicable

应根据证据判定为：

requires_content_image=true
visual_schema_state=missing
visual_kind=option_images

或在证据不足时：

requires_content_image=unknown
visual_schema_state=unknown
suggested_actions=[manual_review]

不得仅因为没有 image segment 就认为题目是纯文字题。

1. 解释 19 条 legacy 的完整去向

当前报告称 legacy=19，但下一阶段只提到：

“one pending legacy stem_diagram”

请输出完整的 19 条 legacy 清单，每条包括：

- import_id；
- question_id；
- page；
- source_question_no；
- visual_kind；
- 当前 segment 数；
- 当前 URL；
- asset_state；
- 是否已发布；
- 是否与 placeholder 记录重叠；
- 是否已有 visual-v2.1 候选 bbox；
- suggested_actions；
- blocker；
- 建议迁移批次。

不得使用模糊汇总隐藏其余 18 条记录。

# ==================== 二、重新定义本次迁移候选集合

生成：

migration-candidate-review.json
migration-candidate-review.csv

候选集必须从真实审计维度动态推导，不得硬编码 28。

至少分为：

A. published_broken_assets

当前预期包括：

- import_id=407 → Question id=1
- import_id=480 → Question id=3

条件：

- 已发布；
- 学生端 content image 为 legacy；
- 当前文件缺失或不可解码。

优先级：P1。

B. placeholder_missing_visuals

当前待复核：

- 302
- 320
- 433
- 449

只有确认它们确实需要图形选项后，才进入候选。

优先级：P1 或 P2。

C. remaining_legacy_content_images

除 frozen Canary 以外的其他 legacy records。

需要进一步区分：

- stem_diagram；
- option_images；
- table；
- code_or_formula；
- source_snapshot_misuse；
- unknown。

D. frozen

- 450
- 452
- 461

只用于回归对照，不进入任何 apply 批次。

E. no_action

- 纯文字题；
- current 且健康的题；
- 不需要视觉迁移的题。

每条候选必须包含：

{
"question_import_id": 0,
"question_id": null,
"candidate_group": "...",
"priority": 0,
"requires_content_image": true,
"visual_kind": "...",
"current_state": "...",
"target_state": "visual-v2.1",
"suggested_actions": [],
"blockers": [],
"preview_required": true,
"approval_required": true,
"migration_candidate": true,
"migration_eligible": false
}

# ==================== 三、生成真实预览审批包

在不更新数据库、不上传正式存储的前提下，为全部 migration_candidate 生成本地预览。

若当前审计脚本已有 --generate-previews，则使用它；否则补齐该功能。

每条需要视觉迁移的题至少生成：

1. full-page-overlay

整页低分辨率预览，绘制：

- 当前 content bbox；
- proposed content bbox；
- question/source snapshot bbox；
- 下一题边界；
- 页眉排除区域。

1. current-content-image

当前学生端展示图片；文件缺失时显示明确诊断卡。

1. proposed-content-image

仅包含学生答题必需的：

- 图；
- 树；
- 表；
- 图形选项。

不得包含：

- 品牌页眉；
- 完整题干，除非视觉本身不可与题干分割；
- 下一道题；
- 大面积空白。

1. proposed-source-snapshot

包含：

- 当前题完整题干；
- 所有题图；
- 全部选项；
- 合理安全边距。

不得包含下一题和品牌页眉。

1. published-render-preview

对于已发布题，模拟最终 Question.content 的学生端渲染顺序，验证：

题干 → content image → 选项

不能只查看单张裁剪 PNG。

输出：

- review.html；
- review-contact-sheet.html 或 PNG；
- candidate-previews.json；
- approval.json。

每个候选必须有独立审批项：

- requires_content_image_approval；
- content_bbox_approval；
- content_image_approval；
- source_snapshot_approval；
- segment_placement_approval；
- published_sync_approval；
- final_approval。

所有审批默认 pending。

# ==================== 四、增加真实数据验收测试

现有 17 个测试通过后，再补充真实数据库回归测试。

至少增加：

1. 492 条 not_applicable 记录不得成为 migration_candidate 或 migration_eligible。
2. current 且无漂移的记录不得成为 migration_candidate。
3. 302、320、433、449 不得仅因为无 image segment 被自动判定为纯文字题。
4. 所有 19 条 legacy 必须出现在 migration candidate 报告或带有明确的排除原因。
5. migration_candidate 数量应等于候选明细数量，不能使用历史固定值 28。
6. migration_eligible 只允许出现在：
   - 无 blocker；
   - preview quality gates 全部通过；
   - 所有 required approvals 已 approved；
     的记录中。
7. approval 全部 pending 时，migration_eligible 必须为 0。
8. frozen Canary 的 migration_candidate 和 migration_eligible 均为 false。
9. published broken asset 407、480 必须为 P1。
10. source snapshot 不得被当作 student-visible content image。
11. 对候选脚本连续运行两次，候选明细和排序保持确定性。

# ==================== 五、完成审批后再创建独立迁移脚本

审计脚本不得获得 apply 能力。

后续迁移必须使用独立脚本，例如：

scripts/migrate_approved_question_visuals.py

该脚本只允许读取：

- 某个固定 audit run；
- 对应 approval.json；
- 对应 migration-candidate-review.json。

迁移脚本必须检查：

- run_id 一致；
- DB hash 一致；
- PDF hash 一致；
- config hash 一致；
- final_approval=approved；
- 所有 applicable 子审批已 approved；
- migration_candidate=true；
- blockers 为空；
- 非 frozen。

任一不满足就拒绝执行。

迁移脚本默认 --dry-run，只有显式 --apply 才允许写入。

# ==================== 六、按批次迁移，禁止一次全量

审批完成后按以下顺序实施。

Batch 1：已发布且资源失效

优先只处理：

- import_id=407
- import_id=480

要求：

- 生成新的 visual-v2.1 content image；
- 生成完整 source snapshot；
- 更新 QuestionImport.parsed_content；
- 同步 Question.content；
- Question.image_url 指向第一张学生可见 content image；
- 普通题目接口可以看到新 content image；
- 普通接口不得泄漏 source_snapshot_url；
- 管理端审核接口可见 source snapshot；
- 旧失效 URL 从学生可见内容中移除；
- 旧数据保存在备份和迁移报告中。

完成后停止，执行全量回归，不得立即继续 Batch 2。

Batch 2：placeholder-only

仅处理已人工确认需要 option_images 的：

- 302
- 320
- 433
- 449

必须逐题确认：

- 每个图形选项是否分别裁剪；
- 选项 A/B/C/D 与图片对应关系；
- 是否需要多 region；
- 前端最终排列是否正确。

Batch 3：其余 approved legacy

按 visual_kind 分组，每批建议不超过 5～10 题：

- stem_diagram；
- option_images；
- table；
- 其他。

每批完成后：

- 重新运行完整 audit；
- 检查 baseline diff；
- 检查 published diff；
- 检查幂等；
- 人工抽查；
- 再允许进入下一批。

严禁直接执行“全量 apply 28 题”。

# ==================== 七、Batch 1 迁移前必须提交 dry-run 报告

下一次交付只做到 Batch 1 dry-run，不要正式 apply。

输出：

batch-1-dry-run/
├── manifest.json
├── targets.json
├── before.json
├── after-proposed.json
├── db-diff.json
├── file-plan.json
├── rollback-plan.json
├── previews/
├── review.html
└── approval.json

dry-run 必须保证：

- 不修改 DB；
- 不上传正式存储；
- 不修改正式静态文件；
- 只在 run 输出目录写预览；
- 显示拟生成的 storage key；
- 显示 QuestionImport 和 Question 的 before/after；
- 显示 segments 的插入位置；
- 显示 image_url 的拟更新值；
- 显示 source snapshot 是否保持后台专用；
- 显示回滚所需的完整旧值。

# ==================== 八、当前阶段完成标准

本阶段完成后报告：

1. 修正后的 migration_candidate 数量。
2. 修正后的 migration_eligible 数量。
3. 492 条 not_applicable 是否全部排除。
4. 4 条 placeholder 的逐题判定。
5. 19 条 legacy 的完整候选/排除清单。
6. published broken assets 407、480 的预览。
7. 所有候选的 preview quality gate。
8. 所有待审批项数量。
9. 新增测试命令和结果。
10. Batch 1 dry-run 报告路径。
11. 确认没有执行任何 DB 或正式 storage 写操作。

完成这些内容后停止，等待人工批准 Batch 1。不要执行正式 apply，不要开始 Batch 2 或 Batch 3。
