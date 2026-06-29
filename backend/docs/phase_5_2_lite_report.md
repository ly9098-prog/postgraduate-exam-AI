# Phase 5.2 向量召回验收报告（Lite）

**日期**: 2026-06-29
**基线**: Phase 5.1 灰度发布验证通过
**测试文件**: `tests/test_services/test_phase5_2_vector_acceptance.py`
**测试结果**: 58 passed / 0 failed
**全量测试**: 2475 passed / 6 skipped / 18 xfailed / 0 failed

---

## 1. VECTOR_MODE 实现与验证

### 1.1 新增配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| VECTOR_MODE | str | "off" | off / shadow / allowlist / all |
| VECTOR_ALLOWLIST | str | "" | JSON 列表，允许 subject 或 user_id |

### 1.2 四种模式验证

| 模式 | 行为 | 测试通过 |
|------|------|----------|
| off | 向量功能完全禁用，所有调用返回 fallback | PASS (4 tests) |
| shadow | 向量检索执行但结果不返回给用户，仅记录日志 | PASS (3 tests) |
| allowlist | 仅对 VECTOR_ALLOWLIST 中的 subject/user_id 启用 | PASS (6 tests) |
| all | 对所有用户/科目启用向量 | PASS (2 tests) |

### 1.3 向后兼容

- `VECTOR_ENABLED=True` + `VECTOR_MODE="off"` → 自动解析为 `"all"`
- 无效 VECTOR_MODE → 回退为 `"off"` 并记录 warning

---

## 2. 质量验证

### 2.1 答案泄漏检查

| 检查项 | 方法 | 结果 |
|--------|------|------|
| embedding 文本不含 answer | `build_question_embedding_text()` 源码审查 | PASS |
| 多种题型验证 | choice/true_false/judgement 均验证 | PASS |
| 答案不作为独立标记 | 文本中不出现 `答案：{answer}` | PASS |

### 2.2 自排除 / 跨科目 / 去重

| 检查项 | SQL 验证 | 结果 |
|--------|----------|------|
| search_similar 排除源题 | `question_id != :qid` | PASS |
| search_similar 限制同科目 | `qe.subject = :subject` | PASS |
| vector_recall 科目过滤 | `qe.subject = :subject OR LIKE :subject_prefix` | PASS |
| exclude_answered 子查询 | `NOT IN (SELECT question_id FROM practice_records ...)` | PASS |

### 2.3 Seed Question 抽样

| 检查项 | 结果 |
|--------|------|
| 抽样条件: is_active=True + review_status=approved | PASS |
| 60 个 seed question embedding 唯一性 | PASS |
| 难度分布均匀（每级 ≥10 题） | PASS |
| embedding 文本包含科目/题型/知识点/题干 | PASS |

---

## 3. 故障注入测试（6 种场景）

| # | 故障类型 | 注入方式 | Fallback 行为 | 结果 |
|---|----------|----------|--------------|------|
| 1 | Embedding API 超时 | httpx.TimeoutException | get_embedding → None → 上层 fallback | PASS |
| 2 | pgvector 查询异常 | db.execute raises Exception | search_similar → enabled=False, strategy=fallback | PASS |
| 3 | Embedding 维度错误 | 返回 512 维（期望 1024） | get_embedding → None（维度校验拦截） | PASS |
| 4 | Embedding 缺失 | _ensure_source_embedding 无结果 | search_similar → enabled=False, fallback | PASS |
| 5 | 空候选集 | pgvector 返回 0 行 | search_similar → enabled=True, recommendations=[] | PASS |
| 6 | 配置错误 | EMBEDDING_API_KEY="" | is_vector_enabled → False | PASS |

**全部 6 种故障场景均验证了自动 fallback，且 random/sequential/submit/review/wrong question 主链路不受影响。**

---

## 4. 主链路完整性

| 链路 | 向量依赖 | 验证方法 | 结果 |
|------|----------|----------|------|
| random 刷题 | 无 | 源码审查：无 vector 调用 | PASS |
| sequential 刷题 | 无 | 源码审查：order_by(id.asc()) | PASS |
| submit_answer | 无 | 源码审查：无 vector_retrieval 调用 | PASS |
| PracticeRecord 写入 | 无 | mock DB 验证 db.add + db.commit | PASS |
| 错题记录 | 无 | 答错时 record_wrong 被调用 | PASS |
| 掌握度更新 | 无 | 失败时 try/except 捕获，不影响 submit | PASS |
| ReviewSchedule/SM-2 | 无 | submit 路径不调用 SM-2 调度 | PASS |

---

## 5. Shadow 模式验证

| 检查项 | 结果 |
|--------|------|
| shadow 模式下 is_vector_enabled 返回 True（基础设施可用） | PASS |
| shadow 模式下 similar 模式返回 fallback 结果 | PASS |
| shadow 模式下 smart 模式不返回向量结果 | PASS |
| shadow 模式执行向量检索并记录 [ShadowMode] 日志 | PASS |
| shadow 模式不改变实际用户结果 | PASS |

---

## 6. 性能基准

### 6.1 本地操作延迟（VECTOR_MODE=off fallback 路径）

| 操作 | P50 | P95 | 阈值 |
|------|-----|-----|------|
| is_vector_enabled() | <1ms | <5ms | <10ms |
| search_similar_questions() fallback | <1ms | <5ms | <10ms |
| vector_recall_by_text() fallback | <1ms | <5ms | <10ms |
| 假 embedding 生成 | 0.009ms | 0.010ms | <1ms |
| 余弦相似度计算 | 0.005ms | 0.005ms | <1ms |

### 6.2 生产环境预期（PostgreSQL + pgvector）

| 操作 | 预期 P50 | 预期 P95 | 说明 |
|------|----------|----------|------|
| pgvector cosine search (top 100) | 5-20ms | 20-50ms | 依赖 HNSW 索引 |
| embedding API 调用 | 100-300ms | 300-500ms | 依赖网络 |
| 端到端 smart/similar | 150-350ms | 350-500ms | API + pgvector + re-ranking |

---

## 7. Allowlist 灰度策略

| 策略 | 配置示例 | 适用场景 |
|------|----------|----------|
| 按科目灰度 | `VECTOR_ALLOWLIST='["exam408-ds"]'` | 先在数据结构科目验证 |
| 按用户灰度 | `VECTOR_ALLOWLIST='[1,2,3]'` | 内部测试用户先行 |
| 空 allowlist | `VECTOR_ALLOWLIST=''` | 全部允许（灰度初期） |
| 混合 | `VECTOR_ALLOWLIST='["exam408-ds", 42]'` | 科目 + 特定用户 |

---

## 8. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/core/config.py` | 新增字段 | VECTOR_MODE, VECTOR_ALLOWLIST |
| `app/services/vector_retrieval_service.py` | 新增函数 | resolve_vector_mode(), is_shadow_mode(), _parse_allowlist(), is_vector_allowed_for() |
| `app/services/vector_retrieval_service.py` | 修改 | is_vector_enabled() 集成 VECTOR_MODE 检查 |
| `app/services/practice_service.py` | 修改 | get_similar_practice_questions() 增加 shadow 模式分支 |
| `app/services/practice_service.py` | 修改 | get_smart_practice_questions() 增加 shadow 模式分支 |
| `tests/test_services/test_phase5_2_vector_acceptance.py` | 新增 | 58 个验收测试 |

---

## 9. 结论

### CONDITIONAL PASS

**可以开启 VECTOR_MODE=allowlist 进行小流量灰度，但需先修复以下问题：**

1. **PostgreSQL + pgvector 环境未验证**: 当前测试环境为 SQLite，pgvector 相关 SQL（`<=>` 操作符、`::vector` 类型转换）未在生产 PostgreSQL 环境执行验证。部署前需确认：
   - PostgreSQL 版本 ≥ 13
   - pgvector 扩展已安装 (`CREATE EXTENSION vector`)
   - `question_embeddings` 表通过 `_ensure_vector_schema()` 自动创建
   - HNSW 索引创建成功（或 best-effort 降级）

2. **Embedding API 凭据未配置**: 当前 `EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL` 为空。生产部署前需配置有效的 embedding 服务端点。

3. **FK 约束 defer**: `practice_records.question_id` 的 FK 约束在迁移中 defer（SQLite 不支持 ALTER TABLE ADD FK）。PostgreSQL 部署时需单独 migration 添加。

### 灰度启动顺序建议

```
Step 1: VECTOR_MODE=off（当前状态，已验证）
Step 2: VECTOR_MODE=shadow（配置好 embedding API + PostgreSQL 后）
Step 3: VECTOR_MODE=allowlist（shadow 24h 无异常后，小科目灰度）
Step 4: VECTOR_MODE=all（allowlist 24h 无异常后，全量开启）
```

### 回滚方案

- 代码回滚: 设置 `VECTOR_MODE=off` 即可立即回退，无需代码变更
- 迁移回滚: pgvector schema 由 runtime 创建，不影响 alembic 迁移链

---

## 附录: 测试用例清单（58 tests）

| 类 | 测试数 | 覆盖范围 |
|----|--------|----------|
| TestVectorModeResolution | 8 | 模式解析、向后兼容、无效值处理 |
| TestVectorModeOff | 4 | off 模式全禁用 |
| TestVectorModeShadow | 3 | shadow 模式不影响用户结果 |
| TestVectorModeAllowlist | 6 | subject/user 白名单过滤 |
| TestVectorModeAll | 2 | all 模式无限制 |
| TestQualityVerification | 9 | 答案泄漏、自排除、同科目、确定性 |
| TestFaultInjection | 7 | 6 种故障 + fallback 验证 |
| TestMainChainIntegrity | 7 | random/sequential/submit 无向量依赖 |
| TestPerformanceBenchmark | 4 | P50/P95 延迟 |
| TestSeedQuestionSampling | 5 | 抽样逻辑、唯一性、难度分布 |
| TestAcceptanceMetrics | 3 | 覆盖率验证 |
