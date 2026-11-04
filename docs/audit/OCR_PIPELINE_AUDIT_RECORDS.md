# OCR Pipeline 审计与任务记录

> 审计范围：`/home/lmh/projects/postgraduate-ai/backend/`
> 审计时间：2026-06-20（初版）→ 2026-07-18（末次更新）
> 审计方法：全量代码扫描 + 文档审查 + 测试用例分析 + 配置审查
> 
> 架构文档参考：`docs/architecture/OCR_PIPELINE_ARCHITECTURE.md`

---

## 目录

1. [代码结构审计](#1-代码结构审计)
2. [LLM 使用审计](#2-llm-使用审计)
3. [失败案例分析](#3-失败案例分析)
4. [性能与成本审计](#4-性能与成本审计)
5. [最终结论：核心问题状态](#5-最终结论核心问题状态)
6. [附录：测试与运维脚本](#6-附录测试与运维脚本)

---

## 1. 代码结构审计

### 1.1 模块职责评估表

| 模块 | 行数 | 职责 | 单一职责 | 耦合度 |
|---|---|---|---|---|
| `pipeline_orchestrator.py` | ~4871 | 19 阶段编排（含 classify_questions + code_structure_reconstruct）+ 性能 Profile + artifact 断点恢复 | 🟡 仍有降低空间 | 🟡 中 |
| `pipeline_coordinator_entry.py` | 210 | 统一 Pipeline 入口（legacy/shadow/coordinator 模式切换）+ AI config 快照冻结 | ✅ 新增 2026-07-18 | 🟢 低 |
| `coordinator_orchestrator.py` | 280 | Coordinator Pipeline 9 阶段顺序执行 | ✅ 新增（thin facade） | 🟢 低 |
| `coordinators.py` | ~180 | 9 个 Stage Coordinator 类 | ✅ 新增（thin facade） | 🟢 低 |
| `services/model_config_resolver.py` | ~600 | AIModelConfigResolver + AICapability 枚举 + ResolvedAIModelConfig | ✅ 新增 | 🟢 低 |
| `pipeline_stages/`（9 文件） | ~1380 | 9 独立 stage 实现 | ✅ 各模块单一 | 🟢 低 |
| `question_pipeline.py` | 2921 | `QuestionNormalizer` + 向后兼容重导出 | 🟡 保留入口 | 🟢 低 |
| `question_ai_complete.py` | 741 | AI 补全 | ✅ 单一 | 🟢 低 |
| `question_ai_enrich.py` | 323 | AI 丰富 | ✅ 单一 | 🟢 低 |
| `question_draft_generator.py` | 134 | AI 生成草稿 | ✅ 单一 | 🟢 低 |
| `question_import_writer.py` | 749 | Excel/PDF 导入 + 审核操作 | ✅ 单一 | 🟢 低 |
| `services/ocr_service.py` | 637 | PaddleOCR 封装 | ✅ 较好 | 🟡 中 |
| `text_normalizer.py` | 1400 | 规则清洗 + 统一 OCR 规范化入口 | ✅ 良好 | 🟢 低 |
| `ocr_fix/`（6 文件） | ~750 | 多模型 OCR 纠错路由（唯一路径） | ✅ 清晰 | 🟢 低 |
| `ocr_vl/paddleocr_vl_client.py` | ~430 | PaddleOCR-VL async HTTP 客户端 | ✅ 单一 | 🟢 低 |
| `ocr_vl/paddleocr_vl_adapter.py` | 112 | OCRFixerProtocol 适配器 | ✅ 清晰 | 🟢 低 |
| `ai_safety.py` | 284 | AI 编辑安全门禁 | ✅ 优秀 | 🟢 低 |
| `question_splitter.py` | 1437 | 题号+选项提取 | ✅ 良好 | 🟢 低 |
| `question_normalizer.py` | 1454 | Layer 0/1/3：题干清洗 + 分类器门控 + 选项标准化 + 题号防御转换 | ✅ 单一 | 🟢 低 |
| `ai_repair.py` | 1164 | AI 修复 + Layer 4 选项不可变门控 | ✅ 较好 | 🟢 低 |
| `code_integrity.py` | 938 | 代码块完整性检测 + 乱码代码块识别 + 代码区域隔离 | ✅ 单一 | 🟢 低 |
| `question_type_classifier.py` | 454 | Layer 1 严格 has_options 门控 + force_options_probe() | ✅ 单一 | 🟢 低 |
| `batch_image_import_service.py` | ~1391 | 批量图片导入编排器 | 🟡 职责增长中 | 🟢 低 |
| `pipeline_artifacts.py` | 559 | Pipeline artifact 持久化、兼容性检查、断点恢复 | ✅ 单一 | 🟢 低 |
| `ocr_fix/router.py` | 428 | OCR 纠错降级链路由 + 候选结果评估安全门禁 + 乱码代码持久检测 | ✅ 良好 | 🟢 低 |
| `ocr_mode.py` | 89 | OCR 模式解析（local/api）+ 依赖校验 | ✅ 单一 | 🟢 低 |
| `pipeline_enums.py` | 139 | Pipeline 状态枚举 + 状态转换守卫 + trace mapping（SSOT） | ✅ 单一 | 🟢 低 |
| `time_utils.py` | 24 | 统一 UTC 时间工具 | ✅ 单一 | 🟢 低 |
| `layout_router.py` | 76 | 生产固化路由决策（pure confidence-based） | ✅ 纯函数 | 🟢 低 |
| `evaluation/routing_metrics.py` | 217 | 路由决策指标收集 | ✅ 单一 | 🟢 低 |
| `evaluation/split_quality.py` | 111 | 分割质量加权评估 | ✅ 单一 | 🟢 低 |
| `services/import_pipeline_service.py` | ~370 | Import pipeline 公共逻辑 | ✅ 单一 | 🟢 低 |
| `api/router.py` / `api/v1/router.py` / `api/admin/router.py` | 3 files | 三层聚合 Router | ✅ 单一 | 🟢 低 |
| `services/storage_backend.py` | 235 | Storage 后端抽象 + 图片压缩 + delete 方法 + 题图存储工厂 | ✅ 较好 | 🟢 低 |
| `utils/question_content.py` | 26 | `extract_image_urls_from_content()` | ✅ 单一 | 🟢 低 |

### 1.2 关键结构问题修复记录

- **P5-2**: `pipeline_orchestrator.py` 9 个 stage 搬至 `pipeline_stages/`（4454→~4000 行）
- **P5-3**: `question_pipeline.py` 拆出 4 个模块（ai_complete/enrich/draft/import_writer）
- **OCR 清洗统一**: 3 处重复合并到 `text_normalizer.py:normalize_ocr_text()`
- **旧版路径清理**: `ocr_correction.py` 精简为 171 行包装层，纠错统一由 OCRFixRouter 处理
- **4 层 SSOT 架构**: Layer 1 门控 + Layer 0/1/3 集成 + Layer 4 选项不可变
- **死代码清理**: 移除 `normalize_option_order`，收紧 `_CHOICE_KEYWORDS`
- **API Router 入口层重构（2026-07-04）**：Service 抽离 + 12 个旧入口 410 + Router 聚合 + 前缀统一
- **乱码代码持久检测（`ad0d237`）**：基于 `detect_code_block_integrity` 的规则检测
- **code_structure_reconstruct 防假成功（`ad0d237`）**：pre/post integrity 对比
- **答案透传修复（`ad0d237`）**：日志字段修正 + `question_number` 类型防御转换
- **Storage Backend 完整实现（2026-07-16）**：COSStorage + compress_image + delete 路径穿越防护
- **题图补图工具链（2026-07-16）**：5 级视觉 QA 工具链
- **OCR Fix / AI Repair 配置统一（2026-07-18）**：`_build_router_config()` + `ai_repair.py` 切换为 AIModelConfigResolver
- **Coordinator Pipeline 生产接入（2026-07-18）**：`pipeline_coordinator_entry.run_pipeline()` 三模式
- **2C/2G 生产实测（2026-07-18）**：`scripts/run_cloud_api_resource_test.py`，生产服务器 10 项全部通过
- **外部 OCR API 数据库配置 E2E（2026-07-18）**：`scripts/run_remote_ocr_db_config_validation.py`，12 测试全部通过
- **Redis task queue 超时修复（2026-07-18）**：`brpoplpush(timeout=0)` → `rpoplpush()`，socket_timeout 2s→5s
- **S0 问题审计评估（2026-07-18）**：8 个 S0 问题中 7 已修复，1 处于设计阶段

---

## 2. LLM 使用审计

### 2.1 所有 LLM 调用全览

| 调用点 | 模型 | 触发条件 | 视觉 |
|---|---|---|---|
| `ocr_vl/paddleocr_vl_adapter.py` | PaddleOCR-VL-1.6 | OCR 路由链首（每批噪声块） | ✅ 原图 |
| `ocr_fix/deepseek_adapter.py` | DeepSeek-v4-flash | VL 失败/不可用（回退） | ❌ |
| `ai_repair.py` | DeepSeek-v4-flash | 规则修复后仍有不达标题 | ❌ |
| `llm_text_structurer.py` | DeepSeek-v4-flash | 规则结构分析不足 | ❌ |
| `question_pipeline.py:enrich/complete` | DeepSeek-v4-flash | 人工触发/自动补全 | ❌ |

> ✅ Qwen-VL 已完全移除（qwen_adapter.py 删除 309 行）。路由链：PaddleOCR-VL → DeepSeek → Rule。

### 2.2 Hallucination 保护

**已有：**
- `deepseek_adapter.py`: 长度越界检查 + 题干丢失保护
- `llm_text_structurer.py`: 反幻觉检查（字段必须在原文中找到）
- `ai_safety.py:evaluate_and_trace()`: 变更前后 diff + 代码符号/中文比例/选项数保护

**缺失：**
- `complete→enrich` 串联无版本回退
- 代码场景无语义等价性检查

---

## 3. 失败案例分析

### 3.1 已知失败样本（17 回归 case + 5 BUGS case）

| 样本 | 根因 | 解决方式 |
|---|---|---|
| `faulty_case_1` | OCR `->` 识别为 `<-`+乱码 | ✅ 规则修复（`_fix_pointer_arrows`） |
| `faulty_case_2` | 双栏选项顺序 B→A→D→C | ✅ 栏阈值降低 |
| `faulty_case_3` | 数字字母混淆 0→O, 1→l | ✅ 字符映射 |
| `faulty_case_4` | 低置信水印未过滤 | ✅ 置信度阈值 |
| `watermark_fail_case` | 水印污染 → LLM 保留水印 | ✅ 品牌水印规则 |
| `watermark_chart_case` | 水印+图表产生大量乱码 | ⚠️ 部分缓解 |
| `page_spread_case` | 跨页题号+答案不连接 | ⚠️ 部分修复 |
| `bugs_case1_stack` | VL confidence=0.0 被 gate 丢弃 | ✅ Fix A `0fed945` |
| `bugs_case2_treerecursion` | VL_REBUILD 被 `source_type=="pdf"` 阻断 | ✅ Fix B `be03159` |
| `bugs_case3_linkedlist` | VL 去掉了选项字母前缀 + 噪声 + frozen 阻塞 | ✅ 双源策略 `62f4870` + 代码重建 `e91a020` + 多修复 `ad33620` |
| `bugs_case4_forloop` | `}` 断裂 + brace 告警残留 | ✅ 代码结构重建 `e91a020` |
| `bugs_case5_listinsert` | VL 输出 LaTeX 污染 + 双源各损一半选项 | ✅ 双源 + Phase 3 merge + AI repair 兜底 |

### 3.2 根因分类

| 根因 | 占比 |
|---|---|
| PP-OCRv6 识别错误（含裁切/漏识别） | 40% |
| 版面分析错误 | 20% |
| 结构恢复错误 | 10% |
| PaddleOCR-VL 输出质量（缺前缀/LaTeX 污染/列表化） | 10% |
| VL confidence gate / pipeline routing | 10% |
| AI 纠错幻觉 | 5% |
| 代码场景特殊 | 5% |

> `ocr_failure_analyzer.py`（16 种分类），pipeline 完成后自动归因。

---

## 4. 性能与成本审计

### 4.1 LLM 成本估算

| 调用 | Tokens/100 页 | 成本 |
|---|---|---|
| PaddleOCR-VL 纠错 | 图片 | 外部 API 按次 |
| DeepSeek 纠错（回退） | 10K | ¥0.003 |
| DeepSeek 修复 | 36K | ¥0.011 |
| DeepSeek 补全+丰富 | 200K | ¥0.06 |
| **合计** | **~246K + API** | **~¥0.08 + 外部 API** |

### 4.2 Latency Bottleneck（本地 i7+3060, 100 页）

| 阶段 | 耗时 | 瓶颈 |
|---|---|---|
| PaddleOCR (GPU) | 10-25s | ✅ 可接受 |
| PaddleOCR-VL 纠错 | 15-40s | 🚨 外部 API（信号量=3） |
| DeepSeek 修复 | 10-30s | API 调用 |
| AI 补全 | 30-200s | 🚨 50 题串行 |
| **总计** | **~2-5min** | 可接受 |

> 内置性能 Profile（`diagnostics.performance_profile`），每 stage 耗时/IO/AI 调用/缓存命中率。

---

## 5. 最终结论：核心问题状态

| 优先级 | 问题 | 状态 |
|---|---|---|
| **P0** | 3 个内存缺陷（PDF bytes 驻留 + 双 OCR + store 大字段） | ✅ d7b2ae5, 04fd013 |
| **P0** | 旧版 `ocr_correction.py` 与新版并行 | ✅ edcfd0c |
| **P0** | OCR 清洗三处重复不同步 | ✅ cc419dd |
| **P0** | AI 纠错→修复无 diff 防护 | ✅ edcfd0c, 04fd013 |
| **P0** | 回归测试同义反复 | ✅ 058aea3, b63df47 |
| **P1** | 超级类拆分 | ✅ P5-2 + P5-3 |
| **P1** | 公式截图+审核提效 | ✅ c82c464 |
| **P1** | AI 补全并行化 | ⏳ |
| **P1** | 断点恢复 | ⏳ |
| **P9** | DAG 编排 + Batch-Image 并发一致性 | ✅ ede71f9, dce5aa4 |
| **Phase 2** | 路由策略固化 + Evaluation | ✅ 484d4e0, a9946af |
| **2026-06-23** | PaddleOCR-VL 客户端 `state`/`errorMsg`/JSONL 解析 bug | ✅ 本轮修复 |
| **2026-06-23** | `ocr_mode=api` 路由（跳过本地 OCR） | ✅ 本轮修复 |
| **P0** | 选项检测/修复路径不一致 | ✅ SSOT 冻结 + Layer 1 + Layer 4 |
| **P0** | AI repair 篡改 frozen/non-frozen 选项 | ✅ 773e8ef |
| **P1** | `_CHOICE_KEYWORDS` 过宽导致非选择题误判 | ✅ 54fbeeb |
| **P2** | `in "ABCD"` 子串匹配隐患 + 死代码 | ✅ 773e8ef |
| **P0** | PaddleOCR-VL confidence=0.0 丢弃 VL 结果 | ✅ 0fed945 |
| **P0** | VL_REBUILD PDF-only 限制 | ✅ be03159 |
| **P0** | VL 输出结构性损坏→选项丢失 | ✅ 62f4870（双源策略） |
| **P0** | AI repair 禁止修改 `{}` 导致代码 brace 无法修复 | ✅ e91a020 |
| **P1** | 前序失败时 review 仍写入审核池 | ✅ P5-3 skip on failure |
| **P0** | 案例三残留：噪声/空选项/冻结阻塞 | ✅ ad33620 |
| **P2** | 代码类型噪声无可观测性 | ✅ cb33729 |
| **P0** | 案例五残留：双源各损一半选项 | ✅ Phase 3 merge + AI repair |
| **P1** | Pipeline store 终态条目未清理 | ✅ LRU prune |
| **P1** | 断点恢复无兼容性检查 | ✅ check_artifact_compatibility() |
| **P2** | OCR fix 路由缺候选评估门禁 | ✅ CandidateDecision + risk_flags |
| **P2** | OCR 模式解析分散 | ✅ ocr_mode.py 统一 |
| **P2** | Pipeline 状态值硬编码 | ✅ pipeline_enums.py |
| **P2** | `datetime.utcnow()` 弃用 | ✅ time_utils.utcnow() |
| **P1** | 并发 merge 重复执行 | ✅ merge_status guard |
| **P1** | 并发 request_id 重复 job | ✅ 唯一索引 |
| **P2** | 同批去重跨科目假阳 | ✅ (subject, hash) 复合 key |
| **P2** | API Router 入口过多 | ✅ Service 抽离 + 410 |
| **P3** | Trace event docstring 过时 | ✅ 更新 |
| **P0** | OCR fix 乱码代码未验证 | ✅ ad0d237 |
| **P0** | code_structure_reconstruct 假成功 | ✅ ad0d237 |
| **P1** | 审核日志字段名不匹配 | ✅ ad0d237 |
| **P1** | question_number 类型不一致 | ✅ ad0d237 |
| **P2** | COS Storage 未实现 | ✅ 2026-07-16 |
| **P2** | 题图补图无自动化工具 | ✅ 2026-07-16 |
| **P1** | OCR Fix / AI Repair 配置未统一 | ✅ 2026-07-18：`AICapability.OCR_FIX` + `AI_REPAIR`，15 测试 |
| **P1** | Pipeline 入口未统一 | ✅ 2026-07-18：`coordinator_entry.run_pipeline()` 三模式 |
| **P1** | Redis `brpoplpush(timeout=0)` 误用 | ✅ 2026-07-18：`rpoplpush()` + socket_timeout 5s |
| **P2** | S0 审计问题未系统跟踪 | ✅ 2026-07-18：`s0_fix_assessment.md`，7/8 已修复 |
| **P3** | 2C/2G 生产资源限制未验证 | ✅ 2026-07-18：生产实测 10/10 通过，峰值 59MB |

---

## 6. 附录：测试与运维脚本

### 测试文件

| 文件 | 用途 |
|---|---|
| `tests/ocr_regression/runner.py` | ✅ 回归运行器 |
| `tests/ocr_regression/cases/` | ✅ 17 个回归 case |
| `tests/ocr_acceptance/run_acceptance.py` | ✅ 验收测试 runner |
| `tests/ocr_acceptance/cases/` | ✅ 10 类样本模板 |
| `tests/test_evaluation/test_routing_metrics.py` | Phase 2 路由指标测试 |
| `tests/test_ocr_code_question_repair.py` | 460 行，22 个测试 |
| `tests/test_services/test_storage_backend.py` | 228 行，20 个测试 |
| `tests/test_services/test_question_image_backfill.py` | 888 行，56 个测试 |
| `tests/test_ocr_fix_uses_admin_ai_config.py` | 5 测试：OCR_FIX 能力解析 |
| `tests/test_ai_repair_uses_admin_ai_config.py` | 7 测试：AI_REPAIR 能力解析 |
| `tests/test_ai_capability_model_separation.py` | 3 测试：feature mapping 分离 |

### 运维脚本

| 文件 | 用途 |
|---|---|
| `scripts/backfill_question_images.py` | 题图补图：PDF→bbox 裁剪→DB 写入 |
| `scripts/auto_detect_figure_regions.py` | OpenCV 自适应阈值 + contour 检测 |
| `scripts/visual_qa_check.py` ~ `scripts/final_visual_qa_report.py` | 5 级视觉 QA 工具链 |
| `scripts/run_remote_ocr_db_config_validation.py` | 外部 OCR API 数据库配置 E2E 验证 |
| `scripts/run_cloud_api_resource_test.py` | 2C/2G 资源限制实测 |

### 相关文档

| 文件 | 内容 |
|---|---|
| `docs/architecture/OCR_PIPELINE_ARCHITECTURE.md` | OCR Pipeline 架构 |
| `docs/ocr/OPERATIONS.md` | 运维手册 |
| `docs/ocr/TROUBLESHOOTING.md` | 故障排查手册 |
| `docs/ocr/DEPLOY_CHECKLIST.md` | 发布检查清单 |
| `docs/audit/OCR_PIPELINE_AUDIT_RECORDS.md` | 本文件：审计与任务记录 |

---

*报告结束。初版：2026-06-20，末次更新：2026-07-18。*

---

## 相关链接

- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
