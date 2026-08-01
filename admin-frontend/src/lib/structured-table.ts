export type TableCellAlignment = "left" | "center" | "right";

export type TableContentSegment = {
  type?: string;
  text?: string;
  alt?: string;
  url?: string;
  display?: boolean;
  [key: string]: unknown;
};

export type StructuredTableCell = {
  text: string;
  content: TableContentSegment[];
  row_span: number;
  col_span: number;
  is_header: boolean;
  alignment: TableCellAlignment;
  bbox?: number[] | null;
  confidence: number;
};

export type StructuredTableRow = {
  cells: StructuredTableCell[];
};

export type StructuredTableSegment = {
  type: "table";
  schema_version: "table.v2";
  table_id?: string;
  caption: string;
  rows: StructuredTableRow[];
  row_count: number;
  column_count: number;
  has_header: boolean;
  source_format: string;
  source_page?: number;
  source_pages: number[];
  bbox?: number[] | null;
  coordinate_space?: string | null;
  region_id?: string | null;
  confidence: number;
  requires_review: boolean;
  signals: string[];
  markdown: string;
  source_text?: string;
  source_image_url?: string;
  fallback_image_url?: string;
  continuation?: Record<string, unknown>;
  option_key?: string;
  [key: string]: unknown;
};

export type TableLayoutCell = {
  row: number;
  column: number;
  cell: StructuredTableCell;
};

export type TableLayout = {
  columnCount: number;
  rowCount: number;
  anchors: TableLayoutCell[];
  issues: string[];
};

const MAX_ROWS = 500;
const MAX_COLUMNS = 100;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function positiveSpan(value: unknown): number {
  return Math.max(1, Math.min(MAX_COLUMNS, Math.floor(finiteNumber(value, 1))));
}

function confidenceValue(value: unknown, fallback = 1): number {
  return Math.max(0, Math.min(1, finiteNumber(value, fallback)));
}

function normalizeAlignment(value: unknown): TableCellAlignment {
  const text = String(value ?? "").toLowerCase();
  if (text.includes("center")) return "center";
  if (text.includes("right")) return "right";
  return "left";
}

function normalizeContent(value: unknown, fallbackText: string): TableContentSegment[] {
  if (!Array.isArray(value)) {
    return [{ type: "text", text: fallbackText }];
  }
  const normalized = value
    .filter((item) => item && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({ ...(item as Record<string, unknown>) }) as TableContentSegment);
  return normalized.length > 0 ? normalized : [{ type: "text", text: fallbackText }];
}

export function tableContentToText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => {
      const block = asRecord(item);
      if (!block) return "";
      if (String(block.type ?? "").toLowerCase() === "newline") return "\n";
      return String(block.text ?? block.alt ?? "");
    })
    .join("")
    .trim();
}

export function createTableCell(text = ""): StructuredTableCell {
  return {
    text,
    content: [{ type: "text", text }],
    row_span: 1,
    col_span: 1,
    is_header: false,
    alignment: "left",
    confidence: 1,
  };
}

function normalizeCell(value: unknown): StructuredTableCell {
  const record = asRecord(value);
  if (!record) return createTableCell(String(value ?? ""));
  const rawText = String(record.text ?? tableContentToText(record.content) ?? "");
  const content = normalizeContent(record.content, rawText);
  return {
    text: rawText || tableContentToText(content),
    content,
    row_span: positiveSpan(record.row_span ?? record.rowspan),
    col_span: positiveSpan(record.col_span ?? record.colspan),
    is_header: Boolean(record.is_header),
    alignment: normalizeAlignment(record.alignment ?? record.align),
    bbox: Array.isArray(record.bbox) ? record.bbox.map((item) => finiteNumber(item, 0)) : null,
    confidence: confidenceValue(record.confidence, 1),
  };
}

function splitMarkdownRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|") && !value.endsWith("\\|")) value = value.slice(0, -1);
  const result: string[] = [];
  let current = "";
  let escaped = false;
  for (const char of value) {
    if (escaped) {
      current += char;
      escaped = false;
    } else if (char === "\\") {
      escaped = true;
    } else if (char === "|") {
      result.push(current.replace(/<br\s*\/?\s*>/gi, "\n").trim());
      current = "";
    } else {
      current += char;
    }
  }
  result.push(current.replace(/<br\s*\/?\s*>/gi, "\n").trim());
  return result;
}

function parseLegacyMarkdown(source: string): StructuredTableRow[] {
  const lines = String(source ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return [];
  const separatorIndex = lines.findIndex((line) => /^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(line));
  const headerIndex = separatorIndex > 0 ? separatorIndex - 1 : -1;
  return lines
    .filter((_, index) => index !== separatorIndex)
    .map((line, index) => ({
      cells: splitMarkdownRow(line).map((text) => ({
        ...createTableCell(text),
        is_header: headerIndex >= 0 && index === headerIndex,
      })),
    }));
}

function hashString(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function escapeMarkdown(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/\|/g, "\\|").replace(/\n/g, "<br>");
}

export function tableRowsToMarkdown(rows: StructuredTableRow[]): string {
  if (rows.length === 0) return "";
  const matrix = tableToMatrix(rows);
  if (matrix.length === 0 || matrix[0].length === 0) return "";
  const headerRow = rows.findIndex((row) => row.cells.some((cell) => cell.is_header));
  const effectiveHeader = headerRow >= 0 ? headerRow : 0;
  const output: string[] = [];
  matrix.forEach((row, index) => {
    output.push(`| ${row.map((value) => escapeMarkdown(value)).join(" | ")} |`);
    if (index === effectiveHeader) {
      output.push(`| ${row.map(() => "---").join(" | ")} |`);
    }
  });
  return output.join("\n");
}

export function buildTableLayout(rows: StructuredTableRow[]): TableLayout {
  const anchors: TableLayoutCell[] = [];
  const occupied = new Set<string>();
  const issues: string[] = [];
  let columnCount = 0;

  rows.slice(0, MAX_ROWS).forEach((row, rowIndex) => {
    let column = 0;
    row.cells.forEach((cell, cellIndex) => {
      while (occupied.has(`${rowIndex}:${column}`) && column < MAX_COLUMNS) column += 1;
      if (column >= MAX_COLUMNS) {
        issues.push(`第 ${rowIndex + 1} 行第 ${cellIndex + 1} 个单元格超出最大列数`);
        return;
      }
      const rowSpan = Math.min(cell.row_span, Math.max(1, rows.length - rowIndex));
      const colSpan = Math.min(cell.col_span, Math.max(1, MAX_COLUMNS - column));
      if (rowSpan !== cell.row_span) issues.push(`第 ${rowIndex + 1} 行存在越界行合并`);
      if (colSpan !== cell.col_span) issues.push(`第 ${rowIndex + 1} 行存在越界列合并`);
      for (let rr = rowIndex; rr < rowIndex + rowSpan; rr += 1) {
        for (let cc = column; cc < column + colSpan; cc += 1) {
          const key = `${rr}:${cc}`;
          if (occupied.has(key)) issues.push(`单元格在第 ${rr + 1} 行第 ${cc + 1} 列发生重叠`);
          occupied.add(key);
        }
      }
      anchors.push({ row: rowIndex, column, cell: { ...cell, row_span: rowSpan, col_span: colSpan } });
      column += colSpan;
      columnCount = Math.max(columnCount, column);
    });
  });

  if (rows.length === 0) issues.push("表格没有数据行");
  if (columnCount < 1) issues.push("表格没有有效列");
  return { columnCount, rowCount: rows.length, anchors, issues: Array.from(new Set(issues)) };
}

export function tableToMatrix(rows: StructuredTableRow[]): string[][] {
  const layout = buildTableLayout(rows);
  const matrix = Array.from({ length: layout.rowCount }, () => Array.from({ length: layout.columnCount }, () => ""));
  layout.anchors.forEach(({ row, column, cell }) => {
    matrix[row][column] = cell.text || tableContentToText(cell.content);
  });
  return matrix;
}

export function normalizeStructuredTableSegment(value: unknown): StructuredTableSegment | null {
  const record = asRecord(value);
  if (!record) return null;
  const type = String(record.type ?? "").toLowerCase();
  let rows: StructuredTableRow[] = [];
  if (type === "table" && Array.isArray(record.rows)) {
    rows = record.rows.slice(0, MAX_ROWS).map((rowValue) => {
      const rowRecord = asRecord(rowValue);
      const cells = Array.isArray(rowRecord?.cells)
        ? rowRecord!.cells.map(normalizeCell)
        : Array.isArray(rowValue)
          ? rowValue.map(normalizeCell)
          : [];
      return { cells };
    });
  } else if (type === "table_markdown" || typeof record.markdown === "string") {
    rows = parseLegacyMarkdown(String(record.markdown ?? record.text ?? record.content ?? ""));
  } else {
    return null;
  }
  if (rows.length === 0) return null;

  const layout = buildTableLayout(rows);
  const confidence = confidenceValue(record.confidence, type === "table" ? 1 : 0.7);
  const signals = Array.isArray(record.signals) ? record.signals.map(String) : [];
  const manuallyVerified = Boolean(record.manual_verified);
  const requiresReview = layout.issues.length > 0 || (!manuallyVerified && (Boolean(record.requires_review) || confidence < 0.65));
  const sourcePages = Array.isArray(record.source_pages)
    ? record.source_pages.map((page) => Math.floor(finiteNumber(page, 0))).filter((page) => page > 0)
    : [];
  const sourcePage = Math.floor(finiteNumber(record.source_page, sourcePages[0] ?? 0));
  if (sourcePage > 0 && !sourcePages.includes(sourcePage)) sourcePages.unshift(sourcePage);
  const markdown = tableRowsToMarkdown(rows);
  const fingerprint = JSON.stringify({ rows, sourcePages, region: record.region_id ?? null });

  return {
    ...record,
    type: "table",
    schema_version: "table.v2",
    table_id: String(record.table_id ?? `tbl_frontend_${hashString(fingerprint)}`),
    caption: String(record.caption ?? ""),
    rows,
    row_count: rows.length,
    column_count: layout.columnCount,
    has_header: rows.some((row) => row.cells.some((cell) => cell.is_header)),
    source_format: String(record.source_format ?? (type === "table_markdown" ? "legacy_markdown" : "structured")),
    source_page: sourcePage || undefined,
    source_pages: Array.from(new Set(sourcePages)).sort((a, b) => a - b),
    confidence,
    requires_review: requiresReview,
    signals: Array.from(new Set([...signals, ...layout.issues])),
    markdown,
    source_image_url: typeof record.source_image_url === "string" ? record.source_image_url : undefined,
    fallback_image_url: typeof record.fallback_image_url === "string" ? record.fallback_image_url : undefined,
  } as StructuredTableSegment;
}

export function updateStructuredTableRows(
  segment: StructuredTableSegment,
  rows: StructuredTableRow[],
): StructuredTableSegment {
  const normalized = normalizeStructuredTableSegment({
    ...segment,
    rows,
    manual_verified: false,
    requires_review: true,
    assignment_method: "manual_review",
  });
  return normalized ?? segment;
}

export function isTableSegment(value: unknown): boolean {
  const record = asRecord(value);
  if (!record) return false;
  const type = String(record.type ?? "").toLowerCase();
  return type === "table" || type === "table_markdown";
}

export function getTableSegments(content: unknown): StructuredTableSegment[] {
  const record = asRecord(content);
  if (!record || !Array.isArray(record.segments)) return [];
  return record.segments
    .map(normalizeStructuredTableSegment)
    .filter((table): table is StructuredTableSegment => Boolean(table));
}
