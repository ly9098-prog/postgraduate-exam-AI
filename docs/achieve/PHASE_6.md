# 阶段 7：AI 辅助导题与智能题库增强 ✅

**目标**：引入 AI 辅助导题能力，提升题库整理效率、知识点标注效率与后期题库扩展能力。

**核心原则**：AI 仅作为辅助工具，所有 AI 输出必须经过人工确认后才能正式入库。

## 功能模块

### 1. AI 自动生成知识点标签
- 根据题干、答案、解析分析知识点
- 支持单/多知识点、主次知识点
- AI 结果进入待审核，不覆盖人工标签

### 2. AI 自动识别章节与考点归属
- 自动识别所属章节（如高数→导数）
- 输出附带置信度，低置信度重点提醒

### 3. AI 自动生成题目难度
- 难度 1-5 级，含简要原因
- 人工可重新调整

### 4. AI 自动总结题型
- 概念题/计算题/证明题/选择题等 多标签分类
- 不覆盖已人工确认分类

### 5. AI 批量生成练习题
- 基于 Prompt、知识点、章节生成（Markdown / Excel / JSON）
- 默认进入待审核题库

### 6. AI 自动补全缺失信息
- 补全学科/章节/答案/知识点/难度/题型/解析
- 答案必须明确标注"AI生成答案"并强制人工审核

## 审核流

```
AI输出 → 待审核 → 人工确认 → 正式入库
```

严禁 AI 结果直接写入 questions 表。新增 `ai_generated`、`ai_confidence`、`ai_review_status` 等追踪字段。新增 `ai_question_drafts`、`ai_generation_logs`、`ai_review_records` 表。

## 关键文件

```
backend/app/services/ai_import_service.py  # AI 导题服务
backend/app/models/ai_generation_log.py    # AI 生成日志
backend/app/api/v1/imports.py             # 导入 API（含 AI 审核流）
```

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
