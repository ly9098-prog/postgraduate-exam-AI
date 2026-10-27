# 小程序客户端存储与本地派生数据兼容基线

核对日期：2026-10-28。对应重构计划阶段 0；范围仅限小程序 `utils/storage.js` 聚合命名空间、会话/缓存清理、408 学习策略、番茄钟任务类型与知识地图练习回执。不表示 `utils/api.js`、页面级存储写入、真机或全栈语义审查完成。

## 1. 入口与消费者

- `utils/storage.js` 是唯一聚合入口，导出名称与顺序固定为 `KEYS`、`get`、`set`、`setStrict`、`remove`、`clearSession`、`BUSINESS_CACHE_KEYS`、`PROTECTED_KEYS`、`SESSION_DYNAMIC_KEY_PREFIXES`、`studyStrategy`、`pomodoroTaskTypes`、`knowledgePracticeSync`。
- 页面、controller、分包、脚本与测试按聚合对象或解构使用该入口；聚合对象与其子模块导出的是同一实例。全仓 35 个文件引用 `utils/storage`（含门禁脚本的允许依赖清单与新增测试）。
- 2026-10-28 拆分：`storage-core.js`（键与基本读写、会话清理）、`study-strategy-meta/-profile/-plan.js` 与 `study-strategy.js`（策略元数据、档案、选题计算、聚合对象）、`pomodoro-task-types.js`、`knowledge-practice-sync.js`；八个文件均不超过 300 行，全部函数不超过 50 行。

## 2. 键与会话清理契约

- `KEYS` 为 `token` / `user` / `token_expires_at` / `refresh_token`；`BUSINESS_CACHE_KEYS` 16 项（含 `lastPracticeResult`、`practice_recent_subjects_v1`、`pomodoro_*`、`home_today_goal_total`）；`PROTECTED_KEYS` 仅 `privacy_acceptance`；`SESSION_DYNAMIC_KEY_PREFIXES` 8 项（`ai_`、`aiCache`、`ai_diagnosis`、`practice_pending_submission_v1:`、`exam_attempt_pending_v1:`、`v2:`、`v3:`、`review_today_draft_v1:`）。
- `clearSession` 顺序固定：认证键 → 业务缓存键 → 动态前缀键 → 调试快照。`preservePrivacyAcceptance` 只影响动态前缀扫描；`includeDebugSnapshots: false` 跳过调试快照；`getStorageInfoSync` 抛错时对应循环静默跳过。未列入清单的键（如 `other_screen_cache`、`privacy_acceptance`）不会被删除。
- `get`/`remove` 吞掉存储异常，`get` 失败返回 `null`；`set` 吞异常但打印 `Storage set error:`；`setStrict` 把异常抛给调用方（认证与协议记录依赖该差异）。

## 3. 408 学习策略

- 元数据：四科顺序 `data_structure`(11) / `computer_organization`(12) / `operating_system`(10) / `computer_network`(7)，五个阶段与 `CHOICE_TOTAL_POINTS=80`、`CHOICE_LOSS_BUDGET_POINTS=8`、`CHOICE_TARGET_POINTS=72`。
- 档案：默认权重 15/35/35/15；`normalizeProfile` 按 owner 指纹隔离（缺 owner 视为 `anonymous`），权重取整到 5 的倍数并夹在 0–100，未知阶段回退科目默认阶段，缺失科目回退默认值；`saveProfile` 校验通过才 `setStrict` 写入并刷新 `updatedAt`，失败抛 `invalid_study_strategy`。
- 观察（保留原文案）：`validateProfile` 的「存在无效学习阶段」分支在公开调用路径不可达，因为归一化阶段已把未知阶段替换为默认阶段。
- `subjectCodeFromItem` 支持 code/subject_code/subject/subjectCode 与中文名称别名（含「计组」「计网」），code 命中优先于矛盾名称。
- `buildChoiceLossBudget`：按首个子科目项去重；`accuracyPct` 按百分比、`accuracy` 按小数（>1 视为百分比）；覆盖满 40 题才在预算内/超预算之间切换，未满始终 `building`；失分与剩余预算保留一位小数，文案为 `预计失 X 分` / `待建立数据` / `已覆盖 N/40 道选择题配额` / `预计失分 X，在预算内` / `预计超预算 X 分`。
- `buildNextBestAction`：候选来自四科策略分（权重 + 阶段加成 + 无数据加成 + 弱项加成）、`dueReviewCount > 0` 的复习候选与 `hub.primary_task`/`hub.tasks` 后端候选；权重 0 的科目显式暂停；返回前删除内部 `_nbaScore`/`_subjectCode`；无候选返回 `null`。

## 4. 番茄钟任务类型

- 六种类型 `lecture/textbook/new_questions/wrong_questions/review/exam`，缺省 `new_questions`；`normalize`、`label` 对非法值回退默认类型。
- 记录键为 `id:<sessionId>` 与 `client:<clientStartId>`，非法类型、缺 id 与 client id 的会话不写入；自身限制 600 条，按 `savedAt` 降序截断。
- `typeForSession` 只认合法 `task_type`，否则按 id、client id 顺序回退到记录；非法/历史会话不会被归入默认类型。`labelForSession` 对无法归类的会话返回空串。

## 5. 知识地图练习回执

- 回执键 `knowledge_practice_sync_receipts_v1`、基线键 `knowledge_practice_sync_baselines_v1`；owner 指纹不匹配时读为空、写会重置；回执上限 120 条。
- `normalizeKnowledgePracticeReceipt` 把计数夹为非负整数、`correctCount` 不超过已答数、`wrongCount` 不超过错误余量，`expectedMinAttemptCount = baselineAttemptCount + answeredCount`，`requestId` 截断 128、`rootName` 截断 80。
- 合并同一节点回执时取较小基线、较大期望计数、较大创建时间，`requestId` 为空则沿用旧值，其余字段以最新一次为准。
- `resolveReceipt` 用归一化后的字段重算阈值（等于基线 + 已答数），不直接使用存储中的期望计数；`consumeBaseline` 读取后即删除，键 `0:0` 一律忽略。

## 6. 可执行基线

- 契约测试 `miniprogram/tests/test-storage-facade-contract.js` 10 项（导出顺序、原语成败语义、会话清理矩阵、策略元数据/隔离/取整/校验、科目推断、失分预算、下一步动作、任务类型与上限、知识回执），在 HEAD 原 `utils/storage.js` 与拆分后的门面均通过。
- 差分刻画：以 1,608 组调用脚本对照 HEAD 原模块与拆分后门面（含 650+ 条记录截断、清理矩阵与失败路径），0 不一致。
- 门禁 `miniprogram/tests/test-client-storage-boundaries.js` 14 项：八个模块的 300/50 预算、显式无环依赖图、只有门面可聚合、子模块不得反向引用门面、门面与子模块导出对象身份一致，以及父目录/跨分包/第三方/动态 require、超预算、循环依赖等负向自检，全部通过且不执行被检源码。
- 按当前 `reliability.yml` 的小程序步骤（259 行命令）本机精确重放：退出码 0、0 个 `not ok`，含新增两项。这是本机重放，不是远端 CI。
- 主包源码由 754.7 KiB / 174 个文件变为 759.7 KiB / 181 个文件（低于 1.4 MiB 阈值）；拆分后 8 个文件合计 34,815 字节，原单文件 29,701 字节 / 769 行，净增 5,114 字节。源码体积不是微信编译或上传体积证据。
- 同步更新的旧脚本：`tests/test-study-plan-save.js` 改为在同一 vm 上下文递归加载拆分后的模块（拆分后曾因 `wx is not defined` 失败，现已恢复通过）；`scripts/test-pomodoro-resilience.js` 的登出清理断言改读 `utils/storage-core.js`（该脚本在 CI 清单内，106 项通过）。

## 7. 未完成和未验证

- 未执行真实微信开发者工具编译、模拟器或真机；存储配额、清理时机与真机行为未验证。
- `scripts/test-408-feature-integration.js` 与 `scripts/test-pomodoro-practice-stats.js` 不在 CI 清单：前者在 HEAD 即因 `activeTaskTypeLabel` 旧内联形状失败（本次拆分又新增一处 `utils/storage.js` 内联断言过期），后者在 HEAD 与当前失败集合完全一致（12 项，均为已拆分页面的旧形状断言）。两者都只反映历史脚本落后于现有模块形状，不能当作小程序功能失败。
- `utils/api.js`（554 行，`request` 94 行、`uploadFile` 75 行）、`pages/dashboard`、`pages/home`、`subpackages/knowledge`、`subpackages/export` 等主包文件仍未治理；页面级存储写入与真机 `wx` 行为不在本基线范围。
- 本基线不覆盖后端学习域、任务队列、OCR 导入、AI 执行或生产验收。
