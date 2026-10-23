"use client";

import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ImportQuestionItem } from "@/lib/api/types";
import {
  beginReviewDetailSession,
  createReviewDetailSession,
  endReviewDetailSession,
  isReviewDetailReady,
  settleReviewDetailSession,
} from "../review-detail-session";

export type ReviewQuestionDetailApiRequest = <T>(
  path: string,
  options?: RequestInit,
) => Promise<T>;

function loadReviewQuestionDetail(
  request: ReviewQuestionDetailApiRequest,
  id: number,
): Promise<ImportQuestionItem> {
  return request<ImportQuestionItem>(`/imports/questions/${id}`);
}

export function useReviewQuestionDetail(
  previewId: number | null,
  request: ReviewQuestionDetailApiRequest,
) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState(createReviewDetailSession);
  const sessionRef = useRef(session);
  const updateSession = useCallback((next: ReturnType<typeof createReviewDetailSession>) => {
    sessionRef.current = next;
    setSession(next);
  }, []);

  const detail = useQuery({
    queryKey: ["import-question-detail", previewId],
    queryFn: () => loadReviewQuestionDetail(request, previewId as number),
    enabled: previewId !== null,
    retry: false,
  });

  const beginSession = useCallback((id: number) => {
    const next = beginReviewDetailSession(sessionRef.current, id);
    updateSession(next);
    void queryClient.fetchQuery({
      queryKey: ["import-question-detail", id],
      queryFn: () => loadReviewQuestionDetail(request, id),
      staleTime: 0,
    }).then(() => {
      updateSession(settleReviewDetailSession(sessionRef.current, next.token));
    }).catch(() => {
      // The regular detail query exposes the error; edit remains disabled.
    });
  }, [queryClient, request, updateSession]);

  const endSession = useCallback(() => {
    updateSession(endReviewDetailSession(sessionRef.current));
  }, [updateSession]);

  return {
    detail,
    detailReady: isReviewDetailReady(session, previewId, detail.data?.id),
    beginSession,
    endSession,
  };
}
