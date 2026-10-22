export type ReviewFilterUpdateSource = "facet" | "keyword" | "reset";

export type ReviewFilterSelectionState<TFilters> = {
  filters: TFilters;
  selectedIds: Set<number>;
};

export function shouldClearReviewSelection(source: ReviewFilterUpdateSource) {
  return source === "facet";
}

export function reduceReviewFilterSelection<TFilters>(
  state: ReviewFilterSelectionState<TFilters>,
  source: ReviewFilterUpdateSource,
) {
  return shouldClearReviewSelection(source)
    ? { ...state, selectedIds: new Set<number>() }
    : state;
}

/** Toggle all item IDs: select all if not all checked, deselect all otherwise. */
export function toggleAllSelection(
  itemIds: number[],
  allChecked: boolean,
): Set<number> {
  return allChecked ? new Set() : new Set(itemIds);
}

/** Toggle a single ID in a selection set, returning a new set. */
export function toggleSingleSelection(
  selectedIds: Set<number>,
  id: number,
): Set<number> {
  const next = new Set(selectedIds);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
