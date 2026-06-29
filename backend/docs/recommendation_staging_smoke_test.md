# 推荐系统 Staging Smoke Test

在 staging 环境执行以下测试，验证推荐系统核心路径可用。
所有命令假设 `$BASE` 为 API 地址，`$TOKEN` 为用户 JWT，`$ADMIN` 为管理员 JWT。

---

## 前置条件

```bash
BASE="https://staging-api.example.com"
# 获取用户 token
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"13800138000","password":"test1234"}' \
  | python -m json.tool | grep access_token | awk -F'"' '{print $4}')

# 获取管理员 token
ADMIN=$(curl -s -X POST "$BASE/api/admin/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python -m json.tool | grep access_token | awk -F'"' '{print $4}')
```

---

## 1. random 刷题（基线模式，不依赖推荐系统）

```bash
curl -s "$BASE/api/v1/practice/questions?mode=random&subject=exam408-ds&count=5" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回 5 道题目，顺序随机
- `strategy` 字段为 `random` 或空

---

## 2. sequential 刷题（基线模式，不依赖推荐系统）

```bash
curl -s "$BASE/api/v1/practice/questions?mode=sequential&subject=exam408-ds&count=5" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回 5 道题目，按 ID 升序
- `strategy` 字段为 `sequential` 或空

---

## 3. smart 刷题（推荐系统核心路径）

```bash
curl -s "$BASE/api/v1/practice/questions?mode=smart&subject=exam408-ds&count=5" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回题目列表
- `strategy` 字段标识使用的策略（如 `weakness_vector`、`knowledge_path`、`fallback_random`）
- 如果 embedding 未配置，应 fallback 到 random，不报错

**降级验证：**

```bash
# VECTOR_ENABLED=false 时，smart 应退化为 random
curl -s "$BASE/api/v1/practice/questions?mode=smart&subject=exam408-ds&count=5" \
  -H "Authorization: Bearer $TOKEN" | python -c "
import sys, json
data = json.load(sys.stdin)
assert 'questions' in data
assert len(data['questions']) > 0
print('smart fallback OK, strategy:', data.get('strategy', 'N/A'))
"
```

---

## 4. similar 推荐（向量召回路径）

```bash
# 先获取一个有效 question_id
QID=$(curl -s "$BASE/api/v1/practice/questions?mode=random&subject=exam408-ds&count=1" \
  -H "Authorization: Bearer $TOKEN" | python -c "import sys,json;print(json.load(sys.stdin)['questions'][0]['id'])")

curl -s "$BASE/api/v1/practice/questions?mode=similar&question_id=$QID&count=5" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回相似题目列表
- 如果 embedding 不可用，应 fallback 到 random，不报错

---

## 5. knowledge path 推荐（知识图谱路径）

```bash
curl -s "$BASE/api/v1/knowledge-path?subject=exam408-ds" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回学习路径推荐
- 如果知识边为空，应返回空路径或降级提示，不报错

---

## 6. recommendation metrics（指标聚合）

### 6.1 健康报告

```bash
curl -s "$BASE/api/admin/v1/recommendation/health-report?subject=exam408-ds" \
  -H "Authorization: Bearer $ADMIN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回指标数据（即使日志为空也不报错）
- 包含 `total_recommendation_logs`、`fallback_rate`、`warnings` 等字段

### 6.2 指标补跑

```bash
curl -s -X POST "$BASE/api/admin/v1/recommendation/metrics/backfill" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"date_from":"2026-06-27","date_to":"2026-06-28","subject":"exam408-ds"}' \
  | python -m json.tool
```

**预期：**
- HTTP 200
- 返回 `success_dates` 和 `failed_dates`
- 幂等：重复调用不产生重复数据

---

## 7. quality scan（质量扫描）

```bash
# 健康报告即质量扫描入口
curl -s "$BASE/api/admin/v1/recommendation/health-report?subject=exam408-ds" \
  -H "Authorization: Bearer $ADMIN" | python -c "
import sys, json
data = json.load(sys.stdin)
print('=== Quality Scan Results ===')
print(f'Total logs (30d): {data.get(\"total_recommendation_logs\", 0)}')
print(f'Fallback rate:    {data.get(\"fallback_rate\", 0):.2%}')
print(f'Low sim rate:     {data.get(\"low_similarity_rate\", 0):.2%}')
print(f'Vector failures:  {data.get(\"vector_recall_failure_count\", 0)}')
warnings = data.get('warnings', [])
if warnings:
    print('WARNINGS:')
    for w in warnings:
        print(f'  - {w}')
else:
    print('No warnings. Quality OK.')
"
```

---

## 8. strategy config（策略配置）

### 8.1 种子策略初始化

```bash
curl -s -X POST "$BASE/api/admin/v1/recommendation/strategies/seed" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"force": false}' | python -m json.tool
```

**预期：**
- HTTP 200
- 返回创建的 5 个默认策略
- 幂等：重复调用不覆盖已有策略（`force=false`）

### 8.2 查询策略列表

```bash
curl -s "$BASE/api/admin/v1/recommendation/strategies" \
  -H "Authorization: Bearer $ADMIN" | python -m json.tool
```

**预期：**
- HTTP 200
- 返回策略列表（至少 5 个种子策略）

### 8.3 创建自定义策略

```bash
curl -s -X POST "$BASE/api/admin/v1/recommendation/strategies" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test_custom_strategy",
    "display_name": "测试自定义策略",
    "scene": "practice_smart",
    "weight_vector_similarity": 0.6,
    "weight_knowledge_overlap": 0.2,
    "weight_difficulty_match": 0.1,
    "weight_mastery_gap": 0.05,
    "weight_path_priority": 0.05,
    "exploration_ratio": 0.15
  }' | python -m json.tool
```

**预期：**
- HTTP 200 或 201
- 返回创建的策略详情

---

## 9. experiment assignment（实验分配）

### 9.1 创建实验

```bash
curl -s -X POST "$BASE/api/admin/v1/recommendation/experiments" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "smoke_test_experiment",
    "scene": "practice_smart",
    "description": "smoke test",
    "variants": [
      {"key": "A", "strategy": "random", "ratio": 0.5},
      {"key": "B", "strategy": "weakness_vector", "ratio": 0.5}
    ],
    "traffic_ratio": 1.0,
    "max_traffic_percent": 100.0
  }' | python -m json.tool
```

### 9.2 启动实验

```bash
EXP_ID=$(curl -s "$BASE/api/admin/v1/recommendation/experiments" \
  -H "Authorization: Bearer $ADMIN" | python -c "
import sys, json
exps = json.load(sys.stdin)
for e in exps:
    if e['name'] == 'smoke_test_experiment':
        print(e['id']); break
")

curl -s -X PATCH "$BASE/api/admin/v1/recommendation/experiments/$EXP_ID/status" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"status": "running"}' | python -m json.tool
```

### 9.3 验证实验分配

```bash
# 用 smart 模式刷题，应触发实验分配
curl -s "$BASE/api/v1/practice/questions?mode=smart&subject=exam408-ds&count=3" \
  -H "Authorization: Bearer $TOKEN" | python -c "
import sys, json
data = json.load(sys.stdin)
print('Strategy used:', data.get('strategy', 'N/A'))
print('Experiment ID:', data.get('experiment_id', 'N/A'))
print('Variant:', data.get('variant_key', 'N/A'))
"
```

**预期：**
- `experiment_id` 非空
- `variant_key` 为 `A` 或 `B`

### 9.4 结束实验

```bash
curl -s -X PATCH "$BASE/api/admin/v1/recommendation/experiments/$EXP_ID/status" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"status": "finished"}' | python -m json.tool
```

### 9.5 安全检查

```bash
curl -s -X POST "$BASE/api/admin/v1/recommendation/experiments/$EXP_ID/safety-check" \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"date_from": "2026-06-28", "date_to": "2026-06-28"}' | python -m json.tool
```

---

## 10. 健康端点

### 10.1 Liveness（无鉴权）

```bash
curl -s "$BASE/api/admin/v1/health/live"
```

**预期：** `{"status": "ok"}`

### 10.2 Readiness（需鉴权）

```bash
# 无 token 应返回 401
curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/v1/health/ready"
# 预期: 401

# 有 token 应返回 200
curl -s "$BASE/api/admin/v1/health/ready" \
  -H "Authorization: Bearer $ADMIN" | python -m json.tool
# 预期: {"status": "ok", "db": "ok", "redis": "ok"|"degraded"}
```

---

## 11. 回归验证（既有功能不受影响）

### 11.1 SM-2 复习

```bash
curl -s "$BASE/api/v1/review/today?subject=exam408-ds" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：** HTTP 200，返回今日复习题目

### 11.2 错题本

```bash
curl -s "$BASE/api/v1/wrong-questions?subject=exam408-ds" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期：** HTTP 200，返回错题列表

---

## 汇总检查

执行完全部 smoke test 后，运行以下 SQL 验证数据完整性：

```sql
-- 确认所有表存在
SELECT table_name FROM information_schema.tables
WHERE table_name IN (
    'knowledge_points', 'question_knowledge_points', 'knowledge_edges',
    'user_knowledge_states', 'recommendation_logs',
    'recommendation_strategy_configs', 'recommendation_experiments',
    'recommendation_experiment_assignments', 'recommendation_metrics_daily'
)
ORDER BY table_name;
-- 预期: 9 行

-- 确认种子策略存在
SELECT name, scene, is_active FROM recommendation_strategy_configs;
-- 预期: 至少 5 行

-- 确认推荐日志有写入
SELECT COUNT(*) FROM recommendation_logs WHERE created_at > CURRENT_DATE - INTERVAL '1 day';
-- 预期: > 0（如果执行了 smart/similar 刷题）

-- 确认实验分配有记录
SELECT COUNT(*) FROM recommendation_experiment_assignments;
-- 预期: >= 0
```

---

## 结果记录

| # | 测试项 | 结果 | 备注 |
|---|--------|------|------|
| 1 | random 刷题 | | |
| 2 | sequential 刷题 | | |
| 3 | smart 刷题 | | |
| 4 | similar 推荐 | | |
| 5 | knowledge path | | |
| 6 | recommendation metrics | | |
| 7 | quality scan | | |
| 8 | strategy config | | |
| 9 | experiment assignment | | |
| 10 | 健康端点 | | |
| 11 | 回归验证 | | |
