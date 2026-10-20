import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { extractOptionVisualModel } from "@/lib/option-visual-utils";
import type { EditState } from "../review-edit-state";
import { MultiBlankChoiceEditor } from "./multi-blank-choice-editor";
import { OptionVisualEditor } from "./option-visual-editor";
import { ReviewOptionEditor } from "./review-option-editor";

function props() {
  return {
    questionType: "single_choice",
    options: [{
      key: "A", text: "old", extra: 7,
      segments: [{ type: "text", text: "hidden" }, { type: "IMAGE", url: "/a.png" },
        { type: "newline" }, { type: "audio" }],
    }],
    multiBlank: undefined as EditState["multiBlank"],
    visualModel: extractOptionVisualModel({}, {}),
    onOptionsChange: vi.fn(), onMultiBlankAction: vi.fn(), onRequestTextModeOverride: vi.fn(),
  };
}

// Leave existing stateful editors intact and inspect only this feature's wiring.
function controls(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if (child.type === MultiBlankChoiceEditor || child.type === OptionVisualEditor) return [child];
    if (typeof child.type === "function") {
      return controls((child.type as (props: unknown) => ReactNode)(child.props));
    }
    const children = controls(child.props.children as ReactNode);
    return typeof child.type === "string" ? [child, ...children] : children;
  });
}

describe("review option editor", () => {
  it("renders regular options and keeps original segment indices when removing a visible chip", () => {
    const data = props();
    const view = createElement(ReviewOptionEditor, data);
    const html = renderToStaticMarkup(view);
    expect(html).toContain('value="old"');
    expect(html).toContain('src="/a.png"');
    expect(html).toContain("换行");
    expect(html).not.toContain("hidden</");
    const elements = controls(view);
    const input = elements.find((element) => element.type === "input")!;
    (input.props.onChange as (event: unknown) => void)({ target: { value: "new" } });
    const remove = elements.filter((element) => element.props.title === "移除该片段");
    expect(remove).toHaveLength(2);
    (remove[0].props.onClick as () => void)();
    expect(data.onOptionsChange.mock.calls[0][0][0]).toEqual({ ...data.options[0], text: "new" });
    expect(data.onOptionsChange.mock.calls[1][0][0]).toEqual({
      ...data.options[0], segments: [data.options[0].segments[0], ...data.options[0].segments.slice(2)],
    });
    expect(data.options[0].segments).toHaveLength(4);
    expect(data.options[0].text).toBe("old");
    expect(data.onMultiBlankAction).not.toHaveBeenCalled();
  });

  it("preserves the empty regular-option message", () => {
    const data = { ...props(), options: [] };
    expect(renderToStaticMarkup(createElement(ReviewOptionEditor, data))).toContain("暂无可编辑选项");
  });

  it("prioritizes valid multi-blank groups and passes the reducer callback and validation metadata", () => {
    const data = props();
    data.questionType = " MULTI-BLANK-MULTIPLE-CHOICE ";
    data.visualModel = { ...data.visualModel, mode: "placeholder_missing" };
    data.multiBlank = {
      groups: [{ id: "1", options: [] }, { id: "2", options: [] }], answerMap: {},
      usesSharedOptions: false, sharedOptions: [], dedupWarnings: ["warning"],
      dedupErrors: ["error"], hasUnappliedDraft: true,
    };
    const editor = controls(createElement(ReviewOptionEditor, data)).find(
      (element) => element.type === MultiBlankChoiceEditor,
    )!;
    expect(editor).toBeDefined();
    expect(editor.props).toEqual({ ...data.multiBlank, multiSelect: true, onAction: data.onMultiBlankAction });
    expect(controls(createElement(ReviewOptionEditor, data)).some(
      (element) => element.type === OptionVisualEditor,
    )).toBe(false);
  });

  it("falls back to visual editing for incomplete groups and preserves explicit override wiring", () => {
    const data = props();
    data.questionType = "multi_blank_choice";
    data.multiBlank = {
      groups: [{ id: "1", options: [] }], answerMap: {}, usesSharedOptions: false, sharedOptions: [],
    };
    for (const mode of ["option_group", "option_images", "placeholder_missing", "unknown_visual"] as const) {
      data.visualModel = { ...data.visualModel, mode };
      const editor = controls(createElement(ReviewOptionEditor, data)).find(
        (element) => element.type === OptionVisualEditor,
      )!;
      expect(editor.props.options).toBe(data.options);
      expect(editor.props.model).toBe(data.visualModel);
      expect(editor.props.onChange).toBe(data.onOptionsChange);
      expect(editor.props.onRequestTextModeOverride).toBe(data.onRequestTextModeOverride);
    }
  });
});
