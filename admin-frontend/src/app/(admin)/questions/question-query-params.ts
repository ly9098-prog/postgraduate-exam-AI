import type { QuestionQueryParams } from "./question-api";
import type { QuestionListFilters } from "./question-list-state";

export function buildQueryParams(
  filters: QuestionListFilters,
  page: number,
  pageSize: number,
): QuestionQueryParams {
  return {
    page,
    page_size: pageSize,
    subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
    is_active: filters.is_active,
    question_type: filters.question_type,
    keyword: filters.keyword,
    year: filters.year,
    difficulty: filters.difficulty ? Number(filters.difficulty) : undefined,
    import_batch_id: filters.import_batch_id || undefined,
    knowledge_point_id: filters.knowledge_point_id ? Number(filters.knowledge_point_id) : undefined,
  };
}
