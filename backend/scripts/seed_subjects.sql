-- 插入学科基础数据（生产 PostgreSQL 用）
-- 用法：docker compose exec -T postgres psql -U postgraduate -d postgraduate < scripts/seed_subjects.sql

INSERT INTO subjects (code, name, level, path, sort_order, is_active)
VALUES
    ('math', '高数',           1, 'math', 1, true),
    ('la',   '线性代数',       1, 'la',   2, true),
    ('ds',   '数据结构',       1, 'ds',   3, true),
    ('cn',   '计算机网络',     1, 'cn',   4, true),
    ('co',   '计算机组成原理', 1, 'co',   5, true),
    ('os',   '操作系统',       1, 'os',   6, true),
    ('pol',  '政治',           1, 'pol',  7, true),
    ('eng',  '英语',           1, 'eng',  8, true)
ON CONFLICT (code) DO NOTHING;
