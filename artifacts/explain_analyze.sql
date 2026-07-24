-- 2240AI — 生产数据库 EXPLAIN ANALYZE 脚本
-- 执行方式：
--   docker exec -i deploy-postgres-1 psql -U pguser -d postgraduate < explain_analyze.sql
-- 或者：
--   PGPASSWORD=xxx psql -h localhost -U pguser -d postgraduate -f explain_analyze.sql

-- ============================================================
-- 1. 今日复习
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT wq.id, wq.question_id, wq.user_id, wq.next_review_at, wq.mastered,
       q.subject_id, q.question_type, q.difficulty
FROM wrong_questions wq
JOIN questions q ON q.id = wq.question_id
WHERE wq.user_id = (SELECT id FROM users LIMIT 1)
  AND wq.is_active = TRUE
  AND wq.next_review_at <= NOW()
ORDER BY wq.next_review_at ASC
LIMIT 20;

-- ============================================================
-- 2. 错题列表和统计
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT wq.id, wq.question_id, wq.created_at, wq.mastered,
       wq.consecutive_correct, wq.total_attempts,
       q.subject_id, q.question_type
FROM wrong_questions wq
JOIN questions q ON q.id = wq.question_id
WHERE wq.user_id = (SELECT id FROM users LIMIT 1)
  AND wq.is_active = TRUE
ORDER BY wq.created_at DESC
LIMIT 50;

-- 错题统计
EXPLAIN (ANALYZE, BUFFERS)
SELECT q.subject_id, COUNT(*) as cnt,
       COUNT(*) FILTER (WHERE wq.mastered = TRUE) as mastered_cnt
FROM wrong_questions wq
JOIN questions q ON q.id = wq.question_id
WHERE wq.user_id = (SELECT id FROM users LIMIT 1)
  AND wq.is_active = TRUE
GROUP BY q.subject_id;

-- ============================================================
-- 3. practice 推荐
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT q.id, q.subject_id, q.question_type, q.difficulty,
       COALESCE(ks.mastery_level, 0.0) as mastery
FROM questions q
LEFT JOIN knowledge_states ks ON ks.question_id = q.id
  AND ks.user_id = (SELECT id FROM users LIMIT 1)
WHERE q.is_active = TRUE
ORDER BY COALESCE(ks.mastery_level, 0.0) ASC, q.id ASC
LIMIT 10;

-- KP fallback (跨学科循环)
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*) FROM questions q
WHERE q.is_active = TRUE
  AND q.subject_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_states ks
    WHERE ks.question_id = q.id
      AND ks.user_id = (SELECT id FROM users LIMIT 1)
      AND ks.mastery_level >= 0.8
  );

-- ============================================================
-- 4. 知识状态
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT ks.knowledge_point_id, ks.mastery_level, ks.last_review_at,
       kp.name, kp.subject_id
FROM knowledge_states ks
JOIN knowledge_points kp ON kp.id = ks.knowledge_point_id
WHERE ks.user_id = (SELECT id FROM users LIMIT 1)
ORDER BY ks.mastery_level ASC
LIMIT 20;

-- ============================================================
-- 5. pipeline 状态
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT pipeline_id, status, source_type, source_file,
       total_pages, processed_pages, created_at, updated_at
FROM import_pipelines
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================
-- 6. audit log cleanup
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*) FROM audit_logs
WHERE created_at < NOW() - INTERVAL '180 days';

-- Cleanup query plan
EXPLAIN (ANALYZE, BUFFERS)
DELETE FROM audit_logs
WHERE id IN (
    SELECT id FROM audit_logs
    WHERE created_at < NOW() - INTERVAL '180 days'
    LIMIT 1000
);

-- ============================================================
-- 7. pomodoro 到期扫描
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, user_id, expected_end_time, status
FROM pomodoro_sessions
WHERE status = 'running'
  AND expected_end_time <= NOW()
LIMIT 100;

-- ============================================================
-- 8. task 管理查询（Redis 中的数据，此处查 staging）
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT object_id, original_name, size_bytes, created_at
FROM staging_objects
WHERE lease_expires_at < NOW()
  OR lease_expires_at IS NULL
LIMIT 100;

-- ============================================================
-- 9. question import review queue
-- ============================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT qi.id, qi.batch_id, qi.source_type, qi.status,
       qi.created_at, qi.parsed_content,
       ip.pipeline_id, ip.status as pipeline_status
FROM question_imports qi
LEFT JOIN import_pipelines ip ON ip.pipeline_id = qi.batch_id
WHERE qi.status IN ('pending_review', 'ai_reviewing')
ORDER BY qi.created_at DESC
LIMIT 50;

-- 按 review status 计数
EXPLAIN (ANALYZE, BUFFERS)
SELECT qi.status, COUNT(*) as cnt
FROM question_imports qi
GROUP BY qi.status;

-- ============================================================
-- 10. 关键索引检查
-- ============================================================
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename IN (
    'wrong_questions', 'questions', 'knowledge_states',
    'knowledge_points', 'question_imports', 'import_pipelines',
    'audit_logs', 'pomodoro_sessions', 'practice_records',
    'review_schedules'
)
ORDER BY tablename, indexname;
