/**
 * Pure helpers for exam detail page, extracted from exams/[id]/page.tsx.
 * Covers draft-item grouping, candidate filtering, and score/status aggregation.
 */

export const SUBJECT_ORDER = [
  "data_structure",
  "computer_organization",
  "operating_system",
  "computer_network",
];

export type DraftItemLike = {
  question_id: number;
  subject_code: string;
  subject_name: string;
  score: number | string | null | undefined;
  version_is_current?: boolean;
};

export type CandidateLike = {
  id: number;
};

export type QuestionGroup = {
  subject_code: string;
  subject_name: string;
  entries: Array<{ index: number; item: DraftItemLike }>;
};

/**
 * Group draft items by subject_code, preserving insertion order, then sort
 * groups by SUBJECT_ORDER with locale fallback for unknown subjects.
 */
export function groupDraftItemsBySubject<T extends DraftItemLike>(
  items: T[],
): Array<QuestionGroup & { entries: Array<{ index: number; item: T }> }> {
  const grouped = new Map<string, { subject_code: string; subject_name: string; entries: Array<{ index: number; item: T }> }>();
  items.forEach((item, index) => {
    const key = item.subject_code || item.subject_name || "unknown";
    const existing = grouped.get(key);
    if (existing) {
      existing.entries.push({ index, item });
    } else {
      grouped.set(key, {
        subject_code: item.subject_code || "unknown",
        subject_name: item.subject_name || "未归类",
        entries: [{ index, item }],
      });
    }
  });
  return Array.from(grouped.values()).sort((left, right) => {
    const leftOrder = SUBJECT_ORDER.indexOf(left.subject_code);
    const rightOrder = SUBJECT_ORDER.indexOf(right.subject_code);
    const leftRank = leftOrder === -1 ? Number.MAX_SAFE_INTEGER : leftOrder;
    const rightRank = rightOrder === -1 ? Number.MAX_SAFE_INTEGER : rightOrder;
    return leftRank - rightRank || left.subject_name.localeCompare(right.subject_name, "zh-CN");
  });
}

/**
 * Filter candidate questions not already in the exam.
 */
export function filterCandidates<T extends CandidateLike>(
  candidates: T[],
  selectedIds: Set<number>,
): T[] {
  return candidates.filter((question) => !selectedIds.has(question.id));
}

/**
 * Count candidates that are already in the exam.
 */
export function countMatchedSelected<T extends CandidateLike>(
  candidates: T[],
  selectedIds: Set<number>,
): number {
  return candidates.filter((question) => selectedIds.has(question.id)).length;
}

/**
 * Sum the draft scores of all items, treating invalid values as 0.
 */
export function computeDraftScore<T extends DraftItemLike>(items: T[]): number {
  return items.reduce((total, item) => total + (Number(item.score) || 0), 0);
}

/**
 * True when any item has a stale version (version_is_current === false).
 */
export function hasStaleVersion<T extends DraftItemLike>(items: T[]): boolean {
  return items.some((item) => item.version_is_current === false);
}

/**
 * Build the search summary string for the candidate search panel.
 */
export function buildCandidateSearchSummary(
  candidateTotal: number,
  matchedSelectedCount: number,
  candidatesLength: number,
  keyword: string,
): string {
  return keyword
    ? `匹配 ${candidateTotal} 道 · 已在卷中 ${matchedSelectedCount} 道 · 可添加 ${candidatesLength} 道`
    : `当前可添加 ${candidatesLength} 道`;
}
