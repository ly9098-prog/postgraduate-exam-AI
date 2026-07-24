# 生产 EXPLAIN ANALYZE 结果

> 执行时间：2026-07-24 | 服务器：8.163.56.109 | 数据库：PostgreSQL 15 (deploy-postgres-1)

## 数据库概况

| 表 | 行数 | 大小 |
|---|------|------|
| questions | 1,176 | 3,472 kB |
| pomodoro_sessions | 87 | 128 kB |
| review_records | 10 | 56 kB |
| wrong_questions | ~27 | 152 kB |
| review_schedules | ~27 | 56 kB |
| practice_records | ~36 | 96 kB |

> 当前为早期生产环境，数据量较小。查询计划在数据增长后会自动切换为索引扫描。

## 查询分析摘要

### 1. 今日复习 (review_schedules + questions JOIN)
- **修复前**：Seq Scan on review_schedules (rows=27, 无 next_review_at 索引)
- **修复后**：新索引 `ix_review_schedules_user_next_review(user_id, next_review_at) WHERE mastered=false`
- **计划**：当前使用 Seq Scan (小表最优)，数据增长后自动切换 Index Scan
- **结论**：✅ 索引已创建，随数据增长生效

### 2. 错题列表 (wrong_questions + questions JOIN, ORDER BY created_at DESC)
- **修复前**：Sort (cost=25.96..26.01) on wq.created_at DESC，无覆盖索引
- **修复后**：新索引 `ix_wq_user_active_created(user_id, is_active, created_at DESC)` 替换旧的 `ix_wq_user_active_next`
- **计划**：当前使用 Sort + Seq Scan (小表最优)
- **结论**：✅ 覆盖索引已创建

### 3. 错题统计 (GROUP BY subject_id)
- **计划**：HashAggregate → Merge Join → Index Scan(questions_pkey) + Sort(wrong_questions)
- **执行时间**：0.176ms
- **结论**：✅ 正常

### 4. Practice 推荐 (questions LEFT JOIN user_knowledge_states via subquery)
- **计划**：Seq Scan on questions → nested subquery per row (1173 loops)
- **执行时间**：4.053ms
- **风险**：⚠️ 逐题子查询 (question_knowledge_points lookup × 1173)，数据增长时需批量优化
- **建议**：考虑 JOIN 替代相关子查询

### 5. 知识状态 (user_knowledge_states + knowledge_points)
- **计划**：Hash Join，使用 idx_uks_user_mastery_conf
- **执行时间**：0.048ms
- **结论**：✅ 正常

### 6. Pipeline 状态 (import_pipelines + import_pipeline_chunks GROUP BY)
- **计划**：HashAggregate → Hash Left Join
- **执行时间**：0.078ms
- **结论**：✅ 正常

### 7. Question Import Review Queue (question_imports LEFT JOIN import_pipelines)
- **计划**：Nested Loop Left Join，使用 ix_question_imports_status
- **执行时间**：0.067ms
- **结论**：✅ 正常（当前无待审核题目）

### 8. Pomodoro 到期扫描
- **计划**：Seq Scan on pomodoro_sessions (rows=87)
- **执行时间**：0.039ms
- **结论**：✅ 正常（87行无需索引）

### 9. Audit Log Cleanup
- **计划**：DELETE → Hash Semi Join → Seq Scan × 2
- **执行时间**：0.082ms
- **结论**：✅ 正常

## 已创建的索引 (v13)

| 索引 | 表 | 列 | 用途 |
|------|-----|-----|------|
| `ix_review_schedules_user_next_review` | review_schedules | (user_id, next_review_at) WHERE mastered=false | 每日复习查询 |
| `ix_wq_user_active_created` | wrong_questions | (user_id, is_active, created_at DESC) | 错题列表排序 |

## 后续建议

1. **Practice 推荐逐题子查询**：当前每道题执行一次 `question_knowledge_points` 子查询 (1173次循环)，建议改为 JOIN + 批量加载
2. **数据增长后监控**：questions > 10K, wrong_questions > 1K 时重新执行 EXPLAIN ANALYZE
3. **`review_schedules.mastered` 列**：考虑添加 `(user_id, mastered, next_review_at)` 复合索引替代当前部分索引
