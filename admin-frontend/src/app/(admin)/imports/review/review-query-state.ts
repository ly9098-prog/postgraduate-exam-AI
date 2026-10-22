export type ReviewFilters = {
  batch_id: string;
  status: string;
  subject_id: string;
  source_type: string;
  keyword: string;
  risk_level: string;
  answer_status: string;
};

export type ReviewFilterInputs = Omit<ReviewFilters, "keyword">;

export function createDefaultReviewFilters(): ReviewFilters {
  return {
    batch_id: "",
    status: "pending",
    subject_id: "",
    source_type: "",
    keyword: "",
    risk_level: "",
    answer_status: "",
  };
}

export function shouldShowReviewFilterReset(filters: ReviewFilters): boolean {
  return Boolean(
    filters.batch_id ||
    filters.subject_id ||
    filters.risk_level ||
    filters.answer_status ||
    filters.keyword,
  );
}

export function buildReviewQueueParams(
  filters: ReviewFilterInputs,
  page: number,
  batchIdParam: string,
  debouncedKeyword: string,
) {
  return {
    page,
    page_size: 50,
    batch_id: filters.batch_id || batchIdParam,
    status: filters.status,
    subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
    source_type: filters.source_type,
    keyword: debouncedKeyword,
    risk_level: filters.risk_level || undefined,
    answer_status: filters.answer_status || undefined,
  };
}
