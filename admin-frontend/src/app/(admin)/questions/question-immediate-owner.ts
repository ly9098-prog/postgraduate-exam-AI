export type QuestionImmediateMutationOwner = {
  questionId: number;
  generation: number;
};

export type QuestionImmediateOwnerState = {
  questionId: number | null;
  mutationOwner: QuestionImmediateMutationOwner | null;
};

export type QuestionImmediateOwnerResolution = {
  owner: QuestionImmediateMutationOwner | null;
  changedQuestion: boolean;
};

export const QUESTION_MUTATION_LOST_MESSAGE =
  "题目已切换，已保存原题修改；请重新执行图片或选项操作。";

export function newQuestionImmediateMutationOwner(
  questionId: number,
  generation: number,
): QuestionImmediateMutationOwner {
  return { questionId, generation: generation + 1 };
}

export function resolveQuestionImmediateOwner(
  resolution: QuestionImmediateOwnerResolution,
  questionId: number | null,
  generation: number,
): QuestionImmediateMutationOwner | null {
  if (questionId === null) {
    if (resolution.owner !== null) resolution.changedQuestion = true;
    resolution.owner = null;
    return null;
  }
  if (resolution.owner?.questionId === questionId) return resolution.owner;
  resolution.changedQuestion = true;
  resolution.owner = newQuestionImmediateMutationOwner(questionId, generation);
  return resolution.owner;
}

export function syncQuestionImmediateOwner(
  state: QuestionImmediateOwnerState,
  sequence: { current: number },
  questionId: number | null,
): QuestionImmediateMutationOwner | null {
  if (state.questionId === questionId) return state.mutationOwner;
  const resolution: QuestionImmediateOwnerResolution = {
    owner: state.mutationOwner,
    changedQuestion: false,
  };
  const owner = resolveQuestionImmediateOwner(
    resolution, questionId, sequence.current,
  );
  if (state.questionId !== questionId || resolution.changedQuestion) {
    sequence.current += 1;
    state.questionId = questionId;
    state.mutationOwner = owner;
  }
  return owner;
}

export function isCurrentQuestionImmediateOwner(
  expected: QuestionImmediateMutationOwner,
  current: QuestionImmediateOwnerState,
): boolean {
  return (
    current.mutationOwner?.questionId === expected.questionId &&
    current.mutationOwner.generation === expected.generation
  );
}

export function canApplyQuestionImmediateResponse(
  responseQuestionId: number,
  owner: QuestionImmediateMutationOwner | undefined,
  current: QuestionImmediateOwnerState,
): boolean {
  if (owner) {
    return (
      owner.questionId === responseQuestionId &&
      isCurrentQuestionImmediateOwner(owner, current)
    );
  }
  return current.questionId === responseQuestionId;
}
