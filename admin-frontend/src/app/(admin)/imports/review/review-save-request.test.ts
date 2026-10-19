import { describe, expect, it, vi } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import { buildReviewSavePayload, executeReviewSaveRequest } from "./review-save-request";
import type { EditState } from "./review-edit-state";

const item = {
  id: 7,
  batch_id: "batch-1",
  source_type: "text",
  status: "pending",
  ai_generated: false,
  ai_answer_flag: false,
  risk_flags: [],
  risk_level: "low",
  risk_reasons: [],
  created_at: "",
  updated_at: "",
  subject_id: 3,
  parsed_content: { text: "old", segments: [{ type: "text", text: "old" }] },
} as ImportQuestionItem;

const state: EditState = {
  subject_id: 4,
  question_type: "single_choice",
  stem: "new stem",
  options: [{ key: "A", text: "alpha" }, { key: "B", text: "beta", segments: [{ type: "text", text: "beta" }] }],
  answer: "A",
  analysis: "analysis",
};

describe("review save request", () => {
  it("builds the ordinary payload and preserves option segment metadata", () => {
    expect(buildReviewSavePayload(state, item, null)).toEqual({
      subject_id: 4,
      question_type: "single_choice",
      stem: "new stem",
      answer: "A",
      analysis: "analysis",
      options: [
        { key: "A", text: "alpha" },
        { key: "B", text: "beta", segments: [{ type: "text", text: "beta" }] },
      ],
    });
  });

  it("uses edited segments and rejects visual blockers before the API call", async () => {
    const request = vi.fn();
    const segments = [{ type: "text", text: "edited" }];
    expect(buildReviewSavePayload(state, item, segments)).toMatchObject({
      parsed_content: {
        stem: "new stem",
        text: "new stem",
        render_mode: "segments",
        segments,
      },
    });
    await expect(executeReviewSaveRequest({
      previewId: 7,
      editState: state,
      previewItem: item,
      editedSegments: null,
      visualBlockReasons: ["选项图片缺失"],
      request,
    })).rejects.toThrow("无法保存：选项图片缺失");
    expect(request).not.toHaveBeenCalled();
  });

  it("builds the multi-blank payload with the edited scalar fields", () => {
    const multiBlank: EditState = {
      ...state,
      question_type: "multi_blank_choice",
      multiBlank: {
        groups: [
          { id: "①", options: [{ key: "A", text: "a" }, { key: "B", text: "b" }] },
          { id: "②", options: [{ key: "A", text: "a" }, { key: "B", text: "b" }] },
        ],
        answerMap: { "①": "A", "②": "B" },
        usesSharedOptions: true,
        sharedOptions: [],
      },
    };
    expect(buildReviewSavePayload(multiBlank, item, null)).toMatchObject({
      subject_id: 4,
      analysis: "analysis",
      question_type: "multi_blank_choice",
      answer: "①:A;②:B",
      parsed_options: null,
    });
  });
});
