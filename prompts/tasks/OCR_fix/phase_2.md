你负责 OCR 整改 P2：消除 coordinator/gateway 的 scaffold、dummy 和假成功语义，使其成为真实生产路径；若无法在本阶段完整实现，必须安全禁用而不是返回成功。

### 当前明确缺陷

- `CoordinatorPipeline.run_all()` 使用 `dummy_ir`。
- `OCRCoordinator` 只构造 Gateway 并返回 `gateway_ready`，没有 OCR。
- Correction/Validation/Review/Persistence Coordinator 存在无条件 success/no-op。
- `PaddleOCRLocalAdapter` 把单页 PNG/JPEG bytes 交给 `_ocr_scanned_pdf()`。
- Gateway 的 local adapter 反向依赖巨型 legacy orchestrator，形成错误依赖方向。
- coordinator context 未把真实 secret 安全解析给 remote adapter。
- 空 `vl_base_url` 被显式传递时可能覆盖 adapter/client 默认 URL。
- adapter/gateway client 生命周期缺统一 close。

### 必做任务

1. 重新定义 coordinator 的 typed stage contracts：
   - InputDocument
   - RenderedPage/PageBatch
   - DocumentIR
   - ParsedQuestionSet
   - CandidateSet
   - ValidationReport
   - ReviewArtifact
   - PersistenceResult
2. `run_all()` 必须把真实上一步输出传入下一步，删除 `dummy_ir`。
3. OCRCoordinator：
   - 对每个 RenderedPage 调用 `gateway.recognize_page()`。
   - 合并 page-level DocumentIR 成一个 document-level DocumentIR。
   - 对 partial failure 产生明确 page error，不得总体假成功。
4. Local adapter：
   - 图片输入调用单页 worker API。
   - PDF 输入先进入 renderer/native-text routing，不能把 PDF/PNG 契约混用。
   - 不得 import `_ocr_scanned_pdf` 或 legacy orchestrator。
5. Remote adapter：
   - 由 resolver 返回 secret handle/secret version，调用时解析，不把 secret 写入 context/artifact。
   - 正确使用默认 base URL。
6. Correction、Validation、Review、Persistence：
   - 真正委托现有实现并返回 typed result。
   - 无可用实现时返回 `NOT_IMPLEMENTED` failure，不得 success。
7. coordinator 与 legacy 的等价测试：
   - 同一输入，问题数、题号、选项、答案、review batch、失败语义可比较。
   - shadow 模式只计算 route/compare，不执行第二次 OCR。
8. rollout：
   - legacy -> shadow -> canary -> coordinator。
   - canary 出现 hard condition 自动切回 legacy。
   - feature flag 变更在 job start 冻结，resume 使用原 context。
9. 生命周期：
   - Gateway/adapter/client 实现 async close/context manager。
   - 应用关闭和 job 取消时关闭资源。

### 验收

- 搜索不到 `dummy_ir` 或 no-op success coordinator。
- coordinator 模式对真实 PDF、PNG、文本 PDF 端到端产生 review batch。
- Gateway local/remote adapter 契约测试通过。
- coordinator 与 legacy 在 acceptance corpus 上达到预设等价阈值。
- 未实现功能 fail closed，不产生 completed/persisted=true 假结果。