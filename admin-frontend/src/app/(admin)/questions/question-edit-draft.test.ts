import { describe, expect, it } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { createQuestionEditDraft, savedQuestionEditDraft } from "./question-edit-draft";
import { buildQuestionEditPatch } from "./question-edit-patch";

const question: AdminQuestion = {
  id: 7, subject_id: 3, question_type: "single_choice", difficulty: 2,
  answer: "A", analysis: "explanation", knowledge_points: ["point"],
  content: { stem: "stem", segments: [{ type: "text", text: "stem" }] },
  options: { A: "yes", B: "no" }, review_status: "approved", is_active: true,
};

describe("question editor draft snapshots", () => {
  it("clones nested content but retains the existing option and knowledge point identities", () => {
    const before = structuredClone(question);
    const draft = createQuestionEditDraft(question);
    expect(draft.form).toEqual({
      subject_id: 3, question_type: "single_choice", difficulty: 2,
      answer: "A", analysis: "explanation", knowledge_points: ["point"],
      content: question.content, options: question.options,
    });
    expect(draft.form.content).not.toBe(question.content);
    expect(draft.form.content?.segments).not.toBe(question.content.segments);
    expect(draft.form.options).toBe(question.options);
    expect(draft.form.knowledge_points).toBe(question.knowledge_points);
    expect(draft.stemText).toBe("stem");
    expect(buildQuestionEditPatch(draft.form, question, draft.stemText)).toEqual({});
    expect(question).toEqual(before);
  });

  it("normalizes a legacy string without numeric object keys", () => {
    const legacy = { ...question, content: "legacy stem" as unknown as AdminQuestion["content"] };
    const draft = createQuestionEditDraft(legacy);
    expect(draft.form.content).toEqual({ stem: "legacy stem", text: "legacy stem" });
    expect(draft.stemText).toBe("legacy stem");
    expect(buildQuestionEditPatch(draft.form, legacy, draft.stemText)).toEqual({});
  });

  it.each([null, undefined, [], 5])("keeps legacy absent/invalid content safe: %s", (content) => {
    const legacy = { ...question, content: content as unknown as AdminQuestion["content"] };
    const draft = createQuestionEditDraft(legacy);
    expect(draft.form.content).toEqual({});
    expect(draft.stemText).toBe("");
  });

  it("normalizes OCR/math textarea text without rewriting persisted content", () => {
    const baseline = { ...question, content: {
      stem: "hidden OCR text", render_mode: "segments",
      segments: [{ type: "text", text: "x =\n y + z" }, { type: "image", url: "image" }],
    } };
    const draft = createQuestionEditDraft(baseline);
    expect(draft.form.content).toEqual(baseline.content);
    expect(draft.stemText).toBe("x =y + z");
    expect(buildQuestionEditPatch(draft.form, baseline, draft.stemText)).toEqual({});
  });

  it("converts legacy array options and preserves images for editing", () => {
    const legacy = { ...question, options: [
      { key: "A", text: "yes", imageUrl: "picture" }, { key: "B", text: "no" },
    ] };
    const draft = createQuestionEditDraft(legacy);
    expect(draft.form.options).toEqual({ A: { text: "yes", url: "picture" }, B: "no" });
    expect(buildQuestionEditPatch(draft.form, legacy, draft.stemText)).toEqual({});
  });

  it("resolves embedded options only when opening the editor", () => {
    const legacy = { ...question, options: null, content: { stem: "stem", options: { A: "yes" } } };
    expect(createQuestionEditDraft(legacy).form.options).toEqual({ A: "yes" });
    expect(savedQuestionEditDraft(legacy).form.options).toBeUndefined();
  });

  it("retains scalar defaults and clears null optional fields after saving", () => {
    const saved = { ...question, subject_id: undefined, question_type: "", answer: "",
      analysis: null, knowledge_points: null, options: null };
    const draft = savedQuestionEditDraft(saved);
    expect(draft.form).toEqual({
      subject_id: null, question_type: "", difficulty: 2, answer: "", analysis: "",
      knowledge_points: undefined, options: undefined, content: question.content,
    });
    expect(draft.form.content).toBe(saved.content);
    expect(draft.stemText).toBe("stem");
  });

  it("adopts response options directly instead of re-normalizing them", () => {
    const saved = { ...question, options: [{ key: "A", text: "yes", imageUrl: "picture" }] };
    expect(savedQuestionEditDraft(saved).form.options).toBe(saved.options);
  });
});
