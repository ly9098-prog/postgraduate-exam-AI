"use client";

import { useMemo } from "react";
import type { QuestionListFilters } from "../question-list-state";

export function useQuestionToolbarState(filters: QuestionListFilters) {
  const hasActiveFilters = useMemo(
    () => Boolean(
      filters.subject_id ||
        filters.question_type ||
        filters.year ||
        filters.is_active !== "true" ||
        filters.keyword ||
        filters.difficulty ||
        filters.import_batch_id ||
        filters.knowledge_point_id,
    ),
    [filters],
  );

  return { hasActiveFilters };
}
