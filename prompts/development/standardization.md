# 复杂题库导入 + 自动结构化标准化系统 · 主规划

> 参照 `new_task.md` 阶段规划，本文件为导入管线的主控规划。

## 项目最终目标

构建一套**从原始文档到结构化题库**的完整导入管线，支持：

- PDF（可复制文本 + 扫描版 OCR 降级）
- Word（.docx）
- 已有 OCR / 文本解析输出
- 自动结构化、标准化、校验、去重
- 人工审核后进入正式题库
- AI 辅助修复（题型猜测、选项补全、答案校验）

## 完整导入架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       输入层 (Input)                            │
│  PDF (文本/扫描)    Word (.docx)    Excel (.xlsx)   手动编辑    │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    解析层 (Parse)                               │
│  stage1: 文本标准化 → stage2: 结构分析 ──→ stage3: 题目切分     │
│  (ImportTextNormalizer)  (章节/题型识别)     (逐题分割)          │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    标准化层 (Normalize)                         │
│  stage4: 答案匹配 ──→ stage5: 题目标准化                        │
│  (答案/解析提取)       (Schema统一/清洗/题型映射)              │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    修复与增强层 (Repair)                        │
│  stage6: AI 辅助修复 ──→ stage9: OCR 增强                      │
│  (DeepSeek补全验证)     (扫描PDF图片识别)                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    审核入库层 (Review)                          │
│  stage7: 审核系统 ──→ stage8: Pipeline 集成                    │
│  (暂存区/人工审核)     (统一入口/去重/日志)                    │
└─────────────────────────┬───────────────────────────────────────┘
                          ↓
                    questions 正式题库
```

## 各阶段关系

```
stage1 (文本标准化)
  └→ stage2 (结构分析)
       └→ stage3 (题目切分)
            └→ stage4 (答案匹配)
                 └→ stage5 (题目标准化)
                      ├→ stage6 (AI修复) ← stage9 (OCR增强)
                      └→ stage7 (审核系统)
                           └→ stage8 (Pipeline集成)
```

### 依赖关系

| 阶段 | 前置依赖 | 是否可以独立运行 |
|------|---------|----------------|
| stage1_text_normalizer | 无 | 是（可单独标准化文本） |
| stage2_structure_analysis | stage1 产出 | 是（可输入纯文本） |
| stage3_question_splitter | stage2 产出 | 是（可输入已标记文本） |
| stage4_answer_matcher | stage3 产出 | 是（可输入已切分题目） |
| stage5_question_normalizer | stage4 产出 | 是（可输入未标准化题目） |
| stage6_ai_repair | stage5 产出 | 是（不依赖亦可运行） |
| stage7_review_system | stage5 产出 | 是（不依赖 AI） |
| stage8_pipeline_integration | stage1-7 完成 | 否（整合阶段） |
| stage9_ocr_enhancement | stage1 框架 | 是（独立模块，可单独启用） |

## 数据流

```
原始文件
  → bytes / 文件路径
    → RawText [text, pages, metadata]
      → NormalizedBlocks [{page, block_index, raw_text, normalized_text}]
        → StructuredDoc [sections, headers, footnotes]
        → SplitQuestions [questions[], unparsed[]]
          → MatchedQuestions [questions[answer, analysis], unmatched[]]
            → NormalizedQuestions [canonical schema]
              → ReviewQueue [question_imports 暂存区, pending]
                → Questions [正式题库]
```

### 核心数据结构流转

```
Input File
  ↓ stage1
NormalizedBlocks [{ page: int, block_index: int, raw_text: str, normalized_text: str }]
  ↓ stage2
StructuredDocument { sections: Section[], headers: [], raw_text: str }
  ↓ stage3
QuestionCandidates { questions: RawQuestion[], remainder: str }
  ↓ stage4
MatchedResult { questions: MatchedQuestion[], unmatched: RawQuestion[] }
  ↓ stage5
NormalizedQuestions { questions: NormalizedQuestion[], errors: [], warnings: [] }
  ↓ stage6 (可选)
AIRepairedQuestions { questions: NormalizedQuestion[], repaired: [], unrepaired: [] }
  ↓ stage7
ReviewItems { batch_id, items: ReviewItem[], stats: {} }
  ↓ stage8
PipelineResult { accepted: int, rejected: int, import_batch_id: str }
```

## 最终 Question Schema

```json
{
  "schema_version": "v1",
  "subject": "math2",
  "question_type": "single_choice",
  "stem": "题干文本",
  "options": [
    {"key": "A", "text": "选项 A"},
    {"key": "B", "text": "选项 B"},
    {"key": "C", "text": "选项 C"},
    {"key": "D", "text": "选项 D"}
  ],
  "answer": "A",
  "analysis": "解析文本",
  "raw_text": "原始OCR/导入文本",
  "knowledge_points": ["导数"],
  "difficulty": 3,
  "source": {
    "file": "source.pdf",
    "page": 1,
    "type": "pdf"
  },
  "is_valid": true,
  "errors": [],
  "warnings": []
}
```

注意：`schema_version` 必须保留（如 `"v1"`），`raw_text` 始终保留原始导入文本。
```

### 题型标准值

| 标准值 | 兼容别名 |
|--------|---------|
| `single_choice` | choice, 单选, 单项选择 |
| `multiple_choice` | multiple, 多选, 多项选择 |
| `true_false` | 判断, 判断题 |
| `fill_blank` | fill, 填空 |
| `subjective` | 主观题, 简答, 论述, 计算 |

### 学科标准值

`math2` / `exam408` / `english`，兼容中文别名。

## DB 映射

| Schema 字段 | question_imports 字段 | questions 字段 |
|------------|---------------------|---------------|
| stem | parsed_content ({"text": ...}) | content ({"text": ...}) |
| options | parsed_options ({"A": "..."}) | options ({"A": "..."}) |
| answer | parsed_answer | answer |
| analysis | parsed_analysis | analysis |
| knowledge_points | - | knowledge_points |
| difficulty | - | difficulty |
| source | source_type + source_file | source_type + source_file |
| batch | batch_id | import_batch_id |

## Pipeline 结构

```
process_question_pipeline(raw, source_type, source)
  → normalize_question(raw_question)  ← 同文件函数
    → validate_question(normalized)
      → check_duplicate(subject, stem_hash)
        → write_to_imports()
          → [人工审核]
            → write_to_questions()
```

文件位置：`backend/app/features/question_pipeline.py`
原则：
- 单文件聚合，不再拆 service / helper / utils
- 不改数据库结构，不引入新 migration
- AI 生成必须经过 question_imports，绝不直接进 questions

## 开发原则

1. **可回退** — 每阶段产出的中间数据格式兼容，任意阶段可回滚
2. **可独立开发** — 每阶段不依赖后续阶段的内部实现，只依赖约定好的输入/输出格式
3. **AI 可开关** — AI 修复是可选增强，核心管线不依赖 AI
4. **人工审核最后一关** — 所有题目必须经过 question_imports 暂存区 + 人工确认
5. **不引入新中间件** — 不需要消息队列、缓存、向量数据库
6. **单文件聚合** — 一个阶段一个核心文件（或函数），不拆散到多个模块
7. **不提前建索引** — 等慢查询出现再加
8. **Excel 优先** — 能用 Excel 批量编辑解决问题，就不写解析代码
9. **渐进式复杂度** — stage1-5 是主线，stage6-9 是可选增强

## 架构原则（from new_task.md）

1. **OCR 与 AI 解耦** — OCR 只负责文本提取，AI 只负责修复/补全
2. **Prompt 禁止硬编码** — 所有 Prompt 统一放入 `/prompts`
3. **AI 仅用于修复/补全/结构化增强** — 禁止将所有内容直接丢给 LLM
4. **优先规则解析** — 规则能解决的问题不用 AI
5. **核心逻辑必须支持单元测试** — AI 调用可 mock，规则逻辑必须可测

## 文件目录

```
backend/app/
├── features/                     # 新目录：导入管线
│   ├── question_pipeline.py      # stage8: pipeline 集成入口
│   ├── text_normalizer.py         # stage1: 文本标准化
│   ├── structure_analyzer.py     # stage2: 结构分析
│   ├── question_splitter.py      # stage3: 题目切分
│   ├── answer_matcher.py         # stage4: 答案匹配
│   ├── question_normalizer.py    # stage5: 题目标准化
│   ├── ai_repair.py              # stage6: AI 修复
│   ├── ocr_service.py            # stage9: OCR 增强
│   └── __init__.py
├── services/
│   └── import_service.py         # 保留：现有导入服务可能被重构
└── models/
    ├── question.py               # 保留：现有 Question 模型
    └── question_import.py        # 保留：现有 QuestionImport 模型
```

## 执行顺序

```
stage1 (文本标准化) → stage2 (结构分析) → stage3 (题目切分) → stage4 (答案匹配)
→ stage5 (题目标准化) → stage7 (审核系统) → stage8 (Pipeline集成)
                                        ↑ stage6 (AI修复) ← 可选，与 stage7 并行
                                        ↑ stage9 (OCR增强) ← 可选，依赖 stage1 框架
```

推荐先完成 stage1→5→7 主线，再追加 stage6 和 stage9 增强。
