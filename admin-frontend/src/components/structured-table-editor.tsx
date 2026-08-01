"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import {
  buildTableLayout,
  createTableCell,
  normalizeStructuredTableSegment,
  updateStructuredTableRows,
  type StructuredTableCell,
  type StructuredTableRow,
  type StructuredTableSegment,
} from "@/lib/structured-table";

function cloneRows(rows: StructuredTableRow[]): StructuredTableRow[] {
  return rows.map((row) => ({
    cells: row.cells.map((cell) => ({
      ...cell,
      content: cell.content.map((block) => ({ ...block })),
      bbox: cell.bbox ? [...cell.bbox] : null,
    })),
  }));
}

export function StructuredTableEditor({
  segment,
  onChange,
  onDelete,
}: {
  segment: unknown;
  onChange: (segment: StructuredTableSegment) => void;
  onDelete?: () => void;
}) {
  const table = useMemo(() => normalizeStructuredTableSegment(segment), [segment]);
  if (!table) return null;
  // Narrowed non-null alias so TS keeps the type inside the closures below.
  const current = table;
  const layout = buildTableLayout(current.rows);

  function commit(rows: StructuredTableRow[]) {
    onChange(updateStructuredTableRows(current, rows));
  }

  function updateCell(rowIndex: number, cellIndex: number, patch: Partial<StructuredTableCell>) {
    const rows = cloneRows(current.rows);
    const currentCell = rows[rowIndex].cells[cellIndex];
    const next = { ...currentCell, ...patch };
    if (patch.text !== undefined) next.content = [{ type: "text", text: patch.text }];
    rows[rowIndex].cells[cellIndex] = next;
    commit(rows);
  }

  function addRow() {
    const width = Math.max(1, layout.columnCount);
    commit([...cloneRows(current.rows), { cells: Array.from({ length: width }, () => createTableCell()) }]);
  }

  function deleteRow(rowIndex: number) {
    const rows = cloneRows(current.rows).filter((_, index) => index !== rowIndex);
    if (rows.length > 0) commit(rows);
  }

  function addCell(rowIndex: number) {
    const rows = cloneRows(current.rows);
    rows[rowIndex].cells.push(createTableCell());
    commit(rows);
  }

  function deleteCell(rowIndex: number, cellIndex: number) {
    const rows = cloneRows(current.rows);
    rows[rowIndex].cells = rows[rowIndex].cells.filter((_, index) => index !== cellIndex);
    commit(rows);
  }

  return (
    <section className="rounded-2xl border border-violet-200 bg-violet-50/25 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-[var(--ink)]">结构化表格编辑</p>
          <p className="text-[10px] text-[var(--color-text-hint)]">支持单元格文本、表头、对齐和跨行跨列校正</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={layout.issues.length > 0}
            onClick={() => onChange({
              ...table,
              manual_verified: !Boolean(table.manual_verified),
              requires_review: Boolean(table.manual_verified),
              assignment_method: "manual_review",
            })}
          >
            {layout.issues.length > 0
              ? "先修复结构问题"
              : table.manual_verified
                ? "取消人工核验"
                : "标记人工已核验"}
          </Button>
          <Button type="button" variant="secondary" onClick={addRow}>新增行</Button>
          {onDelete ? <Button type="button" variant="secondary" onClick={onDelete}>删除表格</Button> : null}
        </div>
      </div>

      <label className="mb-3 block text-[11px] text-[var(--color-text-secondary)]">
        表题
        <input
          className="mt-1 w-full rounded-lg border border-[var(--color-border)] bg-white px-2 py-1.5 text-xs"
          value={table.caption}
          onChange={(event) => onChange({
            ...table,
            caption: event.target.value,
            manual_verified: false,
            requires_review: true,
            assignment_method: "manual_review",
          })}
        />
      </label>

      {layout.issues.length > 0 ? (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">{layout.issues.join("；")}</div>
      ) : null}

      <div className="space-y-3">
        {table.rows.map((row, rowIndex) => (
          <div key={rowIndex} className="rounded-xl border border-[var(--color-border)]/70 bg-white p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-semibold text-[var(--color-text-secondary)]">第 {rowIndex + 1} 行</span>
              <div className="flex gap-2">
                <button type="button" className="text-[10px] text-[var(--color-primary)]" onClick={() => addCell(rowIndex)}>新增单元格</button>
                {table.rows.length > 1 ? <button type="button" className="text-[10px] text-red-600" onClick={() => deleteRow(rowIndex)}>删除行</button> : null}
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {row.cells.map((cell, cellIndex) => (
                <div key={cellIndex} className="rounded-lg border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/35 p-2">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] text-[var(--color-text-hint)]">单元格 {cellIndex + 1}</span>
                    {row.cells.length > 1 ? <button type="button" className="text-[10px] text-red-500" onClick={() => deleteCell(rowIndex, cellIndex)}>删除</button> : null}
                  </div>
                  <textarea
                    className="min-h-20 w-full rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-xs"
                    value={cell.text}
                    onChange={(event) => updateCell(rowIndex, cellIndex, { text: event.target.value })}
                  />
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
                    <label>跨行<input type="number" min={1} max={100} className="ml-1 w-14 rounded border px-1 py-0.5" value={cell.row_span} onChange={(event) => updateCell(rowIndex, cellIndex, { row_span: Math.max(1, Number(event.target.value) || 1) })} /></label>
                    <label>跨列<input type="number" min={1} max={100} className="ml-1 w-14 rounded border px-1 py-0.5" value={cell.col_span} onChange={(event) => updateCell(rowIndex, cellIndex, { col_span: Math.max(1, Number(event.target.value) || 1) })} /></label>
                    <label className="flex items-center gap-1"><input type="checkbox" checked={cell.is_header} onChange={(event) => updateCell(rowIndex, cellIndex, { is_header: event.target.checked })} />表头</label>
                    <select className="rounded border bg-white px-1 py-0.5" value={cell.alignment} onChange={(event) => updateCell(rowIndex, cellIndex, { alignment: event.target.value as StructuredTableCell["alignment"] })}>
                      <option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option>
                    </select>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
