当前项目为 postgraduate-exam-AI-main，是一个基于 FastAPI + OCR + AI pipeline 的题库自动导入系统。

系统已完成以下能力：
- OCR pipeline（PaddleOCR + fallback）
- code integrity 检测
- OCR quality gate
- AI repair / enrich / complete
- vision fallback（PaddleOCR-VL）
- pipeline orchestrator
- admin dashboard + ai settings + audit logs
- database migration（Alembic）

---

## 当前任务目标：系统收敛验证（不允许新增功能）

请执行以下三项任务：

---

# 任务1：全链路真实数据压测

请使用真实或接近真实的数据，执行完整 pipeline：

PDF → OCR → normalize → quality_gate → code_gate → AI correction → split → match → review → DB

测试覆盖：

- C / C++ 代码题（必须包含结构体/递归/指针）
- 数学公式题
- 普通选择题
- watermark污染样本
- OCR截断样本
- 双栏排版样本

---

验证要求：

1. code_block_incomplete / code_structure_regression 必须阻断 skip
2. confidence_score 不能覆盖结构错误
3. low_risk_high_confidence 不能 bypass code gate
4. vision fallback 在 code error 时必须触发
5. parsed_content 与 raw_text 差异必须被检测

---

# 任务2：增加决策可观测性（decision trace）

在 pipeline 输出中增加标准字段：

decision_trace: []

必须记录每一步关键决策，例如：

- OCR quality gate 是否通过
- code quality gate 是否触发
- 是否进入 skip
- 是否触发 vision fallback
- AI repair 是否执行
- 最终结果为何是 passed / review / rejected

要求：

必须可以解释“为什么这个题被放行或拦截”。

---

# 任务3：系统进入冻结状态（v1.0 RC freeze）

当前系统进入 release candidate 阶段：

规则如下：

- ❌ 不允许新增功能
- ❌ 不允许新增 pipeline stage
- ❌ 不允许新增 AI 路由
- ✔ 仅允许 bug fix / performance / test enhancement

---

# 验收标准：

1. code损坏题不会进入 passed
2. skip机制无法绕过 code gate
3. 所有决策必须可追踪（decision trace）
4. pipeline 输出行为稳定一致
5. 回归测试全部通过
6. 无隐藏 bypass 路径

---

## 输出要求：

请返回：

- 回归测试结果
- 是否存在任何 bypass
- decision trace 示例（至少3条）
- 是否可以进入 production freeze