import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MathFormula } from "@/components/ui/math-formula";
import { extractOptionVisualModel } from "@/lib/option-visual-utils";
import type { EditState } from "../review-edit-state";
import { MultiBlankChoicePreview } from "./multi-blank-choice-preview";
import { OptionVisualPreview } from "./option-visual-preview";
import { ReviewQuestionPreview } from "./review-question-preview";

function props() {
  return {
    content: { stem: "stored stem" },
    draft: {
      stem: "draft stem", question_type: "single_choice", options: [{ key: "A", text: " A. first " }],
      multiBlank: undefined,
    } as Pick<EditState, "stem" | "question_type" | "options" | "multiBlank">,
    visualModel: { ...extractOptionVisualModel({}, {}), consumedSegmentIds: ["region:1"] },
    onRuntimeIssue: vi.fn(),
  };
}

function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if ([QuestionContentRenderer, MathFormula, MultiBlankChoicePreview, OptionVisualPreview]
      .some((component) => child.type === component)) {
      return [child];
    }
    if (typeof child.type === "function") {
      return elements((child.type as (props: unknown) => ReactNode)(child.props));
    }
    return elements(child.props.children as ReactNode);
  });
}

describe("review question preview", () => {
  it("keeps the content renderer's code, table, fallback and consumed-asset options", () => {
    const data = props();
    const renderer = elements(createElement(ReviewQuestionPreview, data))
      .find((element) => element.type === QuestionContentRenderer)!;
    expect(renderer.props).toEqual({
      content: data.content, fallbackText: "draft stem", showTableMetadata: true,
      ignoredSegmentIds: data.visualModel.consumedSegmentIds, preserveCodeText: true,
    });
  });

  it("normalizes regular option text and preserves empty options", () => {
    const data = props();
    const math = elements(createElement(ReviewQuestionPreview, data)).find(
      (element) => element.type === MathFormula,
    )!;
    expect(math.props.text).toBe(" A. first ");
    data.draft.options = [];
    expect(renderToStaticMarkup(createElement(ReviewQuestionPreview, data))).toContain("（无选项）");
  });

  it("prioritizes valid multi-blank groups and passes the existing group model intact", () => {
    const data = props();
    data.draft.question_type = "multi_blank_choice";
    data.draft.multiBlank = {
      groups: [{ id: "1", options: [] }, { id: "2", options: [] }],
      answerMap: { "1": "A" }, usesSharedOptions: true, sharedOptions: [{ key: "A", text: "a" }],
    };
    data.visualModel.mode = "placeholder_missing";
    const children = elements(createElement(ReviewQuestionPreview, data));
    const grouped = children.find((element) => element.type === MultiBlankChoicePreview)!;
    expect(grouped.props).toEqual({ ...data.draft.multiBlank, stem: data.draft.stem });
    expect(children.some((element) => element.type === OptionVisualPreview)).toBe(false);
  });

  it("falls back to image preview for incomplete groups and connects runtime feedback", () => {
    const data = props();
    data.draft.question_type = "multi_blank_multiple_choice";
    data.draft.multiBlank = {
      groups: [{ id: "1", options: [] }], answerMap: {}, usesSharedOptions: false, sharedOptions: [],
    };
    for (const mode of ["option_group", "option_images", "placeholder_missing", "unknown_visual"] as const) {
      data.visualModel.mode = mode;
      const visual = elements(createElement(ReviewQuestionPreview, data))
        .find((element) => element.type === OptionVisualPreview)!;
      expect(visual.props.options).toBe(data.draft.options);
      expect(visual.props.model).toBe(data.visualModel);
      expect(visual.props.onRuntimeIssue).toBe(data.onRuntimeIssue);
      (visual.props.onRuntimeIssue as (issue: string) => void)(mode);
    }
    expect(data.onRuntimeIssue).toHaveBeenCalledTimes(4);
  });
});
