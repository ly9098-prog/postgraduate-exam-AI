"use client";

import { MathFormula } from "@/components/ui/math-formula";
import { resolveAssetUrl } from "@/lib/asset-url";
import {
  buildTableLayout,
  normalizeStructuredTableSegment,
  tableContentToText,
  type StructuredTableCell,
  type StructuredTableSegment,
} from "@/lib/structured-table";

function CellContent({ cell }: { cell: StructuredTableCell }) {
  const blocks = Array.isArray(cell.content) ? cell.content : [];
  if (blocks.length <= 1 && !blocks.some((block) => block.type === "image" || block.type === "math_image")) {
    return <MathFormula text={cell.text || tableContentToText(blocks)} />;
  }
  return (
    <div className="space-y-1.5">
      {blocks.map((block, index) => {
        const type = String(block.type ?? "text").toLowerCase();
        if (type === "newline") return <div key={index} className="h-1" />;
        if (["image", "math_image", "code_image", "table_image"].includes(type) && block.url) {
          const url = resolveAssetUrl(String(block.url));
          return url ? (
            <img
              key={index}
              src={url}
              alt={String(block.alt ?? "表格单元格图片")}
              className="max-h-40 max-w-full rounded border border-[var(--color-border)]/50 object-contain"
            />
          ) : null;
        }
        const text = String(block.text ?? block.alt ?? "");
        return text ? <MathFormula key={index} text={text} /> : null;
      })}
    </div>
  );
}

export function StructuredTable({
  segment,
  compact = false,
  showMetadata = true,
}: {
  segment: unknown;
  compact?: boolean;
  showMetadata?: boolean;
}) {
  const table = normalizeStructuredTableSegment(segment);
  if (!table) return null;
  const layout = buildTableLayout(table.rows);
  const pageLabel = table.source_pages.length > 0
    ? table.source_pages.length === 1
      ? `第 ${table.source_pages[0]} 页`
      : `第 ${table.source_pages[0]}–${table.source_pages[table.source_pages.length - 1]} 页`
    : null;
  const sourceImageUrl = resolveAssetUrl(table.source_image_url || table.fallback_image_url);

  return (
    <figure className={`overflow-hidden rounded-xl border bg-white ${table.requires_review ? "border-amber-300" : "border-[var(--color-border)]/70"}`}>
      {(table.caption || showMetadata) ? (
        <figcaption className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/45 px-3 py-2">
          <span className="text-xs font-semibold text-[var(--ink)]">{table.caption || "结构化表格"}</span>
          {table.requires_review ? <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700">需核对</span> : null}
          {showMetadata ? (
            <>
              <span className="text-[10px] text-[var(--color-text-hint)]">{table.row_count} 行 × {table.column_count} 列</span>
              <span className="text-[10px] text-[var(--color-text-hint)]">置信度 {(table.confidence * 100).toFixed(0)}%</span>
              {pageLabel ? <span className="text-[10px] text-[var(--color-text-hint)]">{pageLabel}</span> : null}
              {table.source_format ? <span className="text-[10px] text-[var(--color-text-hint)]">{table.source_format}</span> : null}
            </>
          ) : null}
        </figcaption>
      ) : null}
      <div className="max-w-full overflow-x-auto">
        <table className={`w-full border-collapse ${compact ? "text-xs" : "text-sm"}`}>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.cells.map((cell, cellIndex) => {
                  const Tag = cell.is_header ? "th" : "td";
                  return (
                    <Tag
                      key={`${rowIndex}-${cellIndex}`}
                      rowSpan={cell.row_span}
                      colSpan={cell.col_span}
                      className={`${compact ? "px-2 py-1.5" : "px-3 py-2.5"} min-w-24 border border-[var(--color-border)]/70 align-top leading-6 text-[var(--color-text-secondary)] ${cell.is_header ? "bg-[var(--color-primary-light)]/35 font-semibold text-[var(--ink)]" : "bg-white"}`}
                      style={{ textAlign: cell.alignment }}
                    >
                      <CellContent cell={cell} />
                    </Tag>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {layout.issues.length > 0 ? (
        <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          {layout.issues.join("；")}
        </div>
      ) : null}
      {table.requires_review && sourceImageUrl ? (
        <details className="border-t border-[var(--color-border)]/60 px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-medium text-[var(--color-text-secondary)]">查看原始表格截图</summary>
          <img
            src={sourceImageUrl}
            alt="原始表格截图"
            className="mt-2 max-h-80 max-w-full rounded-lg border border-[var(--color-border)] object-contain"
          />
        </details>
      ) : null}
    </figure>
  );
}

export function StructuredTableList({ segments }: { segments: unknown[] }) {
  const tables = segments
    .map(normalizeStructuredTableSegment)
    .filter((table): table is StructuredTableSegment => Boolean(table));
  if (tables.length === 0) return null;
  return <div className="space-y-3">{tables.map((table, index) => <StructuredTable key={table.table_id || index} segment={table} />)}</div>;
}
