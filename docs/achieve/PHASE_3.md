# 阶段 4：SM-2 智能复习系统 ✅

**目标**：升级为间隔重复驱动的动态复习系统

| 项目 | 内容 |
|------|------|
| 数据库 | review_schedules（新增） |
| 后端 | SM-2 算法实现、复习调度逻辑、质量评分接口 |
| 前端 | 复习评分交互、待复习队列、复习统计 |
| AI | ❌ 无（纯算法调度） |

### SM-2 算法

```
质量评分 q (0-5):
  5 = 完全正确，毫不犹豫
  4 = 正确，稍有犹豫
  3 = 正确，但较困难
  2 = 错误，但能想起来正确答案
  1 = 错误，想起来正确答案但很困难
  0 = 完全错误，毫无印象

更新规则:
  if q < 3: repetitions = 0, interval = 1
  else:
    if repetitions == 0: interval = 1
    elif repetitions == 1: interval = 6
    else: interval = round(interval * ease_factor)
    repetitions += 1
  ease_factor = max(1.3, ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
  next_review_date = today + interval
```

### 设计原则

- 不推翻现有 wrong_questions / review_plans，渐进式增强
- review_plans 面向用户"每日复习题单"，SM-2 做后端调度引擎
- 混合模式：wrong_questions 短期复习 + review_schedules 长期巩固
- 最多 3 表 join，保持查询高效

### 关键文件

```
backend/app/services/sm2_service.py   # SM-2 算法核心 + 调度
backend/app/services/review_service.py # 复习计划服务
```

详细算法见 `/docs/REVIEW_ALGORITHM.md`。
