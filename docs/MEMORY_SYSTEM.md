# Memory System

> 本项目没有向量库，没有知识图谱，没有独立的"记忆模块"。记忆能力分散在三个地方：**错题缓存**、**SM-2 调度字段**、**行为记录表**。

---

## 当前实现

### 记忆存储分布

| 存储位置 | 存储内容 | 用途 | 查询方式 |
|---|---|---|---|
| `WrongQuestion.ai_analysis` (JSON) | 每道错题的 AI 分析结果 | 错题分析缓存 | `ai_service.analyze_error` 检索引擎 |
| `WrongQuestion.efactor / interval / repetitions / next_review_date` (标量) | SM-2 间隔重复参数 | 复习调度 | `review_service.get_due_reviews` |
| `AnswerBehavior` 表 | 每题答题行为（耗时、首答正确、最终正确、switch 次数） | 行为统计 | `behavior_service.get_behavior_stats` |
| `AiChat` 表 | AI 对话记录（messages + response + context_snapshot） | 成本审计 / 调用追溯 | 直接查表 |
| `PracticeRecord` 表 | 每次练习记录（题目列表、答案、正确/错误数） | 练习历史 | `practice_service.list_records` |

### 各模块记忆能力

**AI 模块**
- 有缓无忆：错题分析结果缓存（`WrongQuestion.ai_analysis`），但没有跨对话的用户知识状态
- 每次 `study_advice` 调用独立，不记忆上次推荐了什么

**复习模块**
- SM-2 字段直接挂在 `WrongQuestion` 表上，每道错题独立调度
- `get_review_stats` 汇总统计（待复习数、已掌握数、平均 EF、各科目分布）

**练习模块**
- `AnswerBehavior` 记录每题全量行为数据，支持正确率 / 平均耗时 / 按科目统计
- `get_behavior_stats` 提供整体学习画像

### 当前"记忆"的局限

- **没有用户知识状态模型** — 系统不知道用户"掌握了什么知识点"，只知道"哪些题做错了"
- **没有语义检索** — `WrongQuestion.ai_analysis` 只能按 primary key 查，不能按知识点内容查
- **缓存在错题行上** — 如果 `WrongQuestion` 行被删除，关联的 AI 分析也丢失
- **AiChat 表只写不读** — 数据有积累，但没有接口消费

---

## 存在问题

1. **知识点掌握度不可计算** — 无法回答"用户的极限掌握到什么程度了"，因为 `knowledge_points` 挂在 `Question` 表而非 `WrongQuestion`，没有聚合统计
2. **重复错题归并缺失** — 同一道题错多次会 upsert，但 `error_type` 未保留历史变化轨迹
3. **无遗忘曲线可视化数据** — `AnswerBehavior` 有每题记录，但缺少按知识点聚合的准确率趋势
4. **缓存无时效标记** — `WrongQuestion.ai_analysis` 没有 `cached_at`，无法判断缓存是否过期

---

## 下一阶段扩展方案

### Phase 1 — 知识点聚合统计（1 天）

- **wrong_question_service.py** 新增 `get_knowledge_stats(db, user_id)`：
  - 读取用户所有错题的 `Question.knowledge_points`，合并统计各知识点出现次数
  - 计算各知识点掌握率 = 最近 N 次正确 / 总练习次数（关联 `AnswerBehavior`）
  - 返回 `[{knowledge_point, wrong_count, accuracy, last_practiced_at}]`
- 新增路由 `GET /api/v1/wrong-questions/knowledge-stats`

### Phase 2 — 简单推荐（1 天）

- 基于 `get_knowledge_stats` 输出薄弱知识点列表
- practice_service 扩充 `get_batch_questions`，支持按知识点筛选
- 新增 `GET /api/v1/practice/recommend?count=10&focus_weak=true`
  - 从薄弱知识点关联的题目中随机选取

### Phase 3 — 复习优先级排序（1 天）

- `review_service.get_due_reviews` 增加优先级排序：
  - 优先级因子 = 错题次数 × (1 - 最近正确率) × EF 倒数
  - 同天待复习题目按优先级排序返回

### 明确不做的

- ❌ 向量嵌入 / 语义检索（关键词匹配够用）
- ❌ 知识图谱
- ❌ 个性化 ML 推荐
- ❌ 跨用户记忆共享
- ❌ 用户知识状态持久化框架（直接在现有表上加字段和查询即可）
- ❌ 主动遗忘模型 / 预测遗忘曲线
