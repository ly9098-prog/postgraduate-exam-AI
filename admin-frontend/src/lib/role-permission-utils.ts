/**
 * Pure helpers for roles page, extracted from roles/page.tsx.
 * Covers permission-change diff computation and category-entry sorting.
 */

export type PermissionChanges = { added: number; removed: number };

/**
 * Compute the diff between original and active permission sets.
 * Returns counts of added and removed permissions.
 */
export function computePermissionChanges(
  originalIds: Set<number>,
  activeIds: Set<number>,
): PermissionChanges {
  let added = 0;
  let removed = 0;
  activeIds.forEach((id) => {
    if (!originalIds.has(id)) added += 1;
  });
  originalIds.forEach((id) => {
    if (!activeIds.has(id)) removed += 1;
  });
  return { added, removed };
}

/**
 * Sort category entries by a predefined order, falling back to locale compare.
 * Categories not in the order list are placed after known ones, sorted alphabetically.
 * Generic over the item type so callers get typed arrays back.
 */
export function sortCategoryEntries<T>(
  entries: Array<[string, T[]]>,
  categoryOrder: string[],
): Array<[string, T[]]> {
  return entries.sort(([left], [right]) => {
    const leftIndex = categoryOrder.indexOf(left);
    const rightIndex = categoryOrder.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
}

/**
 * Total permission count across all category entries.
 */
export function computeTotalPermissionCount<T>(
  entries: Array<[string, T[]]>,
): number {
  return entries.reduce((total, [, items]) => total + items.length, 0);
}
