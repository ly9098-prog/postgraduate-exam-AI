> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

你现在不要直接大规模修改代码。请基于当前仓库，围绕“刷题小程序 OCR 导入题库准确率”做一次专项代码审计，并输出下一步可执行改造方案。

项目背景：

这是一个考研刷题小程序项目，包含：

- backend：FastAPI 后端
- admin-frontend：Next.js 管理端
- miniprogram：微信小程序用户端

OCR 功能主要用于题库导入，不需要做通用 OCR 平台。核心目标是提高高数题、408 计算机类题目的导入准确率，减少用户导入后发现“题目和原题不符”的情况。

请重点关注：

1. 高数题：公式、上下标、积分、极限、矩阵、分式、概率统计公式。
2. 408 题：C 语言代码、伪代码、数据结构、操作系统调度表、计组 Cache/地址表、计网路由表、SQL、哈夫曼编码表。
3. 导入后的人工审核效率：不要让用户逐题排查 OCR bug。
4. AI 只能辅助修复低置信度片段，不能擅自改写原题、猜答案、改代码逻辑。

当前已知关键文件包括但不限于：

```text
backend/app/api/v1/imports.py
backend/app/api/v1/admin_imports.py
backend/app/api/v1/ai_import.py

backend/app/features/pipeline_orchestrator.py
backend/app/features/question_pipeline.py
backend/app/features/review_service.py
backend/app/features/question_splitter.py
backend/app/features/question_normalizer.py
backend/app/features/text_normalizer.py
backend/app/features/ocr_quality_gate.py
backend/app/features/ocr_correction.py
backend/app/features/ocr_fix/router.py
backend/app/features/ocr_fix/qwen_adapter.py
backend/app/features/ocr_fix/deepseek_adapter.py
backend/app/features/ai_repair.py
backend/app/features/batch_image_import_service.py

backend/app/services/ocr_service.py
backend/app/services/import_service.py
backend/app/services/formula_normalizer.py
backend/app/services/math_region_detector.py
backend/app/services/formula_image_cropper.py
backend/app/services/hybrid_content_builder.py
backend/app/services/storage_backend.py

backend/app/models/question.py
backend/app/models/question_import.py
backend/app/models/import_pipeline.py
backend/app/models/import_batch_job.py

admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/app/(admin)/imports/questions/page.tsx
admin-frontend/src/app/(admin)/imports/batch-image/page.tsx
admin-frontend/src/app/(admin)/imports/text-import/page.tsx
admin-frontend/src/lib/api/types.ts

miniprogram/pages/practice/practice.js
miniprogram/pages/practice/practice.wxml
miniprogram/pages/wrong-detail/wrong-detail.js
miniprogram/pages/wrong-detail/wrong-detail.wxml
miniprogram/components/math-question/math-question.js
miniprogram/components/math-question/math-question.wxml
miniprogram/components/mp-html/
```

请完成以下任务。

# ============================================================ 一、先输出当前真实 OCR 导题链路

请从管理端上传入口开始，追踪当前真实调用链。

至少覆盖：

1. 管理端导入任务页：
   - admin-frontend/src/app/(admin)/imports/tasks/page.tsx
   - 当前调用的后端接口是什么
   - 注意检查它现在是否调用 `/imports/upload`，以及后端该接口是否被标记 deprecated
   - 如果前端仍在调用 deprecated 接口，请重点标出
2. 后端导入接口：
   - backend/app/api/v1/imports.py
   - backend/app/api/v1/admin_imports.py
   - backend/app/api/v1/ai_import.py
3. OCR pipeline：
   - pipeline_orchestrator.py
   - question_pipeline.py
   - services/ocr_service.py
   - features/ocr_service.py
   - batch_image_import_service.py
4. 审核入库：
   - review_service.py
   - question_import.py
   - question.py
   - admin_imports.py 审核、编辑、通过、发布接口

请输出真实调用链，格式如下：

```text
管理端页面：
  admin-frontend/...

HTTP 接口：
  POST /...

后端函数：
  xxx.py::function_name()

中间处理：
  xxx.py::class.method()
  xxx.py::function()

写入表：
  question_imports / questions / import_pipelines / import_batch_jobs

前端审核：
  admin-frontend/...
```

如果存在多个并行入口，请分别列出：

- PDF 导入
- 单图导入
- 批量图片导入
- Excel 导入
- 文本导入
- AI 补全
- AI 丰富
- 审核发布

请明确指出哪些是主路径，哪些是旧路径，哪些疑似废弃但仍被调用。

# ============================================================ 二、检查“管理端导入页是否调用了正确接口”

我特别怀疑当前管理端导入任务页可能调用了 deprecated 接口。

请检查：

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
backend/app/api/v1/imports.py
backend/app/api/v1/admin_imports.py
```

重点确认：

1. 管理端任务页上传文件时调用的是哪个路径？
2. 这个路径在后端是否 deprecated？
3. 是否应该改成 `/imports/pipeline/upload` 或 admin 侧对应的新接口？
4. 当前接口是否能走新版 pipeline？
5. 如果调用旧接口，会绕过哪些新 OCR 优化？
6. 前端状态查询接口是否和上传接口匹配？
7. 后端返回字段是否和前端 ImportPipelineStatusResponse 类型匹配？

请输出：

| 问题 | 当前代码位置 | 当前行为 | 风险 | 建议改法 |
| ---- | ------------ | -------- | ---- | -------- |
|      |              |          |      |          |

如果确认需要修改，请给出最小改法，但先不要直接改代码，先输出方案。

# ============================================================ 三、检查题目数据结构是否适合保存公式、代码、表格

请检查：

```text
backend/app/models/question.py
backend/app/models/question_import.py
backend/app/services/hybrid_content_builder.py
backend/app/services/math_region_detector.py
backend/app/services/formula_image_cropper.py
miniprogram/components/math-question/*
miniprogram/pages/practice/*
miniprogram/pages/wrong-detail/*
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

请分析当前数据结构：

1. `Question.content` 是 JSON，是否已经支持 segments？
2. `QuestionImport.parsed_content` 是否支持 segments？
3. `QuestionImport.math_regions` 是否已经保存公式区域？
4. `math_region_detector.py` 检测出来的公式区域是否能关联到具体题目？
5. `formula_image_cropper.py` 是否能把公式区域截图上传？
6. `hybrid_content_builder.py` 是否已经能构造 `render_mode: "segments"`？
7. 小程序 `math-question` 组件是否能渲染 `math_image` segment？
8. 管理端审核页是否能展示公式图片 segment？
9. 发布时 `QuestionImport.parsed_content` 到 `Question.content` 是否会保留 segments？
10. 错题页、刷题页是否都能展示 segments？

请输出：

| 能力 | 当前是否支持 | 代码位置 | 是否贯通到小程序 | 缺口 |
| ---- | ------------ | -------- | ---------------- | ---- |
|      |              |          |                  |      |

重点判断：

- 公式截图保留是否已经有 60% 基础，只差接入 OCR pipeline？
- 是否只在旧 import_service.import_pdf 里启用，而新版 pipeline 没有接入？
- 后续应该优先补后端 pipeline，还是补管理端审核预览？

# ============================================================ 四、检查高数题 OCR 风险点

请围绕高数题导入检查当前代码。

重点文件：

```text
backend/app/services/formula_normalizer.py
backend/app/services/math_region_detector.py
backend/app/services/formula_image_cropper.py
backend/app/services/hybrid_content_builder.py
backend/app/features/text_normalizer.py
backend/app/features/question_pipeline.py
backend/app/features/question_normalizer.py
backend/app/features/ai_repair.py
backend/app/ai/prompts.py
```

请检查：

1. 当前是否会把 Unicode 数学符号转成 LaTeX？
2. 是否会误改数学中的 l/1/I/O/0？
3. 是否会把复杂公式压成普通文本？
4. 是否支持分式、矩阵、行列式、分段函数？
5. 是否对低置信度公式做标记？
6. 是否保留公式原图？
7. AI 修复是否可能猜公式？
8. 前端 KaTeX / mp-html 是否能显示当前格式？
9. `formula_normalizer.py` 是不是只在部分旧流程中调用？
10. 新版 OCR pipeline 是否接入公式保护？

请输出高数题风险 Top 10：

| 排名 | 风险 | 具体表现 | 涉及文件 | 对刷题影响 | 最小修复方案 |
| ---- | ---- | -------- | -------- | ---------- | ------------ |
|      |      |          |          |            |              |

请注意：对高数题，原则是“公式不确定就标红或保留截图，不要让 AI 猜”。

# ============================================================ 五、检查 408 计算机题 OCR 风险点

请围绕 408 导入检查当前代码。

重点文件：

```text
backend/app/features/text_normalizer.py
backend/app/features/question_pipeline.py
backend/app/features/question_splitter.py
backend/app/features/question_normalizer.py
backend/app/features/ai_repair.py
backend/app/features/ocr_quality_gate.py
backend/app/features/ocr_fix/*
backend/app/features/text_question_parser.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
miniprogram/pages/practice/practice.*
```

请检查：

1. C 代码块是否被识别为代码块？
2. 代码缩进是否被保留？
3. `->`、`==`、`!=`、`<=`、`>=`、`&&`、`||` 是否被保护？
4. `*`、`&`、`[]`、`{}`、`()` 是否可能被 OCR 清洗误删或误改？
5. 普通文本清洗是否会影响代码？
6. AI 修复是否可能重写代码逻辑？
7. 题干中的代码是否能在小程序中正常展示？
8. 管理端审核页是否有代码块预览？
9. 408 表格，例如页表、段表、Cache 表、路由表，是否会被压成普通文本？
10. 多列选项是否容易错序？

请输出 408 风险 Top 10：

| 排名 | 风险 | 具体表现 | 涉及文件 | 对刷题影响 | 最小修复方案 |
| ---- | ---- | -------- | -------- | ---------- | ------------ |
|      |      |          |          |            |              |

原则：

- 代码只做保真，不做美化。
- AI 不能改写代码逻辑。
- 关键符号变化必须回滚或标红。

# ============================================================ 六、检查导入审核页是否足够帮助用户快速发现 OCR 错误

请检查：

```text
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/app/(admin)/imports/questions/page.tsx
admin-frontend/src/app/(admin)/imports/batch-image/page.tsx
admin-frontend/src/lib/api/types.ts
backend/app/api/v1/admin_imports.py
backend/app/features/review_service.py
backend/app/models/question_import.py
```

请分析：

1. 审核页是否展示 risk_flags？
2. 是否展示 OCR 原文 raw_data？
3. 是否展示 AI metadata？
4. 是否展示公式图片？
5. 是否展示原图区域？
6. 是否有绿色/黄色/红色风险分级？
7. 是否可以按风险过滤？
8. 是否可以只看高风险题？
9. 是否可以对照原图修改？
10. 是否能批量通过低风险题？

请输出当前审核页缺口：

| 缺口 | 当前代码位置 | 影响 | 最小改造方案 |
| ---- | ------------ | ---- | ------------ |
|      |              |      |              |

请特别关注：如果后端已经有 `risk_flags`，但前端没有有效展示或过滤，请明确指出。

# ============================================================ 七、检查原图区域保留能力

请检查当前 OCR 结果中是否保留：

- source_file
- source_page
- bbox
- page image
- question region image
- formula region image
- code region image
- table region image

重点文件：

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/visual_boundary_detector.py
backend/app/features/exercise_region_detector.py
backend/app/services/formula_image_cropper.py
backend/app/models/question_import.py
backend/app/models/import_batch_job.py
backend/app/features/review_service.py
```

请输出：

| 信息 | 当前是否存在 | 存在哪里 | 是否入库 | 前端是否可用 | 缺口 |
| ---- | ------------ | -------- | -------- | ------------ | ---- |
|      |              |          |          |              |      |

请判断：

1. 现在是否已经有 bbox，但没有入库？
2. 是否能从 OCR boxes 追踪到题目区域？
3. 是否有条件做“左原图，右 OCR 文本”的审核预览？
4. 如果没有，最小实现需要新增哪些字段？

优先给出最小方案，不要设计复杂图像管理系统。

# ============================================================ 八、检查答案字段是否可能被 AI 猜错

请检查：

```text
backend/app/features/answer_matcher.py
backend/app/features/question_normalizer.py
backend/app/features/ai_repair.py
backend/app/features/question_pipeline.py
backend/app/api/v1/ai_import.py
backend/app/api/v1/admin_imports.py
backend/app/ai/prompts.py
```

请分析：

1. 答案是从原文抽取，还是可能由 AI 生成？
2. AI 补全是否会补答案？
3. AI 丰富是否会改答案？
4. 答案缺失时系统会怎么处理？
5. 是否存在“题目看起来正确，但答案被 AI 猜错”的风险？
6. 当前是否有 `ai_answer_flag`，它在哪里设置，前端是否展示？
7. 是否能禁止 AI 自动推理答案，只允许从原文答案区或解析“故选 X”抽取？

请输出：

| 风险 | 当前代码位置 | 当前行为 | 推荐改法 |
| ---- | ------------ | -------- | -------- |
|      |              |          |          |

原则：

- 答案不能由 AI 解题生成。
- 如果原文没有明确答案，应该 answer = null，并标红人工确认。
- 如果 AI 涉及答案字段，必须设置 ai_answer_flag 或风险标记，并在审核页展示。

# ============================================================ 九、检查表格题支持

请检查当前是否支持表格题，包括：

- OCR boxes 是否能保留行列位置
- 是否有 table OCR
- 是否有表格结构化
- 是否能在 parsed_content 中保存 table segment
- 小程序 mp-html 是否能显示 table
- 管理端审核是否能编辑表格
- 表格是否容易被压成一行文本

重点文件：

```text
backend/app/services/ocr_service.py
backend/app/features/question_pipeline.py
backend/app/features/text_normalizer.py
backend/app/features/question_splitter.py
backend/app/services/hybrid_content_builder.py
miniprogram/components/mp-html/
miniprogram/pages/practice/practice.*
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

请输出：

| 表格场景 | 当前支持 | 风险 | 最小修复方案 |
| -------- | -------- | ---- | ------------ |
|          |          |      |              |

表格场景至少包括：

- 408 操作系统进程调度表
- 计组 Cache 映射表
- 计网路由表
- 哈夫曼编码表
- 真值表
- 高数概率统计数据表

# ============================================================ 十、给出下一阶段最小可执行改造计划

请不要给大而全重构计划。请基于真实代码，输出一个 2～3 周内可完成的最小改造计划。

目标：

- 减少导入后题目与原题不符
- 提高高数公式导入可靠性
- 提高 408 代码/表格导入可靠性
- 提高审核时发现 OCR 错误的效率

请分为 P0、P1、P2。

P0 必须是最小且高收益的任务，例如：

1. 修正管理端导入页调用新版 pipeline，而不是 deprecated 接口。
2. 后端为每道导入题生成 `import_risk_level` 和 `risk_reasons`。
3. 管理端审核页展示风险等级、risk_flags、ai_answer_flag。
4. 答案禁止 AI 猜测，AI 改答案必须标红。
5. 408 代码关键符号保护。
6. 高数公式低置信度标红，复杂公式优先保留截图。
7. 低风险题可批量通过，高风险题强制人工确认。

请输出表格：

| 优先级 | 任务 | 涉及文件 | 为什么优先 | 实现要点 | 验收标准 |
| ------ | ---- | -------- | ---------- | -------- | -------- |
|        |      |          |            |          |          |

# ============================================================ 十一、请输出可直接给你执行的 Claude Code 修改提示词

在报告最后，请额外生成一段“下一步修改提示词”，用于下一轮直接让你改代码。

这段提示词必须满足：

1. 只做 P0。
2. 不做大重构。
3. 不改变现有 API，除非已经确认前端调用 deprecated 接口需要修正。
4. 修改后必须运行相关测试。
5. 必须列出改动文件。
6. 必须保证小程序刷题页不被破坏。
7. 必须保证已有公式图片 segments 渲染能力不被破坏。

提示词格式：

```text
请基于上一轮审计报告，执行 P0 改造：
1. ...
2. ...
...
验收标准：
...
```

# ============================================================ 十二、最终输出要求

请最终输出一份 Markdown 文档，标题为：

《刷题小程序 OCR 导题准确率专项审计与最小改造计划》

文档必须包含：

1. 当前真实 OCR 导题链路
2. 管理端导入接口是否走错
3. 公式截图能力是否已经存在但未贯通
4. 高数题风险 Top 10
5. 408 题风险 Top 10
6. 审核页缺口
7. 原图区域保留能力
8. 答案字段 AI 风险
9. 表格题支持情况
10. P0/P1/P2 最小改造计划
11. 下一轮可直接执行的 Claude Code 修改提示词

本轮不要修改代码，只输出审计和计划。