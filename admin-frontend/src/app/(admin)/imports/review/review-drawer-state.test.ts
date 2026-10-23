import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import type { EditState } from "./review-edit-state";
import {
  cloneReviewSegments,
  createReviewEditSession,
  createReviewPreviewState,
  createReviewServerEditState,
  hasUnsavedReviewDrawerChanges,
  serializeReviewEditState,
  serializeReviewSegments,
  type ReviewSegments,
} from "./review-drawer-state";

const item = {
  id: 7,
  batch_id: "batch",
  source_type: "pdf",
  status: "pending",
  ai_generated: false,
  ai_answer_flag: false,
  risk_flags: [],
  risk_level: "low",
  risk_reasons: [],
  created_at: "",
  updated_at: "",
  parsed_content: {
    stem: "stem",
    segments: [{ type: "text", text: "snapshot" }],
  },
  parsed_answer: "A",
  parsed_options: [{ key: "A", text: "option A" }],
  question_type: "single_choice",
} as unknown as ImportQuestionItem;

const editState: EditState = {
  subject_id: null,
  question_type: "single_choice",
  stem: "stem",
  options: [{ key: "A", text: "option A", segments: undefined }],
  answer: "A",
  analysis: "",
};

function dirty(
  state: EditState | null,
  editSnapshot: string,
  editedSegments: ReviewSegments,
  segmentSnapshot: string,
  editing = true,
) {
  return hasUnsavedReviewDrawerChanges({
    editing,
    editState: state,
    editSnapshot,
    editedSegments,
    segmentSnapshot,
  });
}

describe("review drawer state", () => {
  it("creates the preview snapshot from the item without sharing editable objects", () => {
    const preview = createReviewPreviewState(item);
    const sourceSegments = item.parsed_content?.segments as unknown[];
    expect(preview).toMatchObject({
      previewId: 7,
      completedItem: null,
      editSnapshot: serializeReviewEditState(preview.editState),
      segmentSnapshot: serializeReviewSegments(sourceSegments as ReviewSegments),
      editing: false,
      detailView: "formatted",
    });
    expect(preview.editState).toEqual(editState);
    expect((item.parsed_content?.segments as Array<Record<string, unknown>>)[0].text).toBe("snapshot");
  });

  it("keeps null and empty segment arrays distinct for cloning but equal for serialization", () => {
    expect(cloneReviewSegments(null)).toBeNull();
    expect(cloneReviewSegments([])).toBeNull();
    expect(cloneReviewSegments(undefined)).toBeNull();
    const source = [{ type: "image", url: "/a.png", nested: { value: 1 } }];
    const clone = cloneReviewSegments(source)!;
    expect(clone).toEqual(source);
    expect(clone).not.toBe(source);
    expect(clone[0]).not.toBe(source[0]);
    expect(clone[0].nested).not.toBe(source[0].nested);
    expect(serializeReviewSegments(null)).toBe("[]");
    expect(serializeReviewSegments([])).toBe("[]");
  });

  it("starts editing with a cloned segment snapshot and the current edit snapshot", () => {
    const segments = [{ type: "text", text: "original" }];
    const session = createReviewEditSession(editState, segments);
    expect(session.editing).toBe(true);
    expect(session.editedSegments).toEqual(segments);
    expect(session.editedSegments).not.toBe(segments);
    expect(session.editSnapshot).toBe(serializeReviewEditState(editState));
    expect(session.segmentSnapshot).toBe(serializeReviewSegments(segments));
  });

  it("detects view-mode draft changes but ignores inactive segment changes", () => {
    expect(dirty(
      editState, serializeReviewEditState(editState), [], "[]", false,
    )).toBe(false);
    expect(dirty(
      { ...editState, answer: "B" },
      serializeReviewEditState(editState), [], "[]", false,
    )).toBe(true);
    expect(dirty(
      editState,
      serializeReviewEditState(editState),
      [{ type: "text", text: "inactive" }],
      "[]",
      false,
    )).toBe(false);
  });

  it("rebases the view-mode snapshot when full detail replaces the queue brief", () => {
    const detailItem = {
      ...item,
      parsed_analysis: "loaded from detail",
      parsed_content: {
        stem: "full detail stem",
        segments: [{ type: "text", text: "detail" }],
      },
    } as unknown as ImportQuestionItem;
    const serverState = createReviewServerEditState(detailItem);

    expect(serverState.editSnapshot).toBe(serializeReviewEditState(serverState.editState));
    expect(dirty(serverState.editState, serverState.editSnapshot, [], "[]", false)).toBe(false);
    expect(dirty(
      { ...serverState.editState, answer: "B" },
      serverState.editSnapshot,
      [],
      "[]",
      false,
    )).toBe(true);
  });

  it("detects edit and segment changes independently with the existing null fallback", () => {
    const snapshot = serializeReviewEditState(editState);
    expect(dirty(editState, snapshot, null, "[]")).toBe(false);
    expect(dirty(null, snapshot, null, "[]")).toBe(false);
    expect(dirty({ ...editState, answer: "B" }, snapshot, null, "[]")).toBe(true);
    expect(dirty(editState, snapshot, [{ type: "text", text: "added" }], "[]")).toBe(true);
    expect(dirty(editState, snapshot, null, "not-empty")).toBe(true);
    expect(dirty(editState, snapshot, [], "[]")).toBe(false);
  });

  it("uses JSON key order as part of the established dirty comparison", () => {
    const reordered = {
      analysis: "",
      answer: "A",
      options: editState.options,
      stem: editState.stem,
      question_type: editState.question_type,
      subject_id: null,
    } as EditState;
    expect(dirty(reordered, serializeReviewEditState(editState), null, "[]")).toBe(true);
  });
});
