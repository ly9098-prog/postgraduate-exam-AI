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
