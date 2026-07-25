你负责 OCR 整改 P4：合并所有候选 acceptance decision，并清除原文/异常泄露。

### 当前问题

- `CandidateEvaluator`、`ai_safety.safe_accept_ai_result`、OCRFixRouter 自定义检查、pipeline 再评估、code stage safety 并存。
- 默认 `UNIFIED_SAFETY_MODE=off`。
- reason code 中混入动态异常文本。
- pipeline status/diagnostics 保存 OCR 原文 preview。
- 部分 trace/artifact 保存 before/after 原文。
- adapter raw_response 可能包含完整模型输出或上游 body。

### 目标

所有本地 OCR 修复、远程 VL、LLM repair、rule repair 只生成 Candidate；唯一 `CandidateEvaluator` 生成最终 decision。后续模块只消费 decision，不再自行 accept/reject。

### 必做任务

1. 定义稳定数据结构：
   - Candidate
   - CandidateContext
   - CandidateEvaluation
   - Decision enum
   - stable ReasonCode enum
   - redacted Evidence
2. 把现有规则迁入唯一 evaluator：
   - 空输出、长度塌缩/膨胀
   - 题号/选项/答案不可变约束
   - code token/括号/缩进/运算符完整性
   - 数学符号/公式完整性
   - 表格结构
   - hallucination/unsupported insertion
   - watermark/header/footer
3. Router 只负责生成候选和 fallback 顺序，不作最终安全判定。
4. `ai_safety` 变为兼容 adapter，内部必须调用 CandidateEvaluator；禁止保留第二份规则。
5. pipeline、repair、code stage 删除重复 acceptance。
6. 领域质量门：
   - text/code/math/table/figure-question 分别校准。
   - 输出 quality_before/quality_after 和 reason codes。
   - 高风险 evaluator 异常默认 REVIEW/REJECT，不得 auto-accept。
7. 隐私：
   - 普通日志只存 hash、长度、字符类别、页码、reason code、trace id。
   - Redis/status API 删除 `ocr_raw_text`、cleaned text preview 等原文。
   - debug artifact 必须显式开关、加密/权限隔离、短 TTL、审计访问。
   - exception、upstream body、signed URL 不得进入 metric label、model_used、reason code。
8. evaluator version/fingerprint 写入每个 decision 和 review artifact。
9. 默认 rollout：
   - 先 shadow 比较旧/新判定。
   - 达标后 enforce。
   - 最终移除旧判定。

### 测试

- 同一候选从任何入口得到相同 decision。
- evaluator 异常 fail closed。
- 选项/答案/代码/公式不可逆损坏全部拒绝。
- 合理 OCR 修复可接受。
- log/status/metric snapshot 中没有样本文本和 signed URL。
- reason code label 基数固定。
- 红队样本：prompt injection、超长上游异常、HTML/JSON body、密钥片段均被脱敏。

### 验收

- AST 测试证明只有 CandidateEvaluator 产生最终 acceptance。
- `UNIFIED_SAFETY_MODE` 可从 shadow 安全切换 enforce。
- 生产默认路径不存 OCR 原文 preview。