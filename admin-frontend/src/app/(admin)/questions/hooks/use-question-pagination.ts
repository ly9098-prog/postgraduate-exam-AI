import { useEffect, useMemo, useState } from "react";
import {
  normalizeQuestionPageSize,
  positiveInt,
  readQuestionListFilters,
  type QuestionListFilters,
} from "../question-list-state";
import { buildQueryParams } from "../question-query-params";

export function useQuestionPagination(searchParams: URLSearchParams, totalPages?: number) {
  const [filters, setFilters] = useState<QuestionListFilters>(() =>
    readQuestionListFilters(searchParams),
  );
  const [page, setPage] = useState(() => positiveInt(searchParams.get("page"), 1) ?? 1);
  const [pageSize, setPageSize] = useState(() =>
    normalizeQuestionPageSize(searchParams.get("page_size")),
  );
  const queryParams = useMemo(
    () => buildQueryParams(filters, page, pageSize),
    [filters, page, pageSize],
  );

  useEffect(() => {
    if (typeof totalPages !== "number") return;
    const safeLastPage = Math.max(1, totalPages);
    if (page > safeLastPage) setPage(safeLastPage);
  }, [page, totalPages]);

  return {
    filters,
    page,
    pageSize,
    queryParams,
    setFilters,
    setPage,
    setPageSize,
  };
}
