\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

LOCK TABLE knowledge_edges, syllabus_knowledge_points IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE hierarchy_stage (
  subject_id integer,
  subject_code text,
  syllabus_version_id integer,
  knowledge_point_id integer,
  knowledge_point_name text,
  parent_knowledge_point_id integer,
  parent_name text,
  is_root integer,
  depth integer,
  tree_sort_order integer,
  path text,
  relation_type text,
  relation_source text,
  confidence double precision,
  weight double precision,
  existing_parent_knowledge_point_id integer,
  existing_parent_name text,
  parent_change text,
  canonical_knowledge_point_id integer,
  canonical_name text,
  merge_candidate_group text,
  data_quality_note text
);

COPY hierarchy_stage FROM '/tmp/data_structure_hierarchy_2026.csv'
  WITH (FORMAT csv, HEADER true, ENCODING 'UTF8', NULL '');

DO $$
BEGIN
  IF (SELECT count(*) FROM hierarchy_stage) <> 184
     OR (SELECT count(*) FROM hierarchy_stage WHERE parent_knowledge_point_id IS NOT NULL) <> 174
     OR (SELECT count(DISTINCT knowledge_point_id) FROM hierarchy_stage) <> 184
     OR EXISTS (SELECT 1 FROM hierarchy_stage WHERE subject_id <> 7 OR syllabus_version_id <> 1)
     OR EXISTS (SELECT 1 FROM hierarchy_stage WHERE parent_knowledge_point_id = knowledge_point_id)
     OR EXISTS (
       SELECT 1 FROM hierarchy_stage h
       LEFT JOIN knowledge_points k ON k.id = h.knowledge_point_id AND k.subject_id = 7
       WHERE k.id IS NULL
     )
     OR EXISTS (
       SELECT 1 FROM hierarchy_stage h
       LEFT JOIN knowledge_points k ON k.id = h.parent_knowledge_point_id AND k.subject_id = 7
       WHERE h.parent_knowledge_point_id IS NOT NULL AND k.id IS NULL
     )
  THEN
    RAISE EXCEPTION 'hierarchy CSV validation failed';
  END IF;
END $$;

SELECT 'before_parent_edges' AS metric, count(*)::text AS value
FROM knowledge_edges WHERE subject_id = 7 AND relation_type = 'parent'
UNION ALL SELECT 'before_other_edges', count(*)::text
FROM knowledge_edges WHERE subject_id = 7 AND relation_type <> 'parent'
UNION ALL SELECT 'csv_parent_rows', count(*)::text
FROM hierarchy_stage WHERE parent_knowledge_point_id IS NOT NULL;

CREATE TEMP TABLE hierarchy_before_counts AS
SELECT
  (SELECT count(*) FROM knowledge_edges WHERE subject_id = 7 AND relation_type = 'parent') AS parent_edges,
  (SELECT count(*) FROM knowledge_edges WHERE subject_id = 7 AND relation_type <> 'parent') AS other_edges;

DELETE FROM knowledge_edges
WHERE subject_id = 7 AND relation_type = 'parent';

INSERT INTO knowledge_edges (
  subject_id, source_knowledge_point_id, target_knowledge_point_id,
  relation_type, source, confidence, weight, is_active
)
SELECT 7, parent_knowledge_point_id, knowledge_point_id,
       'parent', 'manual', 1.0, 1.0, TRUE
FROM hierarchy_stage
WHERE parent_knowledge_point_id IS NOT NULL;

WITH changed AS (
  UPDATE syllabus_knowledge_points s
  SET sort_order = h.tree_sort_order
  FROM hierarchy_stage h
  WHERE s.syllabus_version_id = 1
    AND s.subject_id = 7
    AND s.knowledge_point_id = h.knowledge_point_id
    AND s.sort_order <> h.tree_sort_order
  RETURNING s.id
)
SELECT 'syllabus_sort_order_updated' AS metric, count(*)::text AS value FROM changed;

DO $$
BEGIN
  IF (SELECT count(*) FROM knowledge_edges WHERE subject_id = 7 AND relation_type = 'parent') <> 174
     OR (SELECT count(*) FROM knowledge_edges WHERE subject_id = 7 AND relation_type <> 'parent') <> (SELECT other_edges FROM hierarchy_before_counts)
  THEN
    RAISE EXCEPTION 'post-write edge count validation failed';
  END IF;
  IF EXISTS (
    SELECT 1 FROM knowledge_edges e
    WHERE e.subject_id = 7 AND e.relation_type = 'parent'
      AND (NOT EXISTS (SELECT 1 FROM hierarchy_stage h WHERE h.parent_knowledge_point_id = e.source_knowledge_point_id AND h.knowledge_point_id = e.target_knowledge_point_id AND h.parent_knowledge_point_id IS NOT NULL))
  ) THEN
    RAISE EXCEPTION 'post-write parent edge set validation failed';
  END IF;
END $$;

SELECT 'parent_edge_count' AS check_name,
       count(*)::text AS value
FROM knowledge_edges WHERE subject_id = 7 AND relation_type = 'parent'
UNION ALL
SELECT 'root_node_count', count(*)::text
FROM syllabus_knowledge_points s
WHERE s.subject_id = 7 AND s.syllabus_version_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_edges e
    WHERE e.subject_id = 7 AND e.relation_type = 'parent'
      AND e.target_knowledge_point_id = s.knowledge_point_id
  )
UNION ALL
SELECT 'multiple_parent_nodes', count(*)::text FROM (
  SELECT target_knowledge_point_id FROM knowledge_edges
  WHERE subject_id = 7 AND relation_type = 'parent'
  GROUP BY target_knowledge_point_id HAVING count(*) > 1
) x
UNION ALL
SELECT 'dangling_parent_edges', count(*)::text
FROM knowledge_edges e
LEFT JOIN knowledge_points sp ON sp.id = e.source_knowledge_point_id
LEFT JOIN knowledge_points tp ON tp.id = e.target_knowledge_point_id
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND (sp.id IS NULL OR tp.id IS NULL)
UNION ALL
SELECT 'lineartable_to_sequential', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 12 AND e.target_knowledge_point_id = 13
UNION ALL
SELECT 'lineartable_to_linkedlist', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 12 AND e.target_knowledge_point_id = 25
UNION ALL
SELECT 'linkedlist_to_singly', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 25 AND e.target_knowledge_point_id = 19
UNION ALL
SELECT 'linkedlist_to_doubly', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 25 AND e.target_knowledge_point_id = 128
UNION ALL
SELECT 'linkedlist_to_circular', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 25 AND e.target_knowledge_point_id = 17
UNION ALL
SELECT 'btree_to_bplus', count(*)::text FROM knowledge_edges e
WHERE e.subject_id = 7 AND e.relation_type = 'parent'
  AND e.source_knowledge_point_id = 195 AND e.target_knowledge_point_id = 250
UNION ALL
SELECT 'sort_order_mismatches', count(*)::text
FROM hierarchy_stage h
JOIN syllabus_knowledge_points s
  ON s.syllabus_version_id = 1 AND s.subject_id = 7
 AND s.knowledge_point_id = h.knowledge_point_id
WHERE s.sort_order <> h.tree_sort_order;

SELECT 'unmatched_syllabus_memberships' AS check_name,
       h.knowledge_point_id::text || ':' || h.knowledge_point_name AS value
FROM hierarchy_stage h
LEFT JOIN syllabus_knowledge_points s
  ON s.syllabus_version_id = 1 AND s.subject_id = 7
 AND s.knowledge_point_id = h.knowledge_point_id
WHERE s.id IS NULL
ORDER BY h.tree_sort_order;

COMMIT;
