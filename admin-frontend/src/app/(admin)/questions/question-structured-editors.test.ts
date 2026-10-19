import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { StructuredTableEditor } from "@/components/structured-table-editor";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";
import { QuestionCodeEditor } from "./components/question-code-editor";
import { QuestionTableEditors } from "./components/question-table-editors";
import type { ContentSegment } from "./question-content-editing";

type Element = ReactElement<Record<string, unknown>>;
type PureComponent = (props: Record<string, unknown>) => ReactNode;

// Expand only these stateless editor wrappers; the table leaf owns React hooks.
function elements(node: ReactNode): Element[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!isValidElement<Record<string, unknown>>(node)) return [];
  if (typeof node.type === "function" && node.type !== StructuredTableEditor) {
    return elements((node.type as PureComponent)(node.props));
  }
  return [node, ...elements(node.props.children as ReactNode)];
}

function codeEditor(segments: ContentSegment[]) {
  const onReplace = vi.fn();
  const onAdd = vi.fn();
  const element = createElement(QuestionCodeEditor, { segments, onReplace, onAdd });
  return { element, nodes: elements(element), onReplace, onAdd };
}

function change(node: Element, value: string) {
  (node.props.onChange as (event: { target: { value: string } }) => void)({ target: { value } });
}

function click(node: Element) {
  (node.props.onClick as () => void)();
}

function tableEditor(segments: ContentSegment[]) {
  const onReplace = vi.fn();
  const element = createElement(QuestionTableEditors, { segments, onReplace });
  const tables = elements(element).filter((node) => node.type === StructuredTableEditor);
  return { element, tables, onReplace };
}

describe("question code editor integration", () => {
  it("exposes both add actions in the empty section", () => {
    const editor = codeEditor([{ type: "text", text: "stem" }]);
    expect(renderToStaticMarkup(editor.element)).toContain("0 个代码块");
    expect(editor.nodes.filter((node) => node.type === "textarea")).toHaveLength(0);
    editor.nodes.filter((node) => node.type === "button").forEach(click);
    expect(editor.onAdd).toHaveBeenCalledTimes(2);
    expect(editor.onReplace).not.toHaveBeenCalled();
  });

  it("reads legacy code text without promoting alt to a caption", () => {
    const editor = codeEditor([{ type: "code", text: "legacy();", alt: "hidden caption" }]);
    const inputs = editor.nodes.filter((node) => node.type === "input");
    expect(inputs.map((node) => node.props.value)).toEqual(["", ""]);
    const textarea = editor.nodes.find((node) => node.type === "textarea")!;
    expect(textarea.props.value).toBe("legacy();");
    expect(textarea.props.wrap).toBe("off");
    expect(textarea.props.spellCheck).toBe(false);
    const html = renderToStaticMarkup(editor.element);
    expect(html).toContain("1 个代码块");
    expect(html).not.toContain("hidden caption");
    expect(html).not.toContain("代码正文不能为空");
  });

  it.each(["", " \r\n "])("shows an empty-code warning for %j", (code) => {
    const html = renderToStaticMarkup(codeEditor([{ type: "code", code }]).element);
    expect(html).toContain("border-amber-300");
    expect(html).toContain("代码正文不能为空");
  });

  it("updates canonical code at the full segment index and retains neighboring objects", () => {
    const segments = [
      { type: "text", text: "stem" },
      { type: "code", text: "old", region_id: "r", alt: "description" },
      { type: "image", url: "img" },
      { type: "code", code: "second" },
    ];
    const before = structuredClone(segments);
    const editor = codeEditor(segments);
    change(editor.nodes.filter((node) => node.type === "textarea")[1], "updated");
    const next = editor.onReplace.mock.calls[0][0];
    expect(next).toEqual([segments[0], segments[1], segments[2], { type: "code", code: "updated" }]);
    expect(next[1]).toBe(segments[1]);
    change(editor.nodes.filter((node) => node.type === "textarea")[0], "");
    expect(editor.onReplace.mock.calls[1][0][1]).toEqual({
      type: "code", code: "", region_id: "r", alt: "description",
    });
    expect(segments).toEqual(before);
  });

  it("clears optional fields and preserves imported metadata", () => {
    const segment = { type: "code", code: "body", caption: "title", language: "c", alt: "kept" };
    const editor = codeEditor([{ type: "image" }, segment]);
    const inputs = editor.nodes.filter((node) => node.type === "input");
    change(inputs[0], "");
    change(inputs[1], "");
    expect(editor.onReplace.mock.calls[0][0][1]).toEqual({
      type: "code", code: "body", language: "c", alt: "kept",
    });
    expect(editor.onReplace.mock.calls[1][0][1]).toEqual({
      type: "code", code: "body", caption: "title", alt: "kept",
    });
    expect(segment.caption).toBe("title");
  });

  it("deletes the selected code without removing text, tables, or another code", () => {
    const segments = [{ type: "text" }, { type: "code" }, { type: "table" }, { type: "code" }];
    const editor = codeEditor(segments);
    // Header add button precedes the delete button for each code row.
    click(editor.nodes.filter((node) => node.type === "button")[2]);
    expect(editor.onReplace).toHaveBeenCalledExactlyOnceWith(segments.slice(0, 3));
    expect(segments).toHaveLength(4);
  });
});

describe("question table editor integration", () => {
  const table = { type: "table", table_id: "table-a", rows: [{ cells: [{ text: "A" }] }] };

  it("renders nothing when there are no table segments", () => {
    const editor = tableEditor([{ type: "text", text: "stem" }, { type: "code", code: "x" }]);
    expect(renderToStaticMarkup(editor.element)).toBe("");
    expect(editor.tables).toHaveLength(0);
  });

  it("passes normalized data to the existing table editor", () => {
    const editor = tableEditor([{ type: "text" }, table, { type: "code" }]);
    expect(editor.tables).toHaveLength(1);
    expect(editor.tables[0].props.segment).toEqual(normalizeStructuredTableSegment(table));
    expect(editor.tables[0].key).toBe("table-a");
    expect(renderToStaticMarkup(editor.element)).toContain("结构化表格编辑");
  });

  it("replaces and deletes by the complete segment index", () => {
    const segments = [{ type: "text" }, table, { type: "code" }, { ...table, table_id: "b" }];
    const before = structuredClone(segments);
    const editor = tableEditor(segments);
    const props = editor.tables[1].props as Parameters<typeof StructuredTableEditor>[0];
    const next = { ...normalizeStructuredTableSegment(table)!, table_id: "edited" };
    props.onChange(next);
    expect(editor.onReplace).toHaveBeenLastCalledWith([...segments.slice(0, 3), next]);
    props.onDelete!();
    expect(editor.onReplace).toHaveBeenLastCalledWith(segments.slice(0, 3));
    expect(segments).toEqual(before);
  });
});
