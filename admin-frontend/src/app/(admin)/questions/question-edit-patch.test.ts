import { describe, expect, it } from "vitest";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { buildQuestionEditPatch } from "./question-edit-patch";
import { normalizeStemForEditing, textForStemEditor } from "./question-content-editing";

const question: AdminQuestion = {
  id: 7, subject_id: 3, question_type: "single_choice", answer: "A", analysis: "explanation",
  difficulty: 2, content: { stem: "stem", text: "stem" }, options: { A: "yes", B: "no" },
  knowledge_points: ["point"], review_status: "approved", is_active: true,
};

function formFor(value: AdminQuestion): QuestionEditRequest {
  return {
    subject_id: value.subject_id, question_type: value.question_type, answer: value.answer,
    analysis: value.analysis ?? "", difficulty: value.difficulty, content: value.content,
    options: value.options, knowledge_points: value.knowledge_points ?? undefined,
  };
}

describe("question minimal edit patch", () => {
  it("keeps an unchanged edit empty and does not mutate either input", () => {
    const form = structuredClone(formFor(question));
    const baseline = structuredClone(question);
    expect(buildQuestionEditPatch(form, baseline, "stem")).toEqual({});
    expect(form).toEqual(formFor(question));
    expect(baseline).toEqual(question);
  });

  it.each([
    ["answer", "B"], ["analysis", ""], ["difficulty", 4],
    ["question_type", "judge"], ["subject_id", null],
  ] as const)("patches only the changed %s field", (field, value) => {
    const form = { ...formFor(question), [field]: value };
    expect(buildQuestionEditPatch(form, question, "stem")).toEqual({ [field]: value });
  });

  it("does not infer a difficulty edit from an absent form value", () => {
    expect(buildQuestionEditPatch({ ...formFor(question), difficulty: undefined }, question))
      .toEqual({});
  });

  it("compares optional scalar fields with the existing null/empty semantics", () => {
    const baseline = { ...question, subject_id: null, analysis: null };
    const form = { ...formFor(baseline), subject_id: undefined, analysis: undefined };
    expect(buildQuestionEditPatch(form, baseline)).toEqual({});
  });

  it("ignores metadata fields that are not editable in this form", () => {
    expect(buildQuestionEditPatch({
      ...formFor(question), source: "different", source_type: "different",
    }, question)).toEqual({});
  });

  it("does not persist hidden legacy stem differences during an answer edit", () => {
    const baseline = { ...question, content: {
      stem: "OCR-only old text", render_mode: "segments",
      segments: [{ type: "text", text: "visible text" }],
    } };
    expect(buildQuestionEditPatch({ ...formFor(baseline), answer: "B" }, baseline, "visible text"))
      .toEqual({ answer: "B" });
  });

  it("does not persist math wrap normalization when another field changes", () => {
    const baseline = { ...question, content: { stem: "x =\n y + z" } };
    const visible = normalizeStemForEditing(textForStemEditor(baseline.content));
    expect(visible).toBe("x =y + z");
    expect(buildQuestionEditPatch({ ...formFor(baseline), difficulty: 3 }, baseline, visible))
      .toEqual({ difficulty: 3 });
  });

  it("rebuilds only stem segments while retaining image/code/option/table content", () => {
    const nonStem = [
      { type: "image", url: "image" }, { type: "code", code: "int x;" },
      { type: "text", option_key: "A", text: "option" }, { type: "table", rows: [["x"]] },
    ];
    const baseline = { ...question, content: {
      stem: "stem", custom: "kept", segments: [{ type: "text", text: "stem" }, ...nonStem],
    } };
    const patch = buildQuestionEditPatch(formFor(baseline), baseline, "new\nstem");
    expect(patch).toEqual({ content: {
      stem: "new\nstem", text: "new\nstem", custom: "kept",
      segments: [
        { type: "text", text: "new" }, { type: "newline" },
        { type: "text", text: "stem" }, ...nonStem,
      ],
    } });
    expect(baseline.content.stem).toBe("stem");
  });

  it("accepts omitted textarea state and explicit clearing independently", () => {
    expect(buildQuestionEditPatch({ ...formFor(question), content: { stem: "typed" } }, question))
      .toEqual({ content: { stem: "typed", text: "typed" } });
    expect(buildQuestionEditPatch(formFor(question), question, ""))
      .toEqual({ content: { stem: "", text: "" } });
  });

  it("preserves the submitted content identity for a structured-only edit", () => {
    const content = { ...question.content, segments: [{ type: "code", code: "new code" }] };
    const patch = buildQuestionEditPatch({ ...formFor(question), content }, question, "stem");
    expect(patch.content).toBe(content);
    expect(Object.keys(patch)).toEqual(["content"]);
  });

  it.each(["blank_option_groups", "blank_groups"])(
    "tracks changed multi-blank options stored as %s", (key) => {
      const baseline = { ...question, content: { stem: "stem", [key]: { "1": { A: "old" } } } };
      const content = { stem: "stem", [key]: { "1": { A: "new" } } };
      expect(buildQuestionEditPatch({ ...formFor(baseline), content }, baseline, "stem"))
        .toEqual({ content });
    },
  );

  it("compares normalized option keys/text/images across legacy storage shapes", () => {
    const baseline = { ...question, options: [
      { key: "A", text: "yes", imageUrl: "image" }, { key: "B", text: "no" },
    ] };
    expect(buildQuestionEditPatch({
      ...formFor(baseline), options: { A: { text: "yes", url: "image" }, B: "no" },
    }, baseline)).toEqual({});
    const options = { A: { text: "yes", url: "changed" }, B: "no" };
    expect(buildQuestionEditPatch({ ...formFor(baseline), options }, baseline)).toEqual({ options });
  });

  it("does not rewrite options resolved from legacy content", () => {
    const baseline = { ...question, options: null, content: {
      stem: "stem", options: { A: "yes", B: "no" },
    } };
    expect(buildQuestionEditPatch({ ...formFor(baseline), options: question.options }, baseline))
      .toEqual({});
  });

  it("clears options and knowledge points using their existing wire values", () => {
    expect(buildQuestionEditPatch({
      ...formFor(question), options: undefined, knowledge_points: undefined,
    }, question)).toEqual({ options: null, knowledge_points: [] });
  });

  it("keeps knowledge-point ordering significant without mutating the selection", () => {
    const baseline = { ...question, knowledge_points: ["a", "b"] };
    const points = ["b", "a"];
    expect(buildQuestionEditPatch({ ...formFor(baseline), knowledge_points: points }, baseline))
      .toEqual({ knowledge_points: points });
    expect(points).toEqual(["b", "a"]);
  });
});
