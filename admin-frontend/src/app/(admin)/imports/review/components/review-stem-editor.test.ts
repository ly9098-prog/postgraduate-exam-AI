import { Children, createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { StructuredTableEditor } from "@/components/structured-table-editor";
import { normalizeStructuredTableSegment, type StructuredTableSegment } from "@/lib/structured-table";
import { ReviewStemEditor } from "./review-stem-editor";

type Segment = Record<string, unknown>;

function props(segments: Segment[] | null = null) {
  return { stem: "original <stem>\n$x^2$", segments, onStemChange: vi.fn(), onSegmentsChange: vi.fn() };
}

// Keep the stateful table editor as a leaf while checking this feature's callbacks.
function controls(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    if (child.type === StructuredTableEditor) return [child];
    if (typeof child.type === "function") {
      return controls((child.type as (props: unknown) => ReactNode)(child.props));
    }
    const children = controls(child.props.children as ReactNode);
    return typeof child.type === "string" ? [child, ...children] : children;
  });
}

const legacy: Segment = { type: "table_markdown", markdown: "| H |\n| --- |\n| A |" };
const table: Segment = { type: "TABLE", table_id: "t2", rows: [{ cells: [{ text: "B" }] }] };

function editors(data: ReturnType<typeof props>) {
  return controls(createElement(ReviewStemEditor, data)).filter((child) => child.type === StructuredTableEditor);
}

describe("review stem editor", () => {
  it("preserves stem text and delegates input without touching table state", () => {
    const data = props();
    const view = createElement(ReviewStemEditor, data);
    const html = renderToStaticMarkup(view);
    expect(html).toContain("original &lt;stem&gt;\n$x^2$");
    const input = controls(view).find((child) => child.type === "textarea")!;
    (input.props.onChange as (event: unknown) => void)({ target: { value: "  next\n  " } });
    expect(data.onStemChange).toHaveBeenCalledExactlyOnceWith("  next\n  ");
    expect(data.onSegmentsChange).not.toHaveBeenCalled();
    expect(data.stem).toBe("original <stem>\n$x^2$");
  });

  it("keeps the explicit table gate and skips unnormalizable tables", () => {
    for (const segments of [null, [], [{ type: "text", text: "body" }], [{ markdown: legacy.markdown }]]) {
      const data = props(segments);
      expect(editors(data)).toHaveLength(0);
      expect(renderToStaticMarkup(createElement(ReviewStemEditor, data))).not.toContain("drawer-section-delay-3");
    }
    const invalid = props([{ type: "table", rows: [] }]);
    expect(editors(invalid)).toHaveLength(0);
    expect(renderToStaticMarkup(createElement(ReviewStemEditor, invalid))).toContain("drawer-section-delay-3");
  });

  it("normalizes all segments after the gate, retaining keys and original source indices", () => {
    const markdownOnly = { markdown: legacy.markdown };
    const data = props([{ type: "text", text: "body" }, { type: "table", rows: [] }, legacy, table, markdownOnly]);
    const tables = editors(data);
    expect(tables).toHaveLength(3);
    for (const [index, source] of [legacy, table, markdownOnly].entries()) {
      const normalized = normalizeStructuredTableSegment(source)!;
      expect(tables[index].props.segment).toEqual(normalized);
      expect(tables[index].key).toContain(normalized.table_id);
    }
    const replacement = { ...normalizeStructuredTableSegment(table)!, caption: "edited" };
    (tables[1].props.onChange as (value: StructuredTableSegment) => void)(replacement);
    const next = data.onSegmentsChange.mock.calls[0][0] as Segment[];
    expect(next).toEqual([data.segments![0], data.segments![1], legacy, replacement, markdownOnly]);
    expect(next).not.toBe(data.segments);
    expect(next[0]).toBe(data.segments![0]);
    expect(next[3]).toBe(replacement);
    expect(data.segments![3]).toBe(table);
    expect(data.onStemChange).not.toHaveBeenCalled();
  });

  it("removes only the selected table while preserving unrelated and duplicate segments", () => {
    const image = { type: "image", url: "/source.png" };
    const data = props([image, legacy, table, legacy]);
    const tables = editors(data);
    (tables[0].props.onDelete as () => void)();
    expect(data.onSegmentsChange).toHaveBeenCalledExactlyOnceWith([image, table, legacy]);
    expect(data.segments).toEqual([image, legacy, table, legacy]);
    expect(data.onStemChange).not.toHaveBeenCalled();
  });
});
