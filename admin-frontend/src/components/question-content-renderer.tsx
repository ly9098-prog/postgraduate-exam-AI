"use client";

import { MathFormula } from "@/components/ui/math-formula";
import { StructuredTable } from "@/components/structured-table";
import { resolveAssetUrl } from "@/lib/asset-url";
import { isTableSegment } from "@/lib/structured-table";
import { looksLikeProgrammingCode } from "@/lib/math-text";

type SegmentRecord = Record<string, unknown>;
type RenderBlock =
  | { kind: "text"; text: string; key: string }
  | { kind: "segment"; segment: SegmentRecord; key: string };

function asContentRecord(content: unknown): Record<string, unknown> | null {
  return content && typeof content === "object" && !Array.isArray(content)
    ? (content as Record<string, unknown>)
    : null;
}

function contentText(content: unknown, fallbackText: string): string {
  if (typeof content === "string") return content;
  const record = asContentRecord(content);
  if (record) {
    const candidate = [record.stem, record.text, record.question, record.title]
      .find((value) => typeof value === "string" && value.length > 0);
    if (typeof candidate === "string") return candidate;
  }
  return String(fallbackText ?? "");
}


function splitProgrammingText(value: string): { prose: string; code: string } {
  const text = String(value ?? "").replace(/\r\n?/g, "\n").trim();
  if (!text) return { prose: "", code: "" };

  const codeStartPatterns = [
    /#\s*(?:include|define|if|ifdef|ifndef)\b/m,
    /(?:const\s+)?(?:(?:unsigned|signed)\s+)?(?:void|int|char|short|long|float|double|bool|auto)\s+[A-Za-z_]\w*\s*(?:\([^)]*\)|(?=[=;,\[]))/m,
    /\b(?:for|while|switch|if)\s*\(/m,
    /\b(?:return|printf|scanf|cout|cin)\b/m,
  ];

  let start = -1;
  for (const pattern of codeStartPatterns) {
    const match = pattern.exec(text);
    if (match && (start < 0 || match.index < start)) start = match.index;
  }

  if (start < 0) return { prose: "", code: text };
  return {
    prose: text.slice(0, start).trimEnd(),
    code: text.slice(start).trim(),
  };
}

/**
 * Reconstruct readable C/C++-style line breaks when imported stem text has
 * been flattened into one line. The formatter only breaks at braces and
 * statement semicolons outside parentheses, so `for (;;)` stays intact.
 */
function formatProgrammingCode(value: string, supportingText = ""): string {
  let source = String(value ?? "").replace(/\r\n?/g, "\n").trim();
  if (!source) return "";

  // Some legacy records lost a closing brace in content.stem while the OCR
  // segment stream still contains it. Only restore that delimiter when the
  // segment text proves it existed, and place it at the common boundary
  // between a function's return statement and following top-level statements.
  const sourceClosingBraces = (source.match(/}/g) ?? []).length;
  const supportingClosingBraces = (supportingText.match(/}/g) ?? []).length;
  if (supportingClosingBraces > sourceClosingBraces) {
    source = source.replace(
      /^(.*?\{[\s\S]*?\breturn\b[\s\S]*?;)\s*((?:(?:const\s+)?(?:(?:unsigned|signed)\s+)?(?:int|char|short|long|float|double|bool|auto)\s+[A-Za-z_]\w*\s*;)[\s\S]*)$/,
      "$1 } $2",
    );
  }

  const lines: string[] = [];
  let buffer = "";
  let indent = 0;
  let parenDepth = 0;
  let quote: '"' | "'" | null = null;
  let escaped = false;

  const emit = (forcedIndent?: number) => {
    const text = buffer.trim();
    buffer = "";
    if (!text) return;
    const level = Math.max(0, forcedIndent ?? indent);
    lines.push(`${"  ".repeat(level)}${text}`);
  };

  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];

    if (quote) {
      buffer += char;
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === quote) {
        quote = null;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      buffer += char;
      continue;
    }

    if (char === "(") {
      parenDepth += 1;
      buffer += char;
      continue;
    }
    if (char === ")") {
      parenDepth = Math.max(0, parenDepth - 1);
      buffer += char;
      continue;
    }

    if (char === "{") {
      buffer = `${buffer.trimEnd()} {`;
      emit();
      indent += 1;
      continue;
    }

    if (char === "}") {
      emit();
      indent = Math.max(0, indent - 1);
      let cursor = index + 1;
      while (cursor < source.length && /[ \t]/.test(source[cursor])) cursor += 1;
      if (source[cursor] === ";") {
        lines.push(`${"  ".repeat(indent)}};`);
        index = cursor;
      } else {
        lines.push(`${"  ".repeat(indent)}}`);
      }
      continue;
    }

    if (char === ";" && parenDepth === 0) {
      buffer = `${buffer.trimEnd()};`;
      emit();
      continue;
    }

    if (char === "\n") {
      emit();
      continue;
    }

    // Collapse layout-only whitespace without altering punctuation or strings.
    if (/\s/.test(char)) {
      if (buffer && !/\s$/.test(buffer)) buffer += " ";
      continue;
    }

    buffer += char;
  }

  emit();
  return lines.join("\n");
}

function ProgrammingStem({ text, supportingText = "" }: { text: string; supportingText?: string }) {
  const { prose, code } = splitProgrammingText(text);
  const formattedCode = formatProgrammingCode(code, supportingText);

  return (
    <div className="min-w-0 space-y-3">
      {prose ? <div className="whitespace-pre-wrap">{prose}</div> : null}
      {formattedCode ? (
        <pre className="max-w-full overflow-x-auto rounded-lg border border-slate-200 bg-white px-3 py-2.5 font-mono text-[0.92em] leading-7 text-slate-800 [tab-size:2]">
          <code>{formattedCode}</code>
        </pre>
      ) : null}
    </div>
  );
}

function stableSegmentId(segment: SegmentRecord, index: number): string {
  const regionId = String(segment.region_id ?? "").trim();
  if (regionId) return regionId;
  const assetHash = String(segment.asset_hash ?? "").trim();
  if (assetHash) return `ah:${assetHash}`;
  const type = String(segment.type ?? "");
  const url = String(segment.url ?? "");
  const bbox = Array.isArray(segment.bbox) ? JSON.stringify(segment.bbox) : "";
  const fingerprint = `${type}|${url}|${bbox}`;
  if (fingerprint.length > 3) {
    let hash = 0;
    for (let offset = 0; offset < fingerprint.length; offset += 1) {
      hash = ((hash << 5) - hash + fingerprint.charCodeAt(offset)) | 0;
    }
    return `fp:${(hash >>> 0).toString(36)}`;
  }
  return `idx:${index}`;
}

function normalizeComparableText(value: unknown): string {
  return String(value ?? "").replace(/\r\n?/g, "\n").trim();
}

function fallbackIsRepresentedByCodeSegment(segments: unknown[], fallbackText: string): boolean {
  const normalizedFallback = normalizeComparableText(fallbackText);
  if (!normalizedFallback) return false;
  return segments.some((rawSegment) => {
    if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return false;
    const segment = rawSegment as SegmentRecord;
    if (String(segment.type ?? "").trim().toLowerCase() !== "code") return false;
    const code = normalizeComparableText(segment.code ?? segment.text ?? "");
    const caption = normalizeComparableText(segment.caption ?? "");
    return normalizedFallback === code || normalizedFallback === normalizeComparableText(caption && code ? `${caption}\n${code}` : (caption || code));
  });
}

function buildRenderBlocks(
  segments: unknown[],
  fallbackText: string,
  skipOptionSegments: boolean,
  ignoredSegmentIds: Set<string>,
): RenderBlock[] {
  const blocks: RenderBlock[] = [];
  let textBuffer = "";
  let textStart = 0;
  let hasTextSegment = false;
  const visibleSegments: SegmentRecord[] = [];

  const flushText = () => {
    if (!textBuffer) return;
    blocks.push({ kind: "text", text: textBuffer, key: `text-${textStart}-${blocks.length}` });
    textBuffer = "";
  };

  segments.forEach((rawSegment, index) => {
    if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return;
    const segment = rawSegment as SegmentRecord;
    if (ignoredSegmentIds.has(stableSegmentId(segment, index))) return;
    if (skipOptionSegments && segment.option_key) return;
    visibleSegments.push(segment);
    const type = String(segment.type ?? "").trim().toLowerCase();

    if (type === "text") {
      if (!textBuffer) textStart = index;
      textBuffer += String(segment.text ?? "");
      hasTextSegment = true;
      return;
    }
    if (type === "newline") {
      if (!textBuffer) textStart = index;
      textBuffer += "\n";
      hasTextSegment = true;
      return;
    }

    flushText();
    blocks.push({
      kind: "segment",
      segment,
      key: String(segment.table_id ?? segment.region_id ?? segment.asset_hash ?? `segment-${index}`),
    });
  });
  flushText();

  if (!hasTextSegment && fallbackText.trim() && !fallbackIsRepresentedByCodeSegment(visibleSegments, fallbackText)) {
    blocks.unshift({ kind: "text", text: fallbackText, key: "fallback-stem" });
  }
  return blocks;
}

export function QuestionContentRenderer({
  content,
  fallbackText = "",
  showTableMetadata = false,
  skipOptionSegments = true,
  ignoredSegmentIds = [],
  preserveCodeText = false,
}: {
  content: unknown;
  fallbackText?: string;
  showTableMetadata?: boolean;
  skipOptionSegments?: boolean;
  ignoredSegmentIds?: string[];
  preserveCodeText?: boolean;
}) {
  const record = asContentRecord(content);
  const segments = record && Array.isArray(record.segments) ? record.segments : [];
  const canonicalText = contentText(content, "");
  const directText = canonicalText || fallbackText;
  const ignoredIds = new Set(ignoredSegmentIds);
  const renderStemAsCode = preserveCodeText && looksLikeProgrammingCode(directText);

  // For text-only programming questions, the canonical stem is authoritative.
  // OCR/import text segments may be stored in region order instead of reading
  // order; rendering those segments is what caused code lines on /questions to
  // jump around.  When no stem visual/table segment needs interleaving, render
  // the canonical stem directly and keep the code out of the math renderer.
  const visibleStemSegments = segments.filter((rawSegment, index) => {
    if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return false;
    const segment = rawSegment as SegmentRecord;
    if (ignoredIds.has(stableSegmentId(segment, index))) return false;
    if (skipOptionSegments && segment.option_key) return false;
    return true;
  });
  const hasOnlyTextStemSegments =
    visibleStemSegments.length > 0 &&
    visibleStemSegments.every((segment) => {
      const type = String((segment as SegmentRecord).type ?? "").trim().toLowerCase();
      return type === "text" || type === "newline";
    });
  const supportingSegmentText = visibleStemSegments
    .map((segment) => {
      const record = segment as SegmentRecord;
      return String(record.type ?? "").trim().toLowerCase() === "newline"
        ? "\n"
        : String(record.text ?? "");
    })
    .join("");

  if (canonicalText && hasOnlyTextStemSegments && renderStemAsCode) {
    return <ProgrammingStem text={canonicalText} supportingText={supportingSegmentText} />;
  }

  const blocks = buildRenderBlocks(
    segments,
    directText,
    skipOptionSegments,
    ignoredIds,
  );

  if (blocks.length === 0) {
    return directText
      ? (renderStemAsCode
          ? <ProgrammingStem text={directText} />
          : <MathFormula text={directText} />)
      : <span className="italic text-[var(--color-text-hint)]">（空）</span>;
  }

  return (
    <div className="space-y-3">
      {blocks.map((block) => {
        if (block.kind === "text") {
          return block.text ? (
            <div key={block.key} className="whitespace-pre-wrap">
              {renderStemAsCode ? <ProgrammingStem text={block.text} /> : <MathFormula text={block.text} />}
            </div>
          ) : null;
        }

        const segment = block.segment;
        const type = String(segment.type ?? "").trim().toLowerCase();
        if (isTableSegment(segment)) {
          return <StructuredTable key={block.key} segment={segment} showMetadata={showTableMetadata} />;
        }
        if (type === "code") {
          const code = String(segment.code ?? segment.text ?? "");
          // `alt` is alternative/accessibility metadata imported with the code
          // region. It is not user-facing stem content. Only an explicit
          // `caption` may be rendered as a visible code-block title.
          const caption = String(segment.caption ?? "").trim();
          const language = String(segment.language ?? "").trim();
          return (
            <figure
              key={block.key}
              className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/70"
            >
              {caption || language ? (
                <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 text-xs text-slate-500">
                  {caption ? <span className="min-w-0 break-words">{caption}</span> : <span />}
                  {language ? (
                    <span className="shrink-0 rounded bg-white px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-slate-400">
                      {language}
                    </span>
                  ) : null}
                </figcaption>
              ) : null}
              {code ? (
                <pre className="max-w-full overflow-x-auto px-3 py-3 font-mono text-[0.92em] leading-7 text-slate-800 [tab-size:2]">
                  <code>{code}</code>
                </pre>
              ) : (
                <div className="px-3 py-3 text-xs text-amber-700">代码块内容为空</div>
              )}
            </figure>
          );
        }
        if (["image", "math_image", "table_image", "code_image"].includes(type)) {
          const url = resolveAssetUrl(String(segment.url ?? ""));
          if (!url) {
            const alt = String(segment.alt ?? "");
            return alt ? <p key={block.key} className="text-xs text-[var(--color-text-hint)]">{alt}</p> : null;
          }
          return (
            <figure key={block.key} className="overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-white p-2">
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block max-w-full rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-300"
                aria-label="在新窗口查看题目图片"
              >
                <img
                  src={url}
                  alt={String(segment.alt ?? "题目图片")}
                  className="max-h-[420px] max-w-full cursor-zoom-in object-contain"
                />
              </a>
              {showTableMetadata && segment.requires_review ? (
                <figcaption className="mt-1 text-[10px] text-amber-700">该视觉片段需要人工核对</figcaption>
              ) : null}
            </figure>
          );
        }
        // Unknown segment metadata must stay non-visible. `alt` is import /
        // accessibility metadata, not generic stem content.
        const text = String(segment.text ?? "");
        return text ? (
          <div key={block.key} className="whitespace-pre-wrap"><MathFormula text={text} /></div>
        ) : null;
      })}
    </div>
  );
}
