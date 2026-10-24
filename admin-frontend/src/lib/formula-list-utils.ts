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

/**
 * Prune a category tree by a search query, keeping nodes that match or have
 * matching descendants. Matching is case-insensitive against name or code.
 * Children arrays of retained nodes are replaced (not mutated).
 */
export function pruneCategoryTree<
  T extends { name: string; code: string; children: T[] },
>(nodes: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return nodes;
  const prune = (list: T[]): T[] =>
    list.flatMap((node) => {
      const children = prune(node.children ?? []);
      const matches =
        node.name.toLowerCase().includes(q) || node.code.toLowerCase().includes(q);
      return matches || children.length ? [{ ...node, children }] : [];
    });
  return prune(nodes);
}

/**
 * Sum the formula counts across root category nodes, preferring the subtree
 * count when available. Used for the "all categories" badge.
 */
export function sumCategoryFormulaCount<
  T extends { subtree_formula_count?: number; formula_count?: number },
>(nodes: T[]): number {
  return nodes.reduce(
    (sum, node) => sum + (node.subtree_formula_count ?? node.formula_count ?? 0),
    0,
  );
}

/**
 * True when any filter field is non-empty. The q/keyword field is checked
 * via the raw filter value (the page keeps a separate search draft).
 */
export function hasActiveFormulaFilters<
  F extends Record<string, string | undefined>,
>(filters: F, ...extraKeys: Array<keyof F>): boolean {
  const keys: Array<keyof F> = [
    "status",
    "category_id",
    "q",
    "library_type",
    "study_card_type",
    "graph_status",
    ...extraKeys,
  ];
  return keys.some((key) => Boolean(filters[key as string]));
}

/**
 * Filter the selected-id set against the current page's items, returning only
 * ids that are still present. Used to avoid stale selection after refetch.
 */
export function computeSafeSelectedIds<
  T extends { id: number },
>(items: T[], selectedIds: Set<number>): Set<number> {
  if (!items.length) return selectedIds;
  const valid = new Set(items.map((c) => c.id));
  return new Set([...selectedIds].filter((id) => valid.has(id)));
}

export interface BatchSelectionState {
  allSelected: boolean;
  indeterminate: boolean;
  selectedCount: number;
}

/**
 * Compute batch-selection aggregate state from items and the selected-id set.
 * `allSelected` is true only when items exist and all are selected; the
 * indeterminate flag covers the partial case.
 */
export function computeBatchSelectionState<
  T extends { id: number },
>(items: T[], selectedIds: Set<number>): BatchSelectionState {
  const safe = computeSafeSelectedIds(items, selectedIds);
  const allSelected = items.length > 0 && safe.size === items.length;
  const indeterminate = safe.size > 0 && !allSelected;
  return { allSelected, indeterminate, selectedCount: safe.size };
}

/**
 * Statuses eligible for batch approve/reject/submit on the formula list.
 */
export function isBatchableStatus(status: string | undefined): boolean {
  return status === "pending_review" || status === "draft";
}
