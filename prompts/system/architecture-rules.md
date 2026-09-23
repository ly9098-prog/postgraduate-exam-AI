# Architecture Rules — 导入管线系统

> 状态：早期导入管线 Prompt，不是当前最高规则。以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 和代码为准。下文里的模型、JWT 天数和目录树可能已过时。

## 分层架构

```
输入层 (Input)        → 解析层 (Parse)        → 标准化层 (Normalize)
                        → 修复增强层 (Repair)  → 审核入库层 (Review)
```

- 每层只调用下一层的接口，不允许跨层调用
- 每层的数据结构在 `master_plan.md` 中约定，层间依赖数据格式而非内部实现
- 所有文件统一放在 `backend/app/features/` 目录下

## OCR 与 AI 解耦

- OCR 模块（stage9）和 AI 修复模块（stage6）是独立的可选插件
- OCR 输出与 PDF 文本提取输出格式一致（`RawDocument`），可无缝替换
- AI 修复的输出格式与 stage5 输出一致（`NormalizedQuestions`）
- 解耦原则：主管线不 import OCR/AI 模块，通过配置开关决定是否启用

## Pipeline 设计

- 单个入口函数 `process_question_pipeline(raw, source_type, source)` 
- 内部按阶段依次调用：extract → analyze → split → match → normalize → validate
- 每步返回中间结果，调用方可选择断点续传
- Pipeline 不处理并发，同步执行（大文件在 `BackgroundTasks` 中异步触发）

## Service 职责

- `services/import_service.py`：保留对外 API 接口（上传、审核），调用 pipeline
- `features/question_pipeline.py`：管线编排，不包含解析逻辑
- `features/*.py`：每阶段的具体实现，不包含 HTTP/DB 知识

## DTO/Schema 规范

- 所有阶段间数据格式用 `TypedDict` 定义，放在 `features/question_pipeline.py` 顶部
- 不进 Pydantic model（避免 import 复杂度）
- Schema 定义必须包含字段说明和示例值

## Question Schema 版本化

- Schema 变更时在 `master_plan.md` 中更新最终 schema
- 旧 schema 数据在管线中自动兼容（通过 `normalizer` 做向前兼容）
- 不改数据库字段（不引入新 migration）
