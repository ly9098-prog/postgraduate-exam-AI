export type QuestionListFilters = {
  subject_id: string;
  is_active: string;
  question_type: string;
  keyword: string;
  year: string;
  difficulty: string;
  import_batch_id: string;
  knowledge_point_id: string;
};

export const DEFAULT_QUESTION_FILTERS: QuestionListFilters = {
  subject_id: "",
  is_active: "true",
  question_type: "",
  keyword: "",
  year: "",
  difficulty: "",
  import_batch_id: "",
  knowledge_point_id: "",
};

export function positiveInt(value: string | null, fallback: number | null = null): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function normalizeQuestionPageSize(value: string | null): number {
  const parsed = positiveInt(value, 20) ?? 20;
  return [20, 50, 100].includes(parsed) ? parsed : 20;
}

export function buildQuestionListHref(
  filters: QuestionListFilters,
  page: number,
  pageSize: number,
  selectedQuestionId: number | null,
): string {
  const params = new URLSearchParams();
  if (filters.subject_id) params.set("subject_id", filters.subject_id);
  if (filters.is_active !== DEFAULT_QUESTION_FILTERS.is_active) {
    params.set("is_active", filters.is_active);
  }
  if (filters.question_type) params.set("question_type", filters.question_type);
  if (filters.keyword) params.set("keyword", filters.keyword);
  if (filters.year) params.set("year", filters.year);
  if (filters.difficulty) params.set("difficulty", filters.difficulty);
  if (filters.import_batch_id) params.set("import_batch_id", filters.import_batch_id);
  if (filters.knowledge_point_id) params.set("knowledge_point_id", filters.knowledge_point_id);
  if (page > 1) params.set("page", String(page));
  if (pageSize !== 20) params.set("page_size", String(pageSize));
  if (selectedQuestionId) params.set("selected_id", String(selectedQuestionId));
  const query = params.toString();
  return query ? `/questions?${query}` : "/questions";
}

export function readQuestionListFilters(params: Pick<URLSearchParams, "get" | "has">): QuestionListFilters {
  return {
    subject_id: params.get("subject_id") ?? "",
    is_active: params.has("is_active")
      ? (params.get("is_active") ?? "")
      : DEFAULT_QUESTION_FILTERS.is_active,
    question_type: params.get("question_type") ?? "",
    keyword: params.get("keyword") ?? "",
    year: params.get("year") ?? "",
    difficulty: params.get("difficulty") ?? "",
    import_batch_id: params.get("import_batch_id") ?? "",
    knowledge_point_id: params.get("knowledge_point_id") ?? "",
  };
}
