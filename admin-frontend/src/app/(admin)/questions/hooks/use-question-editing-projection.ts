"use client";

import { useCallback, useMemo } from "react";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";
import { fallbackQuestionImageUrls } from "../question-display-helpers";
import { addQuestionCodeSegment, replaceQuestionSegments } from "../question-segment-editing";
import {
  codeSegmentText,
  comparableText,
  contentSegments,
  isCodeSegment,
} from "../question-content-editing";

type EditingProjectionActions = {
  setEditForm: React.Dispatch<React.SetStateAction<QuestionEditRequest>>;
};

export function useQuestionEditingProjection(
  editForm: QuestionEditRequest,
  question: AdminQuestion | undefined,
  { setEditForm }: EditingProjectionActions,
) {
  const editingSegments = useMemo(
    () => contentSegments(editForm.content),
    [editForm.content],
  );
  const editingFallbackStemImageUrls = useMemo(
    () => fallbackQuestionImageUrls(question?.content, question?.image_url),
    [question?.content, question?.image_url],
  );
  const unresolvedEditingTableCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      const table = normalizeStructuredTableSegment(segment);
      return count + (table?.requires_review ? 1 : 0);
    }, 0),
    [editingSegments],
  );
  const emptyEditingCodeCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      if (!isCodeSegment(segment)) return count;
      return count + (comparableText(codeSegmentText(segment)) ? 0 : 1);
    }, 0),
    [editingSegments],
  );

  const replaceEditingSegments = useCallback(
    (segments: Array<Record<string, unknown>>) => {
      setEditForm((current) => replaceQuestionSegments(current, segments));
    },
    [setEditForm],
  );

  const addEditingCodeSegment = useCallback(() => {
    setEditForm(addQuestionCodeSegment);
  }, [setEditForm]);

  return {
    editingSegments,
    editingFallbackStemImageUrls,
    unresolvedEditingTableCount,
    emptyEditingCodeCount,
    replaceEditingSegments,
    addEditingCodeSegment,
  };
}
