# Memory System

> 基于当前代码整理。系统的“记忆”不是单一模块，而是由错题分析缓存、复习调度、行为记录、知识状态、向量检索和推荐数据共同组成。最后更新：2026-10-29（本次复核模型、缓存判定与模块归属；不代表已完成全域语义审查或真实环境验收）。

## 当前实现

| 记忆域 | 主要存储 | 当前用途 | 代码入口 |
|---|---|---|---|
| 错题与 AI 分析 | `wrong_questions.ai_analysis`、AI 生成/反馈日志 | 缓存错因分析；详情缓存按输入签名、模型签名和视觉输入判定 `ready`/`stale`/`empty`，另有题目版本漂移守卫、进程内生成中集合和缓存租约，生成/反馈链路保留模型结果与失败状态 | `wrong_question_service.py`、`ai_service.py`、`ai/revision_guard.py`、`ai/analysis_execution.py` |
| 复习调度 | `review_schedules` | SM-2 `interval`/`ease_factor`/`repetitions`/`next_review_at`/`mastered` 的唯一数据源，绑定不可变 `question_version_id` 和单调 `occurrence_seq`；题目修订会在发题时重绑定最新版本 | `review_scheduler.py` |
| 复习历史 | `review_records` | 按 `schedule_id + occurrence_seq` 与 `user_id + request_id` 幂等保存每次 rating 与算法前后快照 | `review_scheduler.py` |
| 答题行为 | `answer_behaviors`、`practice_records`、`practice_sessions` | 记录耗时、正确性、会话时长和学习统计 | `behavior_service.py`、`practice_service.py` |
| 知识状态 | `user_knowledge_states`、`user_knowledge_adaptive_states`、`user_adaptive_profiles` | 按知识点维护掌握度、置信度和自适应学习状态 | `adaptive_learning_service.py`、`mastery_service.py`、`api/v1/knowledge_mastery.py` |
| 知识图谱 | `knowledge_points`、`knowledge_edges`、`question_knowledge_points` | 知识点、题目关联和图关系查询 | `knowledge_points.py`、`knowledge_map.py`、`knowledge_path.py`、`admin_knowledge.py` |
| 向量记忆 | 题目/知识点 embedding 与向量配置 | 相似题、语义检索和后台回填；配置 off、allowlist 未命中或服务不可用时按现有规则降级 | `embedding_endpoints.py`、`vector_retrieval_service.py`、`vector_config_service.py`、`admin_vector_config.py` |
| 推荐记忆 | 策略、实验、分配、曝光日志、日指标 | 推荐策略实验与效果评估 | recommendation services/API |
| AI 对话 | `ai_chats` | 保存对话上下文和响应，用于追溯与成本审计 | `ai_service.py` |

## 数据职责

### 复习调度

- `ReviewSchedule` 是 SM-2 的唯一数据源；`WrongQuestion` 不保存旧版 efactor、interval、repetitions、next_review_date、quality 字段，并与调度共用不可变题目版本绑定。
- `ReviewRecord` 只追加，不作为当前调度状态使用；schedule/occurrence 与 user/request 的唯一约束保证重试不重复记账。
- 评分范围为 0-5；未提供自评时，自动批改使用正确=4、错误=1 的映射。
- 复习时间使用 UTC 计算，面向学习日的 API 在服务层统一处理日期边界。

### 知识状态

- 题目与知识点通过 `question_knowledge_points` 关联表连接，该表是题目知识点关系的唯一事实源；不要读取已移除的 `questions.knowledge_points` 列。
- 用户知识状态与题目错题记录分离：错题回答“哪道题错过”，知识状态回答“该知识点掌握程度如何”。
- 自适应学习服务根据答题与复习数据更新状态，并为学习路径和推荐接口提供输入。

### AI 分析缓存

- AI 分析结果必须关联输入签名和模型签名；详情缓存判定为 ready、stale 或 empty，生成执行通过进程内集合及缓存启用时的跨进程租约限制重复请求（`ai/analysis_execution.py`），另有题目版本漂移守卫。缓存未启用时不提供跨进程互斥保证。
- 只有 ready 结果直接展示给小程序；stale 结果触发重新生成或预热，不作为新鲜结果返回。
- 题目声明需要视觉证据但缺少题图时，服务快速失败并返回结构化错误，不伪造视觉结论。

### 向量与图谱

- Embedding/向量检索能力已存在，但是否可用取决于向量配置、模型和部署环境；业务必须保留关键词/非向量降级路径。
- 知识图谱用于知识点关系和后台质量治理，不替代复习调度或用户知识状态表。

## 典型链路

```text
答题 → practice_records / answer_behaviors
     ├─ 答错 → wrong_questions + AI 分析缓存
     ├─ 复习 → review_schedules + review_records
     └─ 知识状态更新 → user_knowledge_states / adaptive states

检索/推荐 → 题目知识点关联 + 用户知识状态
          ├─ 向量可用：embedding / 向量检索
          └─ 向量不可用：关键词和规则降级
```

## 当前边界

- AI 分析缓存仍以题目/错题为主要粒度，不等同于跨会话自然语言记忆。
- 向量检索、知识图谱和推荐实验是独立能力，不能假设所有部署 profile 都已启用。
- 删除或重建题目时必须同步考虑知识点关联、embedding、错题和审计数据的引用关系。

## 相关文档

- [复习系统设计](./REVIEW_SYSTEM_DESIGN.md)
- [复习算法](./REVIEW_ALGORITHM.md)
- [数据库 schema](../backend/DB_SCHEMA.md)
- [AI 管线](../ai/AI_PIPELINE.md)
- [Admin API](../admin/ADMIN_API_SPEC.md)

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
