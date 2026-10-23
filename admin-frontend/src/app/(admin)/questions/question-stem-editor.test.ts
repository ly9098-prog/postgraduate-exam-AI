import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { QuestionImageField } from "@/components/questions/question-image-field";
import { QuestionStemEditor } from "./question-stem-editor";

type PureComponent = (props: Record<string, unknown>) => ReactNode;
type Element = ReactElement<Record<string, unknown>>;

// Keep the image field unexpanded because it owns React state hooks.
function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === "function" && node.type !== QuestionImageField) {
    return elements((node.type as PureComponent)(node.props));
  }
  return [node, ...elements(node.props.children as ReactNode)];
}

function isElement(type: unknown) {
  return (node: Element) => node.type === type;
}

function render(props: Partial<Parameters<typeof QuestionStemEditor>[0]> = {}) {
  const setStemText = vi.fn();
  const beforeDirtyMutation = vi.fn();
  const onMutated = vi.fn();
  const nodes = elements(createElement(QuestionStemEditor, {
    stemText: "stem text",
    setStemText,
    segments: [{ type: "text", text: "stem" }],
    fallbackImageUrls: [],
    questionId: 7,
    dirty: true,
    beforeDirtyMutation,
    onMutated,
    ...props,
  }));
  return { nodes, setStemText, beforeDirtyMutation, onMutated };
}

describe("QuestionStemEditor", () => {
  it("renders the textarea and insertion image field when no image exists", () => {
    const ui = render();
    const textarea = ui.nodes.find(isElement("textarea"))! as {
      props: Record<string, unknown>;
    };
    (textarea.props.onChange as (event: { target: { value: string } }) => void)({
      target: { value: "changed" },
    });

    expect(ui.setStemText).toHaveBeenCalledWith("changed");
    expect(ui.nodes.some(isElement(QuestionImageField))).toBe(true);
  });

  it("passes every structured and legacy image to the image field", () => {
    const ui = render({
      segments: [
        { type: "text", text: "before" },
        { type: "image", url: "/structured.png" },
      ],
      fallbackImageUrls: ["/legacy.png"],
    });
    const fields = ui.nodes.filter(isElement(QuestionImageField)) as Array<{
      props: Record<string, unknown>;
    }>;

    expect(fields.map((field) => field.props.valueUrl)).toEqual([
      "/structured.png",
      "/legacy.png",
    ]);
    expect(fields.every((field) => field.props.addLabel === "更换图片")).toBe(true);
  });
});
