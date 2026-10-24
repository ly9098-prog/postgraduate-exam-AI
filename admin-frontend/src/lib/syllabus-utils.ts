/**
 * Pure helpers for syllabus page, extracted from syllabus/page.tsx.
 * Covers catalog filtering, grouping, membership dirty-checking, and
 * included-id extraction.
 */

import type { SyllabusCatalogItem } from "@/lib/api/types";

export const SUBJECT_PREFERRED_ORDER = [
  "data_structure",
  "computer_organization",
  "operating_system",
  "computer_network",
];

/**
 * Filter catalog items by a keyword (matches subject_name, name, knowledge_point_id).
 */
export function filterCatalogItems(
  items: SyllabusCatalogItem[],
  keyword: string,
): SyllabusCatalogItem[] {
  if (!keyword) return items;
  const normalized = keyword.toLowerCase();
  return items.filter((item) =>
    `${item.subject_name} ${item.name} ${item.knowledge_point_id}`.toLowerCase().includes(normalized),
  );
}


/**
 * Group catalog items by subject_code::subject_name, sorted by preferred order.
 * Returns entries as [key, items[]] tuples to match the page's destructuring pattern.
 */
export function groupCatalogBySubject(
  items: SyllabusCatalogItem[],
): Array<[string, SyllabusCatalogItem[]]> {
  const groups = new Map<string, SyllabusCatalogItem[]>();
  for (const item of items) {
    const key = `${item.subject_code}::${item.subject_name}`;
    const bucket = groups.get(key) ?? [];
    bucket.push(item);
    groups.set(key, bucket);
  }
  return [...groups.entries()].sort(([, leftItems], [, rightItems]) => {
    const leftCode = leftItems[0]?.subject_code ?? "";
    const rightCode = rightItems[0]?.subject_code ?? "";
    const leftIndex = SUBJECT_PREFERRED_ORDER.indexOf(leftCode);
    const rightIndex = SUBJECT_PREFERRED_ORDER.indexOf(rightCode);
    if (leftIndex >= 0 || rightIndex >= 0) {
      if (leftIndex < 0) return 1;
      if (rightIndex < 0) return -1;
      return leftIndex - rightIndex;
    }
    return (leftItems[0]?.subject_name ?? "").localeCompare(rightItems[0]?.subject_name ?? "", "zh-CN");
  }).map(([key, groupItems]) => [key, groupItems] as [string, SyllabusCatalogItem[]]);
}

/**
 * Extract the set of included knowledge_point_ids from catalog items.
 */
export function extractIncludedIds(items: SyllabusCatalogItem[]): Set<number> {
  return new Set(items.filter((item) => item.included).map((item) => item.knowledge_point_id));
}

/**
 * Check if the selected knowledge point set differs from the included set.
 */
export function isMembershipDirty(
  selectedIds: Set<number>,
  includedIds: Set<number>,
): boolean {
  if (selectedIds.size !== includedIds.size) return true;
  return [...selectedIds].some((id) => !includedIds.has(id));
}
