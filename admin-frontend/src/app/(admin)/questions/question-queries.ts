import { queryOptions } from "@tanstack/react-query";
import {
  fetchQuestionDetail,
  fetchQuestions,
  fetchQuestionVersionDetail,
  fetchQuestionVersions,
  type QuestionQueryParams,
} from "./question-api";

export const questionKeys = {
  all: ["questions"] as const,
  scope: (id: number | null) => ["questions", id] as const,
  list: (params: QuestionQueryParams) => ["questions", params] as const,
  detail: (id: number | null) => ["questions", id, "detail"] as const,
  versions: (id: number | null) => ["questions", id, "versions"] as const,
  version: (id: number | null, version: number | "current" | null) =>
    ["questions", id, "versions", version] as const,
};

export function questionListOptions(params: QuestionQueryParams) {
  return queryOptions({
    queryKey: questionKeys.list(params),
    queryFn: () => fetchQuestions(params),
    placeholderData: (previousData) => previousData,
    retry: false,
  });
}

// Shared by the enabled detail observer and hover prefetch; each owns its policy.
export function questionDetailOptions(id: number | null) {
  return queryOptions({
    queryKey: questionKeys.detail(id),
    queryFn: () => fetchQuestionDetail(id!),
  });
}

export function questionVersionsOptions(id: number | null) {
  return queryOptions({
    queryKey: questionKeys.versions(id),
    queryFn: () => fetchQuestionVersions(id!),
    enabled: id !== null,
    retry: false,
  });
}

export function questionVersionOptions(id: number | null, version: number | "current" | null) {
  return queryOptions({
    queryKey: questionKeys.version(id, version),
    queryFn: () => fetchQuestionVersionDetail(id!, version as number),
    enabled: id !== null && typeof version === "number",
    placeholderData: (previousData) =>
      previousData?.question_id === id ? previousData : undefined,
    retry: false,
  });
}
