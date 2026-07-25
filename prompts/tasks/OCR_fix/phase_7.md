你负责 OCR 整改 P7：建立可以决定“是否真的优化完成”的质量、性能、安全和发布证据。

### 目标

不能再以文件存在、测试数量或文档勾选作为完成证据。每次 OCR 版本发布必须生成可复现的 release evidence。

### 必做任务

1. 建立业务 corpus，至少按以下场景分桶：
   - 清晰扫描、低 DPI、模糊、倾斜、手机拍照
   - 单栏、双栏、多栏、跨页题目
   - 中文、英文、混排、特殊符号
   - 代码：括号、缩进、箭头、比较运算符、泛型、指针
   - 数学：上下标、分式、矩阵、LaTeX
   - 表格、流程图、题图、坐标图
   - 水印、页眉页脚、页码、装订线
   - 选择、判断、填空、简答、组合题
2. 样本治理：
   - 脱敏。
   - manifest 含 sample hash、license/来源、expected schema。
   - hard cases 和普通 cases 分开。
3. 指标：
   - CER/WER
   - 题号 exact match
   - 选项集合/顺序 exact match
   - 答案 exact match
   - code token exact、括号平衡、可解析率
   - 数学规范化等价率
   - region/layout F1
   - reading order pairwise/Kendall
   - table cell/TEDS
   - silent corruption rate
   - p50/p95/p99 latency、RSS、GPU memory、cost/page
4. runner：
   - 固定 seed、环境、模型 digest。
   - 输出 JSON + Markdown。
   - baseline 与 candidate 分桶比较。
5. 故障注入：
   - worker kill/native crash/OOM
   - Redis/DB/对象存储短暂失败
   - 磁盘满/cache corruption
   - VL 429/5xx/timeout/partial response
   - 超长 PDF、坏页、加密 PDF、空白页、巨型图片、压缩炸弹
6. canary/rollout：
   - 稳定 bucket。
   - hard stop：silent corruption、数据泄露、重复入库、worker crash propagation。
   - statistical stop：质量下降、p99/成本超阈值。
   - 自动 rollback 必须真正修改生效配置，而不只是生成 decision JSON。
7. CI/CD：
   - PR：unit/contract/static/security/small acceptance。
   - nightly：full benchmark/fault injection。
   - release：锁定 commit/model/sample hash，生成 evidence。
8. `RELEASE_EVIDENCE/`：
   - environment.json
   - dependency/SBOM
   - test-results
   - benchmark baseline/candidate
   - security scan
   - fault-injection report
   - canary decision
   - migration/rollback rehearsal

### 建议发布门槛

先由 baseline 数据校准，但至少要求：
- silent corruption 不得上升。
- 题号/选项/答案 exact match 不得下降。
- code/math 关键符号错误率不得上升。
- p95 latency 和 peak memory 在预算内。
- worker crash 不传播到 API。
- resume 等价率 100%（可接受字段除外）。
- 无高危 security finding。
- 无 OCR 原文泄露。

### 最终验收

输出机器可读 `release_decision.json`：
- decision: GO / NO_GO
- commit
- model/config fingerprints
- corpus hash
- baseline/candidate metrics
- failed gates
- rollback target

只有所有 hard gates 通过时，才可将架构文档对应 Sprint 标记为 ✅。