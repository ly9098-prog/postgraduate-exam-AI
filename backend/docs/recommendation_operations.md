# 推荐系统运维手册

本文档面向运维与管理员，覆盖推荐系统的日常操作、参数调整和故障处理。

---

## 1. 种子策略初始化

首次部署或策略配置被误删后，使用种子接口恢复 5 个默认策略。

### 接口

```
POST /api/admin/v1/recommendation/strategies/seed
```

### 参数

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| force | bool | false | `false` = 只补缺失字段，不覆盖管理员修改；`true` = 强制覆盖全部 |

### 5 个默认策略

| name | scene | 用途 |
|------|-------|------|
| `default_random` | practice_smart | 纯随机探索 |
| `default_weakness_vector` | practice_smart | 薄弱知识点向量召回（默认激活） |
| `default_knowledge_path` | knowledge_path | 知识路径推荐 |
| `default_similar_vector` | similar | 相似题向量召回 |
| `default_fallback` | practice_smart | 兜底策略 |

### 幂等性

- `force=false`：已存在的策略只补充 `None` 或空字符串字段，不覆盖管理员手动修改的权重
- `force=true`：完全覆盖为种子定义

---

## 2. 策略配置校验

创建或更新策略配置时，系统自动校验：

- `strategy_type`（如提供）必须在允许列表中：`weakness_vector`、`knowledge_path`、`similar_vector`、`rule_based`、`fallback_random`、`fallback`
- 权重字段必须为非负数字
- 单个权重超过 1 时记录警告（不报错，因为 `apply_strategy_weights` 会自动归一化）

不合法的配置返回 400 错误。

---

## 3. 实验安全阀

### 3.1 流量上限（max_traffic_percent）

创建实验时可设置 `max_traffic_percent`（默认 100.0），控制进入实验的用户比例。

- 用户通过稳定 hash（MD5）分配到 [0, 1) 区间
- `hash_value * 100 > max_traffic_percent` 的用户不进入实验，使用默认策略
- 设为 0 可完全暂停实验流量而不改变实验状态

### 3.2 自动暂停（auto_pause_on_error_rate）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `auto_pause_on_error_rate` | float | null | 错误率阈值，如 0.5 表示 50% |
| `min_sample_size` | int | 100 | 最小样本量，未达到时不触发暂停 |
| `fallback_strategy_name` | str | null | 实验失败时的兜底策略名 |

### 3.3 安全检查接口

```
POST /api/admin/v1/recommendation/experiments/{id}/safety-check
```

参数：`date_from`、`date_to`

返回：

```json
{
  "paused": true,
  "reason": "错误率 65.00% 超过阈值 50.00%",
  "metrics": {
    "total_answers": 200,
    "total_errors": 130,
    "error_rate": 0.65,
    "min_sample_size": 100,
    "auto_pause_threshold": 0.5
  }
}
```

当错误率超过阈值且样本量充足时，自动将实验状态设为 `paused`。

---

## 4. 指标聚合与补跑

### 4.1 日常聚合

`aggregate_recommendation_metrics_daily` 从 `recommendation_logs` 聚合指定日期的指标，UPSERT 到 `recommendation_metrics_daily` 表。

- 幂等：同一天重复运行会覆盖而非累加
- 按 `(date, subject, scene, strategy, variant_key)` 作为唯一键

### 4.2 补跑接口

```
POST /api/admin/v1/recommendation/metrics/backfill
```

参数：

```json
{
  "date_from": "2026-06-01",
  "date_to": "2026-06-28",
  "subject": "exam408-ds"
}
```

- 逐天补跑，单天失败不影响其他天
- 返回 `success_dates`、`failed_dates`、`errors`

---

## 5. 健康报告

```
GET /api/admin/v1/recommendation/health-report?subject=exam408-ds
```

返回字段：

| 字段 | 说明 |
|------|------|
| `total_recommendation_logs` | 30 天内推荐日志总数 |
| `fallback_rate` | 兜底策略使用比例 |
| `low_similarity_rate` | 相似度 < 0.3 的比例 |
| `experiment_assignment_count` | 进入实验的日志数 |
| `experiment_variant_distribution` | 各实验分组分布 |
| `vector_recall_failure_count` | 向量召回失败数 |
| `top_fallback_scenes` | Top 5 fallback 场景 |
| `top_error_strategies` | Top 5 错误率策略 |
| `warnings` | 自动生成的告警列表 |

### 告警规则

- fallback_rate > 70% → "Fallback 率过高"
- low_similarity_rate > 50% → "低相似度率过高"
- total_logs == 0 → "30 天内无推荐日志"
- vector_recall_failure_count > 30% * total_logs → "向量召回失败率超过 30%"

---

## 6. 缓存失效

推荐系统使用 Redis 缓存加速，以下操作会自动清理相关缓存：

| 操作 | 清理的缓存 pattern |
|------|-------------------|
| 策略配置创建/更新 | `recommendation:strategy:*` |
| 实验状态更新 | `recommendation:experiment:*` |
| 知识边 force_rebuild | `knowledge:path:*`、`practice:smart:*`、`recommendation:path:*` |

Redis 不可用时静默降级（不报错），缓存自然过期后生效。

---

## 7. 故障处理

### 7.1 推荐系统整体不可用

1. 检查 `GET /health-report` 是否正常返回
2. 如果 fallback_rate 接近 100%，说明向量召回或知识路径服务异常
3. 临时方案：将所有 smart 请求降级为 random 模式
4. 推荐错误不影响 random/sequential 模式

### 7.2 实验服务异常

- `resolve_strategy_for_user` 捕获所有异常，自动 fallback 到默认策略
- 不会导致 500 错误
- 日志中搜索 "resolve_strategy_for_user 失败" 可定位问题

### 7.3 指标数据缺失

1. 使用 backfill 接口补跑缺失日期
2. 检查 `recommendation_logs` 表是否有对应日期的数据
3. 如果日志表也缺失，检查 `practice_service` 是否正确写入日志

---

## 8. 系统边界

推荐系统与以下模块有明确边界，不会互相干扰：

| 模块 | 关系 |
|------|------|
| ReviewSchedule | 独立：推荐系统不读写复习调度数据 |
| SM-2 (sm2_service.py) | 独立：推荐系统不修改 SM-2 算法或调度状态 |
| WrongQuestion | 单向同步：ReviewSchedule → WrongQuestion（仅 last_review_at, mastered） |
| random/sequential 模式 | 不受影响：推荐系统仅作用于 smart 模式 |
