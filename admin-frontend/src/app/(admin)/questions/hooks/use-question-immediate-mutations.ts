"use client";

import {
  useCallback, useEffect, useRef,
  type Dispatch, type MutableRefObject, type SetStateAction,
} from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { AdminQuestion, AdminQuestionDetail, QuestionEditRequest } from "@/lib/api/types";
import { updateQuestion } from "../question-api";
import { contentRecord } from "../question-content-editing";
import { savedQuestionEditDraft } from "../question-edit-draft";
import { buildQuestionEditPatch } from "../question-edit-patch";
import {
  QUESTION_MUTATION_LOST_MESSAGE,
  canApplyQuestionImmediateResponse,
  isCurrentQuestionImmediateOwner,
  syncQuestionImmediateOwner,
  type QuestionImmediateMutationOwner,
  type QuestionImmediateOwnerState,
} from "../question-immediate-owner";
import { questionKeys } from "../question-queries";

export type { QuestionImmediateMutationOwner } from "../question-immediate-owner";

type ImmediateInput = {
  questionId: number | null;
  question: AdminQuestion | null | undefined;
  dirty: boolean;
  form: QuestionEditRequest;
  stemText: string;
  unresolvedTableCount: number;
  emptyCodeCount: number;
};
type DraftFeedback = {
  setForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  setStemText: (value: string) => void;
  setMessage: (value: string) => void;
};

type CurrentOwnerRef = MutableRefObject<QuestionImmediateOwnerState>;
type SelectedQuestionIdRef = MutableRefObject<number | null>;
type OwnerRuntime = {
  cache: QueryClient;
  pending: MutableRefObject<Map<number, Promise<boolean>>>;
  currentOwner: CurrentOwnerRef;
  selectedQuestionId: SelectedQuestionIdRef;
  feedback: DraftFeedback;
  sequence: MutableRefObject<number>;
};
function invalidateDetail(cache: QueryClient, question: AdminQuestion) {
  mergeDetail(cache, question.id, question);
  cache.invalidateQueries({ queryKey: questionKeys.scope(question.id) });
  cache.invalidateQueries({ queryKey: questionKeys.all });
}

function invalidateQuestionMutation(
  question: AdminQuestion,
  targetId: number | null,
  cache: QueryClient,
) {
  if (targetId !== question.id) return;
  invalidateDetail(cache, question);
}

function mergeDetail(cache: QueryClient, id: number | null, question: AdminQuestion) {
  if (id === null) return;
  cache.setQueryData<AdminQuestionDetail>(questionKeys.detail(id), (current) =>
    current
      ? { ...current, ...question, import_record: current.import_record ?? null }
      : (question as AdminQuestionDetail),
  );
}

async function finishOwnedDraftSave(
  owner: QuestionImmediateMutationOwner | null,
  currentOwner: CurrentOwnerRef,
  selectedQuestionId: SelectedQuestionIdRef,
  apply: () => void,
): Promise<QuestionImmediateMutationOwner | null> {
  if (
    !owner ||
    selectedQuestionId.current !== owner.questionId ||
    !isCurrentQuestionImmediateOwner(owner, currentOwner.current)
  ) {
    return null;
  }
  apply();
  return owner;
}

function preparationError(input: ImmediateInput): string | null {
  if (input.questionId === null) return "未选中题目，无法保存当前修改。";
  if (input.unresolvedTableCount > 0) return "请先完成结构化表格核验，再继续图片或选项操作。";
  if (input.emptyCodeCount > 0) return "请先填写或删除空代码块，再继续图片或选项操作。";
  return null;
}

function releaseOwnedDraftResponse(
  owner: QuestionImmediateMutationOwner | null,
  currentOwner: CurrentOwnerRef,
  selectedQuestionId: SelectedQuestionIdRef,
): boolean {
  return Boolean(
    owner &&
    selectedQuestionId.current === owner.questionId &&
    isCurrentQuestionImmediateOwner(owner, currentOwner.current),
  );
}

async function saveDraft(
  input: ImmediateInput,
  cache: QueryClient,
  feedback: DraftFeedback,
  currentOwner: CurrentOwnerRef,
  selectedQuestionId: SelectedQuestionIdRef,
  owner: QuestionImmediateMutationOwner | null,
) {
  const stillCurrent = () => (
    releaseOwnedDraftResponse(owner, currentOwner, selectedQuestionId)
  );
  try {
    if (!input.question) {
      if (stillCurrent()) {
        feedback.setMessage("题目详情尚未加载完成，无法保存当前修改。");
      }
      return false;
    }
    const patch = buildQuestionEditPatch(input.form, input.question, input.stemText);
    if (Object.keys(patch).length === 0) return true;
    const question = await updateQuestion(input.questionId!, patch);
    mergeDetail(cache, input.questionId, question);
    const savedOwner = await finishOwnedDraftSave(
      owner,
      currentOwner,
      selectedQuestionId,
      () => {
        const draft = savedQuestionEditDraft(question);
        feedback.setForm(draft.form);
        feedback.setStemText(draft.stemText);
        cache.invalidateQueries({ queryKey: questionKeys.all });
        cache.invalidateQueries({ queryKey: questionKeys.scope(input.questionId) });
        feedback.setMessage("已先保存当前修改，将继续执行该操作。");
      },
    );
    if (!savedOwner) {
      invalidateDetail(cache, question);
      feedback.setMessage(QUESTION_MUTATION_LOST_MESSAGE);
      return false;
    }
    return true;
  } catch (error) {
    if (stillCurrent()) {
      feedback.setMessage(error instanceof Error
        ? `当前修改保存失败：${error.message}`
        : "当前修改保存失败，请稍后重试。");
    }
    return false;
  }
}

function handleQuestionMutationResponse(
  question: AdminQuestion,
  owner: QuestionImmediateMutationOwner | undefined,
  runtime: OwnerRuntime,
) {
  syncQuestionImmediateOwner(
    runtime.currentOwner.current,
    runtime.sequence,
    runtime.selectedQuestionId.current,
  );
  if (runtime.currentOwner.current.questionId === null) {
    invalidateDetail(runtime.cache, question);
    return;
  }
  if (!canApplyQuestionImmediateResponse(
    question.id, owner, runtime.currentOwner.current,
  )) {
    invalidateDetail(runtime.cache, question);
    runtime.feedback.setMessage(QUESTION_MUTATION_LOST_MESSAGE);
    return;
  }
  runtime.feedback.setForm((current) => ({
    ...current,
    content: contentRecord(question.content),
    options: question.options ?? undefined,
  }));
  invalidateQuestionMutation(question, question.id, runtime.cache);
}

function prepareOwnedQuestionMutation(
  input: ImmediateInput,
  runtime: OwnerRuntime,
): Promise<QuestionImmediateMutationOwner | null> {
  const selectedQuestionId = syncQuestionImmediateOwner(
    runtime.currentOwner.current,
    runtime.sequence,
    runtime.selectedQuestionId.current,
  )?.questionId ?? null;
  if (input.questionId === null || selectedQuestionId !== input.questionId) {
    if (input.dirty) runtime.feedback.setMessage("未选中题目，无法保存当前修改。");
    return Promise.resolve(null);
  }
  const existing = runtime.currentOwner.current;
  const owner = runtime.pending.current.has(input.questionId)
    ? existing.mutationOwner
    : {
        questionId: input.questionId,
        generation: runtime.sequence.current + 1,
      };
  if (!owner) return Promise.resolve(null);
  runtime.sequence.current = owner.generation;
  runtime.currentOwner.current = { questionId: owner.questionId, mutationOwner: owner };
  const requestKey = input.questionId;
  if (!input.dirty) return Promise.resolve(owner);
  const patch = input.question
    ? buildQuestionEditPatch(input.form, input.question, input.stemText)
    : null;
  if (patch && Object.keys(patch).length === 0) return Promise.resolve(owner);
  return saveOwnedQuestionDraft({ input, owner, requestKey, ...runtime });
}

function useLatest<T>(value: T) {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref;
}

export function useQuestionImmediateMutations(
  input: ImmediateInput,
  feedback: DraftFeedback,
  selectedQuestionId: SelectedQuestionIdRef,
) {
  const cache = useQueryClient();
  const pending = useRef(new Map<number, Promise<boolean>>());
  const ownerSequence = useRef(0);
  const currentOwner = useRef<QuestionImmediateOwnerState>({
    questionId: input.questionId,
    mutationOwner: input.questionId === null
      ? null
      : { questionId: input.questionId, generation: 0 },
  });
  const latestInput = useLatest(input);
  const runtime = {
    cache, pending, currentOwner, selectedQuestionId,
    feedback,
    sequence: ownerSequence,
  } satisfies OwnerRuntime;
  const prepareImmediateQuestionMutation = useCallback(
    () => prepareOwnedQuestionMutation(latestInput.current, runtime),
    [latestInput, runtime],
  );
  return {
    handleQuestionMutated: (question: AdminQuestion, owner?: QuestionImmediateMutationOwner) => (
      handleQuestionMutationResponse(question, owner, runtime)
    ),
    prepareImmediateQuestionMutation,
  };
}

async function saveOwnedQuestionDraft({
  input, owner, requestKey, cache, pending, currentOwner, selectedQuestionId, feedback,
}: {
  input: ImmediateInput;
  owner: QuestionImmediateMutationOwner | null;
  requestKey: number;
  cache: QueryClient;
  pending: MutableRefObject<Map<number, Promise<boolean>>>;
  currentOwner: CurrentOwnerRef;
  selectedQuestionId: SelectedQuestionIdRef;
  feedback: DraftFeedback;
}): Promise<QuestionImmediateMutationOwner | null> {
  const error = preparationError(input);
  if (error) {
    feedback.setMessage(error);
    return null;
  }
  let task = pending.current.get(requestKey);
  if (!task) {
    task = saveDraft(
      input, cache, feedback, currentOwner, selectedQuestionId, owner,
    );
    pending.current.set(requestKey, task);
    void task.finally(() => {
      if (pending.current.get(requestKey) === task) pending.current.delete(requestKey);
    });
  }
  const saved = await task;
  if (!saved || owner === null) return null;
  return (
    selectedQuestionId.current === owner.questionId &&
    isCurrentQuestionImmediateOwner(owner, currentOwner.current)
  ) ? owner : null;
}
