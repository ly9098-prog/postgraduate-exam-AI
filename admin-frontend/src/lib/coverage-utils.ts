/**
 * Pure helpers for coverage page, extracted from coverage/page.tsx.
 * Covers status counting, item filtering, and issue aggregation.
 */

import type { CoverageStatus } from "@/lib/api/types";

export type CoverageItemLike = {
  status: CoverageStatus;
  subject_name: string;
  subject_code: string;
  name: string;
};

export type CoverageSummaryLike = {
  unversioned_questions: number;
  syllabus_snapshot_missing_questions: number;
  missing_analysis_questions: number;
  image_reference_anomaly_questions: number;
  duplicate_suspect_questions: number;
  empty_knowledge_points: number;
  insufficient_knowledge_points: number;
  imbalanced_knowledge_points: number;
};

export type CoverageQualityLike = {
  unmapped_question_ids: unknown[];
  missing_analysis_question_ids: unknown[];
  image_reference_anomaly_question_ids: unknown[];
  unversioned_question_ids: unknown[];
  syllabus_snapshot_missing_question_ids: unknown[];
  duplicate_groups: unknown[];
};

export type GraphQualityLike = {
  warnings?: unknown[];
  summary?: { isolated_count?: number; cycle_count?: number };
};

/**
 * Count items by coverage status.
 */
export function computeStatusCounts<T extends CoverageItemLike>(items: T[]): Record<CoverageStatus, number> {
  const counts: Record<CoverageStatus, number> = { empty: 0, insufficient: 0, imbalanced: 0, healthy: 0 };
  for (const item of items) counts[item.status] += 1;
  return counts;
}

/**
 * Filter coverage items by keyword and status.
 */
export function filterCoverageItems<T extends CoverageItemLike>(
  items: T[],
  keyword: string,
  status: string,
): T[] {
  const normalized = keyword.trim().toLowerCase();
  return items.filter((item) => {
    if (status && item.status !== status) return false;
    if (!normalized) return true;
    return `${item.subject_name} ${item.subject_code} ${item.name}`.toLowerCase().includes(normalized);
  });
}

/**
 * Sum the data-integrity issue counts from the summary and graph quality.
 */
export function computeIntegrityIssueCount(
  summary: CoverageSummaryLike | null | undefined,
  graph: GraphQualityLike | null | undefined,
): number {
  if (!summary) return 0;
  return (
    summary.unversioned_questions +
    summary.syllabus_snapshot_missing_questions +
    Number(graph?.summary?.isolated_count ?? 0) +
    Number(graph?.summary?.cycle_count ?? 0)
  );
}

/**
 * Sum the quality-sample issue counts.
 */
export function computeQualitySampleCount(quality: CoverageQualityLike | null | undefined): number {
  if (!quality) return 0;
  return (
    quality.unmapped_question_ids.length +
    quality.missing_analysis_question_ids.length +
    quality.image_reference_anomaly_question_ids.length +
    quality.unversioned_question_ids.length +
    quality.syllabus_snapshot_missing_question_ids.length +
    quality.duplicate_groups.length
  );
}

/**
 * True when the knowledge graph has warnings, isolated nodes, or cycles.
 */
export function hasGraphIssues(graph: GraphQualityLike | null | undefined): boolean {
  return Boolean(
    (graph?.warnings?.length ?? 0) ||
      Number(graph?.summary?.isolated_count ?? 0) ||
      Number(graph?.summary?.cycle_count ?? 0),
  );
}
