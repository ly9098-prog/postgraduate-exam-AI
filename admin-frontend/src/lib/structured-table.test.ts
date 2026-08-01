import { describe, expect, it } from "vitest";
import {
  buildTableLayout,
  normalizeStructuredTableSegment,
  tableRowsToMarkdown,
  updateStructuredTableRows,
} from "./structured-table";

describe("structured table.v2", () => {
  it("normalizes row and column spans without flattening merged cells", () => {
    const table = normalizeStructuredTableSegment({
      type: "table",
      schema_version: "table.v2",
      confidence: 0.94,
      rows: [
        { cells: [
          { text: "进程", is_header: true, row_span: 2 },
          { text: "时间", is_header: true, col_span: 2 },
        ] },
        { cells: [
          { text: "到达", is_header: true },
          { text: "服务", is_header: true },
        ] },
        { cells: [{ text: "P1" }, { text: "0" }, { text: "3" }] },
      ],
    });

    expect(table).not.toBeNull();
    expect(table?.row_count).toBe(3);
    expect(table?.column_count).toBe(3);
    expect(table?.requires_review).toBe(false);
    expect(buildTableLayout(table!.rows).anchors).toHaveLength(7);
  });

  it("migrates legacy table_markdown into table.v2", () => {
    const table = normalizeStructuredTableSegment({
      type: "table_markdown",
      markdown: "| 名称 | 数值 |\n| --- | --- |\n| A | 1 |",
    });

    expect(table?.schema_version).toBe("table.v2");
    expect(table?.has_header).toBe(true);
    expect(table?.rows[1].cells[1].text).toBe("1");
  });

  it("preserves empty cells and line breaks in the Markdown compatibility projection", () => {
    const table = normalizeStructuredTableSegment({
      type: "table",
      rows: [
        { cells: [{ text: "名称", is_header: true }, { text: "说明", is_header: true }] },
        { cells: [{ text: "" }, { text: "第一行\n第二行" }] },
      ],
    });

    expect(tableRowsToMarkdown(table!.rows)).toContain("<br>");
    expect(tableRowsToMarkdown(table!.rows)).toContain("|  | 第一行");
  });

  it("marks invalid row spans for manual review", () => {
    const table = normalizeStructuredTableSegment({
      type: "table",
      rows: [{ cells: [{ text: "A", row_span: 4 }] }],
    });

    expect(table?.requires_review).toBe(true);
    expect(table?.signals.length).toBeGreaterThan(0);
  });

  it("does not allow manual verification to hide structural errors", () => {
    const table = normalizeStructuredTableSegment({
      type: "table",
      manual_verified: true,
      requires_review: false,
      rows: [{ cells: [{ text: "A", row_span: 4 }] }],
    });

    expect(table?.requires_review).toBe(true);
  });

  it("recomputes dimensions after admin edits", () => {
    const table = normalizeStructuredTableSegment({
      type: "table",
      rows: [{ cells: [{ text: "A" }, { text: "B" }] }],
    })!;
    const updated = updateStructuredTableRows(table, [
      ...table.rows,
      { cells: [{ text: "1", content: [{ type: "text", text: "1" }], row_span: 1, col_span: 2, is_header: false, alignment: "center", confidence: 1 }] },
    ]);

    expect(updated.row_count).toBe(2);
    expect(updated.column_count).toBe(2);
    expect(updated.rows[1].cells[0].col_span).toBe(2);
  });
});
