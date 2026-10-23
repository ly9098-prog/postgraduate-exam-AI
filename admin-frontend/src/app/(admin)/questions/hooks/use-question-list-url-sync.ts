"use client";

import { useEffect } from "react";
import type { QuestionListFilters } from "../question-list-state";
import { buildQuestionListHref } from "../question-list-state";

type UrlSyncCapabilities = {
  getLocation: () => { pathname: string; search: string };
  replaceState: (state: unknown, title: string, url: string) => void;
};

export function useQuestionListUrlSync(
  filters: QuestionListFilters,
  page: number,
  pageSize: number,
  selectedQuestionId: number | null,
  { getLocation, replaceState }: UrlSyncCapabilities,
) {
  useEffect(() => {
    const nextHref = buildQuestionListHref(filters, page, pageSize, selectedQuestionId);
    const location = getLocation();
    const currentHref = `${location.pathname}${location.search}`;
    if (currentHref !== nextHref) {
      replaceState(window.history.state, "", nextHref);
    }
  }, [filters, getLocation, page, pageSize, replaceState, selectedQuestionId]);
}
