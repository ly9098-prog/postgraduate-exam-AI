import {
  createReviewEditSession,
  hasUnsavedReviewDrawerChanges,
} from "./review-drawer-state";
import type { EditState } from "./review-edit-state";

export function shouldKeepCurrentReviewDrawer({
  previewId,
  segmentUploading,
  completePending,
  hasUnsavedDraft,
  confirm,
}: {
  previewId: number | null;
  segmentUploading: number;
  completePending: boolean;
  hasUnsavedDraft: boolean;
  confirm: (message: string) => boolean;
}): boolean {
  if (segmentUploading >= 0 || completePending) return true;
  return previewId !== null && hasUnsavedDraft &&
    !confirm("有未保存的修改，确定切换到其他题目吗？");
}

export function shouldKeepClosedReviewDrawer({
  segmentUploading,
  completePending,
  hasUnsavedDraft,
  confirm,
}: {
  segmentUploading: number;
  completePending: boolean;
  hasUnsavedDraft: boolean;
  confirm: (message: string) => boolean;
}): boolean {
  if (segmentUploading >= 0 || completePending) return true;
  return hasUnsavedDraft && !confirm("有未保存的修改，确定关闭吗？");
}

export function shouldCancelReviewEditing({
  hasUnsavedDraft,
  confirm,
}: {
  hasUnsavedDraft: boolean;
  confirm: (message: string) => boolean;
}): boolean {
  return hasUnsavedDraft && !confirm("有未保存的修改，确定取消编辑吗？");
}

export function startReviewEditingFlow({
  previewId,
  canWrite,
  detailReady,
  editState,
  segments,
}: {
  previewId: number | null;
  canWrite: boolean;
  detailReady: boolean;
  editState: EditState | null;
  segments: Array<Record<string, unknown>> | undefined;
}) {
  if (!previewId || !canWrite || !detailReady) return null;
  return createReviewEditSession(editState, segments);
}

export function reviewDrawerDirty({
  editing,
  editState,
  editSnapshot,
  editedSegments,
  segmentSnapshot,
}: Parameters<typeof hasUnsavedReviewDrawerChanges>[0]) {
  return hasUnsavedReviewDrawerChanges({
    editing,
    editState,
    editSnapshot,
    editedSegments,
    segmentSnapshot,
  });
}
