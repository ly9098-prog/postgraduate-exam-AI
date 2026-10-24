import type { ReviewFilters } from "./review-query-state";

export type ReviewFilterKey = Exclude<keyof ReviewFilters, "keyword">;

export function reduceReviewFilters(
  current: ReviewFilters,
  key: ReviewFilterKey,
  value: string,
): ReviewFilters {
  return { ...current, [key]: value };
}

export function isReviewFacetFilter(key: ReviewFilterKey) {
  return key !== "source_type";
}
