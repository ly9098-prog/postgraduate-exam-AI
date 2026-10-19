"use client";

import { useQuery } from "@tanstack/react-query";
import type { QuestionQueryParams } from "../question-api";
import {
  questionDetailOptions,
  questionListOptions,
  questionVersionOptions,
  questionVersionsOptions,
} from "../question-queries";

export function useQuestionList(params: QuestionQueryParams) {
  return useQuery(questionListOptions(params));
}

export function useQuestionDetail(id: number | null) {
  return useQuery({
    ...questionDetailOptions(id),
    enabled: id !== null,
    retry: false,
  });
}

export function useQuestionVersions(id: number | null) {
  return useQuery(questionVersionsOptions(id));
}

export function useQuestionVersion(id: number | null, version: number | "current" | null) {
  return useQuery(questionVersionOptions(id, version));
}
