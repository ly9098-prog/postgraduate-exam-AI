# 图片导入架构与实施规划审计

## 审计结论

- 结论：有风险，但可控
- 最高风险级别：P1
- 影响范围：图片上传入口、OCR 执行路径、审核入库链路、导入页交互

## 证据

- `backend/app/api/v1/imports.py:59-75` — 当前 `/import/upload` 只接受 `.xlsx/.xls/.pdf`，图片无法进入现有导入链路。
- `backend/app/api/v1/imports.py:247-290` — 已有独立 `pipeline/upload`，但只接受 `.pdf/.txt`，说明新增图片入口应保持分流而不是硬塞进旧接口。
- `backend/app/features/question_pipeline.py:771-912` — 现有 PDF 解析是按 PDF 文本/页面结构设计，不能直接吃图片 bytes。
- `backend/app/features/question_pipeline.py:1052-1163` — 审核通过后直接写 `questions`，说明任何图片 OCR 结果都不能绕过 `question_imports`。
- `backend/app/features/pipeline_orchestrator.py:203-236` — 新流水线已有文本/ PDF 抽取与 OCR fallback 位置，适合作为图片 raw_text 的后续接入点。
- `backend/app/services/ocr_service.py:27-170` — PaddleOCR 已有懒加载与并发封装，适合复用，但需要单图包装层。
- `miniprogram/pages/import/import.js:49-77` — 前端白名单和文案仅支持 Excel/PDF，图片导入需要前端入口改动。

## 风险点

1. 直接把图片塞进现有 PDF/Excel 接口会破坏当前稳定导入。
   - 影响：Excel/PDF 行为回归，解析分支混乱。
   - 触发条件：复用 `/import/upload` 并加大量分支。
   - 优先级：P1

2. 架构规划里同时保留“旧链路”和“新 pipeline”两套图片接入思路，容易造成实现分叉。
   - 影响：后续维护成本上升，状态语义不统一。
   - 触发条件：开发时没有提前选定唯一主路径。
   - 优先级：P2

3. 规划里建议新增图片上传入口，但未明确是否复用现有 `pipeline/upload` 的状态查询语义。
   - 影响：前端可能要维护两套轮询逻辑。
   - 触发条件：图片任务状态字段与现有 pipeline 状态不一致。
   - 优先级：P2

4. OCR 缓存和临时文件存储的生命周期未明确到可执行粒度。
   - 影响：存储增长、缓存污染、排障困难。
   - 触发条件：长期导入图片但没有清理策略。
   - 优先级：P2

5. 风险文档里强调“原图短期保存”，但没有给出最小保留边界。
   - 影响：存储成本和隐私边界不清。
   - 触发条件：大量图片长期保留。
   - 优先级：P3

## 最小修复建议

1. 只保留一条主实现路径：图片 OCR → raw_text → `ImportPipeline` TXT 分支 → `review_service.submit_to_review()`。
2. 新增图片专用入口，不修改 `/import/upload` 的现有分支。
3. 不新增独立审核 UI，继续复用批次详情页。
4. OCR 缓存只保存 hash、原文摘要和必要元数据，原图仅临时保留。
5. 图片任务状态字段直接对齐现有 pipeline 状态，减少前端分支。
6. 规划文档里明确：第一版不做表格结构化、不做公式 OCR 保证、不拆独立 OCR 服务。

## 回归检查点

- [ ] Excel 导入行为保持不变
- [ ] PDF 导入行为保持不变
- [ ] 图片导入不会直接写入 `questions`
- [ ] 批次详情页可复用，无需新增审核页
- [ ] OCR 失败时状态可见且可重试
- [ ] 临时文件和缓存有清理策略
- [ ] 图片导入状态与现有 pipeline 状态一致

## 需要修订的规划点

- 将“可选 OCR 接入”收敛为唯一主路径，不再并列旧 PDF 解析与新 pipeline 两种实现思路。
- 将“文件存储”收敛为临时存储 + 可选缓存，不要在第一版引入长期图像资产管理。
- 将“审计日志”从“建议记录”改为“必须记录的最小事件集”，以便排障和回归。
- 将“失败策略”明确为：OCR 失败不进入审核队列，但保留错误状态与原图短期预览。

---

## 相关链接

- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
