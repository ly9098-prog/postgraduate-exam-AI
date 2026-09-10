\set ON_ERROR_STOP on
CREATE TEMP TABLE hierarchy_stage (
  subject_id integer, subject_code text, syllabus_version_id integer, knowledge_point_id integer,
  knowledge_point_name text, parent_knowledge_point_id integer, parent_name text, is_root integer,
  depth integer, tree_sort_order integer, path text, relation_type text, relation_source text,
  confidence double precision, weight double precision, existing_parent_knowledge_point_id integer,
  existing_parent_name text, parent_change text, canonical_knowledge_point_id integer,
  canonical_name text, merge_candidate_group text, data_quality_note text
);
COPY hierarchy_stage FROM '/tmp/data_structure_hierarchy_2026.csv'
  WITH (FORMAT csv, HEADER true, ENCODING 'UTF8', NULL '');
SELECT 'csv_rows' AS metric, count(*)::text AS value FROM hierarchy_stage
UNION ALL SELECT 'csv_parent_rows', count(*)::text FROM hierarchy_stage WHERE parent_knowledge_point_id IS NOT NULL
UNION ALL SELECT 'current_parent_edges_subject7', count(*)::text FROM knowledge_edges WHERE subject_id=7 AND relation_type='parent'
UNION ALL SELECT 'current_other_edges_subject7', count(*)::text FROM knowledge_edges WHERE subject_id=7 AND relation_type<>'parent'
UNION ALL SELECT 'current_syllabus_memberships', count(*)::text FROM syllabus_knowledge_points WHERE syllabus_version_id=1 AND subject_id=7
UNION ALL SELECT 'missing_kp_ids', count(*)::text FROM hierarchy_stage h LEFT JOIN knowledge_points k ON k.id=h.knowledge_point_id AND k.subject_id=7 WHERE k.id IS NULL
UNION ALL SELECT 'missing_parent_kp_ids', count(*)::text FROM hierarchy_stage h LEFT JOIN knowledge_points k ON k.id=h.parent_knowledge_point_id AND k.subject_id=7 WHERE h.parent_knowledge_point_id IS NOT NULL AND k.id IS NULL
UNION ALL SELECT 'missing_syllabus_memberships', count(*)::text FROM hierarchy_stage h LEFT JOIN syllabus_knowledge_points s ON s.syllabus_version_id=1 AND s.subject_id=7 AND s.knowledge_point_id=h.knowledge_point_id WHERE s.id IS NULL
UNION ALL SELECT 'sort_order_mismatches', count(*)::text FROM hierarchy_stage h JOIN syllabus_knowledge_points s ON s.syllabus_version_id=1 AND s.subject_id=7 AND s.knowledge_point_id=h.knowledge_point_id WHERE s.sort_order<>h.tree_sort_order
UNION ALL SELECT 'desired_parent_edges_existing_exact', count(*)::text FROM hierarchy_stage h JOIN knowledge_edges e ON e.subject_id=7 AND e.relation_type='parent' AND e.source_knowledge_point_id=h.parent_knowledge_point_id AND e.target_knowledge_point_id=h.knowledge_point_id WHERE h.parent_knowledge_point_id IS NOT NULL
UNION ALL SELECT 'parent_edges_to_delete', count(*)::text FROM knowledge_edges WHERE subject_id=7 AND relation_type='parent';
