import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { SegmentData } from "@/lib/segment-utils";
import { ReviewVisualSegmentEditor } from "./review-visual-segment-editor";

function props(segments: SegmentData[] | null = [
  { type: "text", text: "hidden", extra: 7 },
  { type: "IMAGE", url: "/preview.png", alt: "", option_key: "B", extra: 9 },
  { type: "newline" }, { type: "math_image" },
]) {
  return {
    segments, options: [{ key: "A" }, { key: "B" }], uploading: -1,
    drag: {
      dragIndex: 1, overIndex: 2, start: vi.fn(), over: vi.fn(),
      leave: vi.fn(), drop: vi.fn(), end: vi.fn(),
    },
    inputRef: { current: null }, onFileChange: vi.fn(), onChange: vi.fn(), onReplace: vi.fn(),
  };
}

function controls(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if (typeof child.type === "function") {
      return controls((child.type as (props: unknown) => ReactNode)(child.props));
    }
    const children = controls(child.props.children as ReactNode);
    return typeof child.type === "string" ? [child, ...children] : children;
  });
}

describe("review visual segment editor", () => {
  it("retains visibility, full-array numbering, missing images and drag classes", () => {
    for (const value of [null, [], [{ type: "newline" }], [{ type: "table" }]]) {
      expect(renderToStaticMarkup(createElement(ReviewVisualSegmentEditor, props(value)))).toBe("");
    }
    const html = renderToStaticMarkup(createElement(ReviewVisualSegmentEditor, props()));
    expect(html).toContain("视觉片段编辑器");
    expect(html).toContain("2/4");
    expect(html).toContain("4/4");
    expect(html).toContain('alt=""');
    expect(html).toContain("暂无图片");
    expect(html).toContain("dragging border-");
    expect(html).toContain("drop-target");
    expect(html).toContain("归属：选项 B");
    expect(html).not.toContain("hidden</");
  });

  it("routes immutable reorder, assignment and deletion through the existing segment utilities", () => {
    const data = props();
    const elements = controls(createElement(ReviewVisualSegmentEditor, data));
    const buttons = elements.filter((element) => element.type === "button");
    const up = buttons.find((element) => element.props.title === "上移")!;
    const remove = buttons.find((element) => element.props.title === "删除此片段")!;
    (up.props.onClick as () => void)();
    (remove.props.onClick as () => void)();
    const select = elements.find((element) => element.type === "select")!;
    (select.props.onChange as (event: unknown) => void)({ target: { value: "A" } });
    const original = data.segments!;
    expect(data.onChange.mock.calls[0][0]).toEqual([original[1], original[0], original[2], original[3]]);
    expect(data.onChange.mock.calls[1][0]).toEqual([original[0], original[2], original[3]]);
    expect(data.onChange.mock.calls[2][0][1]).toEqual({ ...original[1], option_key: "A", assignment_method: "manual_review" });
    expect(data.segments![1].option_key).toBe("B");
    expect(up.props.disabled).toBe(false);
    expect(buttons.filter((element) => element.props.title === "下移").at(-1)?.props.disabled).toBe(true);
  });

  it("connects file and drag callbacks with original indices and uploading state", () => {
    const data = { ...props(), uploading: 1 };
    const elements = controls(createElement(ReviewVisualSegmentEditor, data));
    const input = elements.find((element) => element.type === "input")!;
    expect(input.props.onChange).toBe(data.onFileChange);
    expect(input.props.ref).toBe(data.inputRef);
    expect(input.props.accept).toBe("image/jpeg,image/png,image/webp");
    const card = elements.find((element) => element.props.draggable)!;
    const event = {};
    for (const name of ["onDragStart", "onDragOver", "onDrop"]) {
      (card.props[name] as (event: unknown) => void)(event);
    }
    expect(data.drag.start).toHaveBeenCalledWith(1, event);
    expect(data.drag.over).toHaveBeenCalledWith(1, event);
    expect(data.drag.drop).toHaveBeenCalledWith(1, event);
    expect(card.props.onDragLeave).toBe(data.drag.leave);
    expect(card.props.onDragEnd).toBe(data.drag.end);
    const replace = elements.filter((element) => element.type === "button" && !element.props.title)[0];
    expect(replace.props.disabled).toBe(true);
    (replace.props.onClick as () => void)();
    expect(data.onReplace).toHaveBeenCalledWith(1);
    expect(renderToStaticMarkup(createElement(ReviewVisualSegmentEditor, data))).toContain("上传中…");
  });
});
