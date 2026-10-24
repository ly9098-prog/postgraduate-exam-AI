import { describe, expect, it, vi } from "vitest";
import type { EditState } from "./review-edit-state";
import {
  reviewDrawerDirty,
  shouldCancelReviewEditing,
  shouldKeepClosedReviewDrawer,
  shouldKeepCurrentReviewDrawer,
  startReviewEditingFlow,
} from "./review-drawer-flow";

const editState: EditState = {
  subject_id: null,
  question_type: "single_choice",
  stem: "stem",
  options: [{ key: "A", text: "option A", segments: undefined }],
  answer: "A",
  analysis: "",
};
const editSnapshot = JSON.stringify(editState);

describe("review drawer flow", () => {
  it("blocks switching while uploading or completing", () => {
    expect(shouldKeepCurrentReviewDrawer({
      previewId: null,
      segmentUploading: 0,
      completePending: false,
      hasUnsavedDraft: false,
      confirm: () => true,
    })).toBe(true);
    expect(shouldKeepCurrentReviewDrawer({
      previewId: 1,
      segmentUploading: -1,
      completePending: true,
      hasUnsavedDraft: false,
      confirm: () => true,
    })).toBe(true);
  });

  it("keeps the current drawer only when a dirty switch is not confirmed", () => {
    const confirm = vi.fn(() => false);
    expect(shouldKeepCurrentReviewDrawer({
      previewId: 1,
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: true,
      confirm,
    })).toBe(true);
    expect(confirm).toHaveBeenCalledWith("有未保存的修改，确定切换到其他题目吗？");

    expect(shouldKeepCurrentReviewDrawer({
      previewId: 1,
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: true,
      confirm: () => true,
    })).toBe(false);
    expect(shouldKeepCurrentReviewDrawer({
      previewId: null,
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: true,
      confirm: () => true,
    })).toBe(false);
  });

  it("keeps a dirty drawer closed only when close is not confirmed", () => {
    const confirm = vi.fn(() => false);
    expect(shouldKeepClosedReviewDrawer({
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: true,
      confirm,
    })).toBe(true);
    expect(confirm).toHaveBeenCalledWith("有未保存的修改，确定关闭吗？");

    expect(shouldKeepClosedReviewDrawer({
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: true,
      confirm: () => true,
    })).toBe(false);
    expect(shouldKeepClosedReviewDrawer({
      segmentUploading: -1,
      completePending: false,
      hasUnsavedDraft: false,
      confirm: () => true,
    })).toBe(false);
  });

  it("cancels editing only when cancellation is not confirmed", () => {
    const confirm = vi.fn(() => false);
    expect(shouldCancelReviewEditing({ hasUnsavedDraft: true, confirm })).toBe(true);
    expect(confirm).toHaveBeenCalledWith("有未保存的修改，确定取消编辑吗？");
    expect(shouldCancelReviewEditing({ hasUnsavedDraft: true, confirm: () => true })).toBe(false);
    expect(shouldCancelReviewEditing({ hasUnsavedDraft: false, confirm: () => false })).toBe(false);
  });

  it("starts an edit session only for a ready writable preview", () => {
    const segments = [{ type: "text", text: "original" }];
    const session = startReviewEditingFlow({
      previewId: 1,
      canWrite: true,
      detailReady: true,
      editState,
      segments,
    });
    expect(session).toMatchObject({ editing: true, editedSegments: segments });
    expect(session?.editedSegments).not.toBe(segments);

    expect(startReviewEditingFlow({
      previewId: null,
      canWrite: true,
      detailReady: true,
      editState,
      segments,
    })).toBeNull();
    expect(startReviewEditingFlow({
      previewId: 1,
      canWrite: false,
      detailReady: true,
      editState,
      segments,
    })).toBeNull();
    expect(startReviewEditingFlow({
      previewId: 1,
      canWrite: true,
      detailReady: false,
      editState,
      segments,
    })).toBeNull();
  });

  it("delegates dirty detection to the drawer state contract", () => {
    expect(reviewDrawerDirty({
      editing: false,
      editState,
      editSnapshot,
      editedSegments: null,
      segmentSnapshot: "[]",
    })).toBe(false);
    expect(reviewDrawerDirty({
      editing: false,
      editState: { ...editState, answer: "B" },
      editSnapshot,
      editedSegments: null,
      segmentSnapshot: "[]",
    })).toBe(true);
  });
});
