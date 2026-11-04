# 阶段 5：学习数据系统 + 分析看板 ✅

**目标**：基于刷题数据建立多维度统计、知识点掌握度评估、学习趋势分析

### 核心模块

1. **学习数据统计系统** — 多维度学习数据聚合与展示
2. **知识点掌握度系统** — 基于正确率 + 间隔重复的知识点级掌握评估
3. **学习趋势分析系统** — 正确率、学习量、掌握度的时序变化
4. **遗忘趋势分析系统** — 识别短期记住但长期遗忘的假掌握
5. **长期学习画像** — 基于累计数据的个性化学习诊断

### 新 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/stats/overview | 学习总览 |
| GET | /api/v1/stats/subject/{subject} | 学科统计 |
| GET | /api/v1/stats/knowledge-points | 知识点掌握度 |
| GET | /api/v1/stats/trends | 学习趋势 |
| GET | /api/v1/stats/behavior | 学习行为分析 |
| GET | /api/v1/stats/forget-trends | 遗忘趋势分析 |
| GET | /api/v1/knowledge-points | 知识点树 |
| PUT | /api/v1/questions/{id}/knowledge-points | 关联知识点 |

### 掌握度模型

```
mastery = correct_rate * (1 - forget_factor) * recency_bonus

阈值: >= 0.8 掌握良好 | 0.5-0.8 需巩固 | < 0.5 薄弱
```

### 关键文件

```
backend/app/models/knowledge_point.py   # 知识点 model（树形结构）
backend/app/schemas/stats.py            # 统计 schema
backend/app/services/stats_service.py   # 统计数据聚合
backend/app/services/knowledge_service.py # 知识点管理
backend/app/api/v1/stats.py             # 统计 API
backend/app/api/v1/knowledge_points.py   # 知识点 API
```

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
