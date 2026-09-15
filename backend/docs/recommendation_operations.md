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

## 8. 回填 Embedding

当新题库导入或 embedding 模型更换后，需要为存量题目重新生成向量。

### 8.1 触发场景

- 新批次题目导入后，`question_embeddings` 表中缺少对应记录
- 更换 `EMBEDDING_MODEL` 或 `EMBEDDING_DIM` 后，旧向量与新模型不兼容
- 向量召回率异常偏低，怀疑大量题目未 embedding

### 8.2 增量构建逻辑

回填接口按 `(question_id, model_id)` 判定向量版本。每道题先使用现有
`build_question_embedding_text` 构建稳定文本并计算 `content_hash`：

- 无记录：调用 embedding API 并 INSERT
- 记录存在且 `content_hash` 不同：调用 embedding API 并通过
  `ON CONFLICT (question_id, model_id)` UPDATE
- 记录存在且 `content_hash` 相同：SKIP，不调用 API，不写库

已有记录不会被删除或清空。表上已有 `UNIQUE(question_id, model_id)` 约束，
可在并发 worker 冲突时兜底。批量流程先读取本批题目和现有 embedding，再统一
调用批量 embedding API；写入仍按题目使用 SAVEPOINT，单题失败不会破坏原向量。

### 8.3 操作步骤

1. 确认 embedding 服务可用：

```bash
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

2. 先预估影响范围，dry-run 不调用 embedding API，也不写数据库：

```bash
curl -X POST 'http://localhost:8000/api/admin/v1/questions/embeddings/backfill' \
  -H 'Authorization: Bearer <admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{"limit":200,"dry_run":true}'
```

3. 确认结果后执行增量回填：

```bash
curl -X POST 'http://localhost:8000/api/admin/v1/questions/embeddings/backfill' \
  -H 'Authorization: Bearer <admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{"limit":200,"dry_run":false}'
```

4. 验证重复、空 hash 和缺失记录：

```sql
SELECT question_id, model_id, COUNT(*)
FROM question_embeddings
GROUP BY question_id, model_id
HAVING COUNT(*) > 1;

SELECT COUNT(*)
FROM question_embeddings
WHERE content_hash IS NULL OR content_hash = '';

SELECT COUNT(*)
FROM questions q
LEFT JOIN question_embeddings qe
  ON qe.question_id = q.id AND qe.model_id = :model_id
WHERE q.id IS NOT NULL AND qe.id IS NULL;
```

### 8.4 注意事项

- `EMBEDDING_BATCH_SIZE` 控制批量大小，默认 16，生产可提升到 32~64
- embedding API 失败的题目记录日志并计为 `failed`，原 embedding 保持不变
- embedding 写入使用 `flush` 而非 `commit`，由外层事务控制

---

## 9. 知识点 Backfill

当科目知识点体系重建或题目-知识点映射缺失时，需要批量回填。

### 9.1 触发场景

- 新建科目后，`knowledge_points` 表中无该科目的知识点
- 导入题目后 `question_knowledge_points` 表缺少映射
- 知识图谱 `knowledge_edges` 表缺少前置关系

### 9.2 操作步骤

1. **创建知识点**：通过管理后台或脚本批量插入 `knowledge_points`

```
POST /api/admin/v1/knowledge/points
{
    "subject": "exam408-ds",
    "name": "二叉搜索树",
    "normalized_name": "二叉搜索树",
    "difficulty_level": 3
}
```

2. **关联题目与知识点**：

```
POST /api/admin/v1/knowledge/question-bindngs
{
    "question_id": 123,
    "knowledge_point_id": 45,
    "role": "main",
    "weight": 1.0
}
```

3. **推断知识边**：

```
POST /api/admin/v1/knowledge/edges/infer
{
    "subject": "exam408-ds"
}
```

推断的边 `source` 字段为 `inferred`，人工确认后可升级为 `manual`。

4. **验证**：

```sql
-- 检查每个科目的知识点数
SELECT subject, COUNT(*) FROM knowledge_points GROUP BY subject;

-- 检查无映射的题目数
SELECT COUNT(*) FROM questions q
WHERE NOT EXISTS (
    SELECT 1 FROM question_knowledge_points qkp
    WHERE qkp.question_id = q.id
);
```

### 9.3 注意事项

- `force_rebuild` 只删除 `source=inferred` 的边，不碰 `manual/imported/ai`
- 知识边删除会级联影响 `knowledge_path` 推荐结果
- 重建后需要清理缓存：`knowledge:path:*`、`practice:smart:*`

---

## 10. A/B 实验启停操作流程

### 10.1 创建实验

```
POST /api/admin/v1/recommendation/experiments
{
    "name": "smart_strategy_compare_v1",
    "scene": "practice_smart",
    "description": "比较 4 种 smart 策略",
    "variants": [
        {"key": "A", "strategy": "random", "ratio": 0.25},
        {"key": "B", "strategy": "weakness_vector", "ratio": 0.25},
        {"key": "C", "strategy": "knowledge_path", "ratio": 0.25},
        {"key": "D", "strategy": "similar_vector", "ratio": 0.25}
    ],
    "traffic_ratio": 1.0,
    "max_traffic_percent": 50.0,
    "auto_pause_on_error_rate": 0.5,
    "min_sample_size": 100,
    "fallback_strategy_name": "default_fallback"
}
```

### 10.2 启动实验

```
PATCH /api/admin/v1/recommendation/experiments/{id}/status
{
    "status": "running"
}
```

启动前检查：
- 确认至少有 2 个 variant
- 确认 `fallback_strategy_name` 在 `recommendation_strategy_configs` 中存在且 `is_active=true`
- 确认同 `scene` 下没有其他 `running` 状态的实验

### 10.3 暂停实验

```
PATCH /api/admin/v1/recommendation/experiments/{id}/status
{
    "status": "paused"
}
```

暂停场景：
- 手动暂停：管理员判断实验数据异常
- 自动暂停：`auto_pause_on_error_rate` 触发（需先调用 safety-check 接口检测）
- 暂停后已分配的用户继续使用当前 variant，新请求不再进入实验

### 10.4 恢复实验

```
PATCH /api/admin/v1/recommendation/experiments/{id}/status
{
    "status": "running"
}
```

### 10.5 结束实验

```
PATCH /api/admin/v1/recommendation/experiments/{id}/status
{
    "status": "finished"
}
```

结束后：
- 已分配用户记录保留，不再进入实验
- 使用 `GET /health-report` 查看实验期间指标对比
- 使用 `POST /metrics/backfill` 补跑实验期间的每日指标

### 10.6 状态转换规则

```
draft → running → paused → running → finished
  ↓
finished（提前终止）
```

不允许：`finished` → 任何其他状态。

---

## 11. 质量扫描流程

定期运行质量扫描，识别推荐系统的潜在问题。

### 11.1 每日扫描（推荐）

```bash
# 1. 获取健康报告
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/admin/v1/recommendation/health-report?subject=exam408-ds"
```

关注以下告警：

| 指标 | 阈值 | 含义 |
|------|------|------|
| `fallback_rate` | > 70% | 向量召回或知识路径服务异常 |
| `low_similarity_rate` | > 50% | embedding 质量下降或题库覆盖不足 |
| `vector_recall_failure_count` | > 30% × total | embedding 服务不可用 |
| `total_logs` | == 0 | 推荐系统完全未触发 |

### 11.2 每周扫描

除每日检查外，额外关注：

```bash
# 2. 检查实验状态
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/admin/v1/recommendation/experiments"

# 3. 对比各 variant 的 mastery_delta
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/admin/v1/recommendation/metrics?date_from=2026-06-21&date_to=2026-06-28"
```

### 11.3 质量门禁（建议标准）

| 指标 | 门禁值 | 未达标动作 |
|------|--------|-----------|
| fallback_rate | < 30% | 检查向量服务、embedding 覆盖率 |
| low_similarity_rate | < 30% | 检查 embedding 模型、题库多样性 |
| avg_mastery_delta | > 0.05 | 检查推荐策略权重、知识点映射质量 |
| experiment error_rate | < 10% | 暂停实验、检查代码逻辑 |

---

## 12. 系统边界

推荐系统与以下模块有明确边界，不会互相干扰：

| 模块 | 关系 |
|------|------|
| ReviewSchedule | 独立：推荐系统不读写复习调度数据 |
| SM-2 (sm2_service.py) | 独立：推荐系统不修改 SM-2 算法或调度状态 |
| WrongQuestion | 单向同步：ReviewSchedule → WrongQuestion（仅 last_review_at, mastered） |
| random/sequential 模式 | 不受影响：推荐系统仅作用于 smart 模式 |

---

## 13. 可观测性与监控

### 13.1 关键指标与获取方式

| # | 观测项 | 获取方式 | 告警阈值 |
|---|--------|---------|---------|
| 1 | vector fallback 次数 | `GET /health-report` → `fallback_rate` | > 70% |
| 2 | embedding API 失败次数 | `GET /health-report` → `vector_recall_failure_count` | > 30% × total_logs |
| 3 | recommendation_logs 写入失败 | 日志关键词 `"recommendation_log.*ERROR"` | 任何出现 |
| 4 | smart/similar/path 各策略请求量 | `SELECT strategy, COUNT(*) FROM recommendation_logs GROUP BY strategy` | 趋势突变 |
| 5 | random/sequential 基线请求量 | `SELECT mode, COUNT(*) FROM practice_records GROUP BY mode` | 趋势突变 |
| 6 | quality_issues 新增数量 | `GET /health-report` → `warnings` 列表 | 新告警出现 |
| 7 | DB 慢查询 | PostgreSQL `pg_stat_statements` 或 `log_min_duration_statement` | > 500ms |
| 8 | Redis 缓存命中率 | `redis-cli INFO stats` → `keyspace_hits / (keyspace_hits + keyspace_misses)` | < 60% |
| 9 | /ready 鉴权状态 | `curl -s -o /dev/null -w "%{http_code}" /api/admin/v1/health/ready`（无 token 应返回 401） | != 401 |

### 13.2 日志关键词（grep 用）

生产环境中通过以下关键词搜索推荐系统相关日志：

```
# Phase 5.0 新增结构化日志
"[VectorFallback]"                   — 向量召回降级到随机（含 scene/strategy/reason/subject）
"[EmbeddingError]"                   — embedding API 错误（含 provider/model/status_code）
"[RecLogError]"                      — 推荐日志写入失败（含 user_id/scene/strategy/error_type）
"[RecTiming]"                        — 推荐请求耗时（含 scene/strategy/elapsed_ms/candidate_count）

# 既有日志关键词
"resolve_strategy_for_user 失败"   — 推荐服务异常 fallback 到默认策略
"vector_recall"                     — 向量召回调用和结果
"embedding"                         — embedding API 请求/响应/错误
"knowledge_path"                    — 知识路径推荐
"experiment_assignment"             — 实验分配决策
"auto_pause"                        — 实验安全阀触发
"seed_strategies"                   — 策略种子初始化
"backfill"                          — 指标补跑
```

**排障示例**：

```bash
# 查找所有向量降级事件
grep '\[VectorFallback\]' /var/log/app.log | tail -20

# 查找 embedding API 超时
grep '\[EmbeddingError\].*timeout' /var/log/app.log

# 查找推荐日志写入失败
grep '\[RecLogError\]' /var/log/app.log

# 查找耗时超过 500ms 的推荐请求
grep '\[RecTiming\]' /var/log/app.log | awk -F'elapsed_ms=' '{print $2}' | awk '{if($1+0 > 500) print}'
```

### 13.3 定期监控脚本

```bash
# 每日推荐系统健康检查（建议加入 cron）
curl -s -H "Authorization: Bearer $ADMIN" \
     "$BASE/api/admin/v1/recommendation/health-report?subject=exam408-ds" \
     | python -c "
import sys, json
data = json.load(sys.stdin)
print(f'Logs (30d):     {data.get(\"total_recommendation_logs\", 0)}')
print(f'Fallback rate:  {data.get(\"fallback_rate\", 0):.2%}')
print(f'Low sim rate:   {data.get(\"low_similarity_rate\", 0):.2%}')
print(f'Vector fails:   {data.get(\"vector_recall_failure_count\", 0)}')
for w in data.get('warnings', []):
    print(f'WARNING: {w}')
"
```

### 13.4 Phase 5.0 已完成的增强

- ✅ `recommendation_logs` 写入失败时增加 `[RecLogError]` 结构化 WARNING 日志（含 user_id/scene/strategy/error_type）
- ✅ embedding API 错误增加 `[EmbeddingError]` 结构化日志（含 provider/model/status_code，不打印 API Key）
- ✅ 推荐请求耗时增加 `[RecTiming]` 日志（含 scene/strategy/elapsed_ms/candidate_count/returned_count）
- ✅ 向量召回降级增加 `[VectorFallback]` 日志（含 scene/strategy/reason/subject）

### 13.5 Phase 5.1+ 建议增强

- 接入 Prometheus metrics exporter 或 JSON structured logging
- 慢查询告警：`recommendation_logs` INSERT > 100ms
- embedding API 连续失败 > 5 次时触发熔断告警
