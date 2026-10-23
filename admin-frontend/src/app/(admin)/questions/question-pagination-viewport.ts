export const QUESTION_PAGINATION_WINDOW = 5;

export type QuestionPaginationViewportInput = {
  page: number;
  totalPages: number;
};

export function buildQuestionPaginationViewport({
  page,
  totalPages,
}: QuestionPaginationViewportInput): number[] {
  if (totalPages <= 0) return [];
  const startPage = Math.max(
    1,
    Math.min(page - 2, totalPages - (QUESTION_PAGINATION_WINDOW - 1)),
  );
  return Array.from(
    { length: Math.min(totalPages, QUESTION_PAGINATION_WINDOW) },
    (_, index) => startPage + index,
  ).filter((candidate) => candidate >= 1 && candidate <= totalPages);
}
