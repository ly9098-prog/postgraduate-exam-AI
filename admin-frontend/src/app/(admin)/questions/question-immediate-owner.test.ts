import { describe, expect, it } from "vitest";
import {
  canApplyQuestionImmediateResponse,
  newQuestionImmediateMutationOwner,
  resolveQuestionImmediateOwner,
  syncQuestionImmediateOwner,
  type QuestionImmediateOwnerResolution,
} from "./question-immediate-owner";

describe("question immediate response ownership", () => {
  it("bumps generation only when the selected question changes", () => {
    const resolution: QuestionImmediateOwnerResolution = {
      owner: newQuestionImmediateMutationOwner(7, 0),
      changedQuestion: false,
    };
    const first = resolveQuestionImmediateOwner(resolution, 7, 1);
    const same = resolveQuestionImmediateOwner(resolution, 7, 1);
    const switched = resolveQuestionImmediateOwner(resolution, 8, 1);

    expect(first).toEqual({ questionId: 7, generation: 1 });
    expect(same).toBe(first);
    expect(switched).toEqual({ questionId: 8, generation: 2 });
    expect(resolution.owner).toEqual({ questionId: 8, generation: 2 });
  });

  it("drops a response from an older generation or a different question", () => {
    const current = {
      questionId: 8,
      mutationOwner: { questionId: 8, generation: 2 },
    };
    expect(canApplyQuestionImmediateResponse(
      7, { questionId: 7, generation: 1 }, current,
    )).toBe(false);
    expect(canApplyQuestionImmediateResponse(
      8, { questionId: 8, generation: 1 }, current,
    )).toBe(false);
    expect(canApplyQuestionImmediateResponse(
      8, { questionId: 8, generation: 2 }, current,
    )).toBe(true);
  });

  it("allows legacy unowned writes only when the response matches the selection", () => {
    const current = {
      questionId: 8,
      mutationOwner: { questionId: 8, generation: 2 },
    };
    expect(canApplyQuestionImmediateResponse(7, undefined, current)).toBe(false);
    expect(canApplyQuestionImmediateResponse(8, undefined, current)).toBe(true);
    expect(canApplyQuestionImmediateResponse(
      7, undefined, { questionId: null, mutationOwner: null },
    )).toBe(false);
  });

  it("keeps the selected owner stable when the same question is re-rendered", () => {
    const state = { questionId: 7, mutationOwner: { questionId: 7, generation: 1 } };
    const sequence = { current: 1 };
    expect(syncQuestionImmediateOwner(state, sequence, 7)).toBe(state.mutationOwner);
    expect(sequence.current).toBe(1);
    expect(syncQuestionImmediateOwner(state, sequence, 8)).toEqual({
      questionId: 8, generation: 2,
    });
    expect(sequence.current).toBe(2);
    expect(syncQuestionImmediateOwner(state, sequence, null)).toBeNull();
    expect(sequence.current).toBe(3);
  });
});
