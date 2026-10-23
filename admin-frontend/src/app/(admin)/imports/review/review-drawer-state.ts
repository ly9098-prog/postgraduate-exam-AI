import type { ImportQuestionItem } from "@/lib/api/types";
import { editStateFromItem, type EditState } from "./review-edit-state";

export type ReviewSegments = Array<Record<string, unknown>> | null;

export function serializeReviewEditState(editState: EditState | null): string {
  return JSON.stringify(editState);
}

export function serializeReviewSegments(segments: ReviewSegments | undefined): string {
  return JSON.stringify(segments ?? []);
}

export function cloneReviewSegments(segments: ReviewSegments | undefined): ReviewSegments {
  if (!segments || segments.length === 0) return null;
  return JSON.parse(JSON.stringify(segments)) as ReviewSegments;
}

export function createReviewServerEditState(item: ImportQuestionItem) {
  const editState = editStateFromItem(item);
  return {
    editState,
    editSnapshot: serializeReviewEditState(editState),
  };
}

export function createReviewPreviewState(item: ImportQuestionItem) {
  const serverState = createReviewServerEditState(item);
  return {
    previewId: item.id,
    completedItem: null,
    editState: serverState.editState,
    editSnapshot: serverState.editSnapshot,
    segmentSnapshot: serializeReviewSegments(
      item.parsed_content?.segments as ReviewSegments | undefined,
    ),
    editing: false as const,
    detailView: "formatted" as const,
  };
}

export function createReviewEditSession(editState: EditState | null, segments: ReviewSegments | undefined) {
  const editedSegments = cloneReviewSegments(segments);
  return {
    editedSegments,
    segmentSnapshot: serializeReviewSegments(editedSegments),
    editSnapshot: serializeReviewEditState(editState),
    editing: true as const,
  };
}

export function hasUnsavedReviewDrawerChanges({
  editing,
  editState,
  editSnapshot,
  editedSegments,
  segmentSnapshot,
}: {
  editing: boolean;
  editState: EditState | null;
  editSnapshot: string;
  editedSegments: ReviewSegments;
  segmentSnapshot: string;
}): boolean {
  const hasEditStateChanges = Boolean(
    editState && serializeReviewEditState(editState) !== editSnapshot,
  );
  if (!editing) return hasEditStateChanges;
  const hasSegmentChanges = serializeReviewSegments(editedSegments) !== segmentSnapshot;
  return hasEditStateChanges || hasSegmentChanges;
}
