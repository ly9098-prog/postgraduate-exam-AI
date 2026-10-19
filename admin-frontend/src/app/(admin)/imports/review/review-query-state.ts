export type ReviewFilters = {
  batch_id: string;
  status: string;
  subject_id: string;
  source_type: string;
  risk_level: string;
  answer_status: string;
};

export function buildReviewQueueParams(
  filters: ReviewFilters,
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
