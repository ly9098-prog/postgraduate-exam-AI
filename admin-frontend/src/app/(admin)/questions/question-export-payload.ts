import type { QuestionExportPayload } from "./question-api";
import type { QuestionListFilters } from "./question-list-state";

export function buildExportPayload(
  format: "csv" | "docx",
  filters: QuestionListFilters,
  selectedIds: Set<number>,
): QuestionExportPayload {
  return {
    format,
    ids: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
    subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
    is_active:
      filters.is_active === "" ? undefined : filters.is_active === "true",
    question_type: filters.question_type || undefined,
    keyword: filters.keyword || undefined,
    year: filters.year ? Number(filters.year) : undefined,
    difficulty: filters.difficulty ? Number(filters.difficulty) : undefined,
    import_batch_id: filters.import_batch_id || undefined,
    knowledge_point_id: filters.knowledge_point_id
      ? Number(filters.knowledge_point_id)
      : undefined,
  };
}
