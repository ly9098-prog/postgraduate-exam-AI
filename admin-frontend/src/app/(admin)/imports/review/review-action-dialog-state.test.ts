import { describe, expect, it } from "vitest";
import {
  createReviewActionDialogState,
  reduceReviewActionDialogState,
  type ReviewActionDialogState,
} from "./review-action-dialog-state";

describe("review action dialog state", () => {
  it("opens and cancels without clearing selection or rejection reason", () => {
    const initial = {
      ...createReviewActionDialogState(),
      selectedIds: new Set([3, 6]),
      rejectReason: "existing reason",
      message: "existing message",
    };
    const opened = reduceReviewActionDialogState(initial, {
      type: "open",
      action: { action: "batch-reject" },
    });
    expect(opened).toEqual({
      ...initial,
      confirmState: { action: "batch-reject" },
    });
    expect(reduceReviewActionDialogState(opened, { type: "cancel" })).toEqual({
      ...initial,
      confirmState: null,
    });
  });

  it("updates the rejection reason and message independently", () => {
    const initial = createReviewActionDialogState();
    expect(reduceReviewActionDialogState(initial, {
      type: "reject-reason",
      reason: "wrong stem",
    })).toEqual({ ...initial, rejectReason: "wrong stem" });
    expect(reduceReviewActionDialogState(initial, {
      type: "message",
      message: "saved",
    })).toEqual({ ...initial, message: "saved" });
  });

  it("replaces the entire selection set without mutating the previous set", () => {
    const state = {
      ...createReviewActionDialogState(),
      selectedIds: new Set([1, 2]),
    };
    const replacement = new Set([4, 5]);
    expect(reduceReviewActionDialogState(state, {
      type: "selected-ids",
      selectedIds: replacement,
    }).selectedIds).toBe(replacement);
    expect(state.selectedIds).toEqual(new Set([1, 2]));
  });

  it("applies consecutive functional selection updates against reducer state", () => {
    const initial = {
      ...createReviewActionDialogState(),
      selectedIds: new Set([1, 2]),
    };
    const toggle = (id: number) => (current: Set<number>) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    };
    const once = reduceReviewActionDialogState(initial, {
      type: "update-selected-ids",
      update: toggle(1),
    });
    const twice = reduceReviewActionDialogState(once, {
      type: "update-selected-ids",
      update: toggle(3),
    });
    expect(once.selectedIds).toEqual(new Set([2]));
    expect(twice.selectedIds).toEqual(new Set([2, 3]));
    expect(initial.selectedIds).toEqual(new Set([1, 2]));
  });

  it("resets selection, confirmation and rejection reason while preserving message", () => {
    const state: ReviewActionDialogState = {
      selectedIds: new Set([1, 2]),
      confirmState: { action: "reject", id: 2 },
      rejectReason: "reason",
      message: "kept",
    };
    expect(reduceReviewActionDialogState(state, { type: "reset" })).toEqual({
      selectedIds: new Set(),
      confirmState: null,
      rejectReason: "",
      message: "kept",
    });
    expect(state.selectedIds).toEqual(new Set([1, 2]));
  });
});
