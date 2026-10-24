/**
 * Pure helpers for formula list page, extracted from formulas/page.tsx.
 */

export interface FormulaListFilters {
  category_id?: string;
  status?: string;
  keyword?: string;
  card_type?: string;
  study_card_type?: string;
  exam_scope?: string;
}

/**
 * Parse a positive integer from a string, returning fallback if invalid.
 */
export function positiveInt(
  value: string | null,
  fallback: number | null = null,
): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

/**
 * Build the href for the formula list page with filters, page, and selected id.
 */
export function buildFormulaListHref(
  filters: FormulaListFilters,
  page: number,
  selectedId: number | null,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  if (page > 1) params.set("page", String(page));
  if (selectedId) params.set("selected_id", String(selectedId));
  const query = params.toString();
  return query ? `/formulas?${query}` : "/formulas";
}

/**
 * Recursively find a category node by id in a tree.
 */
export function findCategoryNode<T extends { id: number; children: T[] }>(
  nodes: T[],
  id: number | null,
): T | null {
  if (id === null) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findCategoryNode(node.children ?? [], id);
    if (found) return found;
  }
  return null;
}
