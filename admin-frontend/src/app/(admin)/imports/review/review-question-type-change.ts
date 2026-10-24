/** Pure decision logic for question-type change in the import review page. */
import { isMultiBlankChoice } from "./review-edit-state";

export type MultiBlankState = {
  groups: never[];
  answerMap: Record<string, never>;
  usesSharedOptions: boolean;
  sharedOptions: never[];
};

export type QuestionTypeChangeResult =
  | { action: "noop" }
  | { action: "clear_multi_blank"; nextState: { question_type: string; multiBlank: undefined; options: never[] } }
  | { action: "update_type"; nextState: { question_type: string } }
  | { action: "init_multi_blank"; nextState: { question_type: string; multiBlank: MultiBlankState } };

export type BuildQuestionTypeChangeOptions = {
  currentType: string;
  newCode: string;
  hasMultiBlankGroups: boolean;
  confirmed: boolean;
};

export function buildQuestionTypeChange(
  options: BuildQuestionTypeChangeOptions,
): QuestionTypeChangeResult {
  const { currentType, newCode, hasMultiBlankGroups, confirmed } = options;
  if (currentType === newCode) return { action: "noop" };

  const wasMultiBlank = isMultiBlankChoice(currentType);
  const isMultiBlankTarget = isMultiBlankChoice(newCode);

  if (wasMultiBlank && !isMultiBlankTarget && hasMultiBlankGroups) {
    if (!confirmed) return { action: "noop" };
    return {
      action: "clear_multi_blank",
      nextState: { question_type: newCode, multiBlank: undefined, options: [] },
    };
  }

  if (wasMultiBlank && isMultiBlankTarget) {
    return { action: "update_type", nextState: { question_type: newCode } };
  }

  if (isMultiBlankTarget) {
    return {
      action: "init_multi_blank",
      nextState: {
        question_type: newCode,
        multiBlank: {
          groups: [],
          answerMap: {},
          usesSharedOptions: false,
          sharedOptions: [],
        },
      },
    };
  }

  return { action: "update_type", nextState: { question_type: newCode } };
}

