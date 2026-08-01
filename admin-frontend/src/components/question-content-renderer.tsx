"use client";

import { MathFormula } from "@/components/ui/math-formula";
import { StructuredTable } from "@/components/structured-table";
import { resolveAssetUrl } from "@/lib/asset-url";
import { isTableSegment } from "@/lib/structured-table";

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
  return String(record?.stem ?? record?.text ?? record?.question ?? record?.title ?? fallbackText ?? "");
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
    const type = String(segment.type ?? "").toLowerCase();

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

  if (!hasTextSegment && fallbackText.trim()) {
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
}: {
  content: unknown;
  fallbackText?: string;
  showTableMetadata?: boolean;
  skipOptionSegments?: boolean;
  ignoredSegmentIds?: string[];
}) {
  const record = asContentRecord(content);
  const segments = record && Array.isArray(record.segments) ? record.segments : [];
  const directText = contentText(content, fallbackText);
  const blocks = buildRenderBlocks(
    segments,
    directText,
    skipOptionSegments,
    new Set(ignoredSegmentIds),
  );

  if (blocks.length === 0) {
    return directText
      ? <MathFormula text={directText} />
      : <span className="italic text-[var(--color-text-hint)]">（空）</span>;
  }

  return (
    <div className="space-y-3">
      {blocks.map((block) => {
        if (block.kind === "text") {
          return block.text ? (
            <div key={block.key} className="whitespace-pre-wrap">
              <MathFormula text={block.text} />
            </div>
          ) : null;
        }

        const segment = block.segment;
        const type = String(segment.type ?? "").toLowerCase();
        if (isTableSegment(segment)) {
          return <StructuredTable key={block.key} segment={segment} showMetadata={showTableMetadata} />;
        }
        if (["image", "math_image", "table_image", "code_image"].includes(type)) {
          const url = resolveAssetUrl(String(segment.url ?? ""));
          if (!url) {
            const alt = String(segment.alt ?? "");
            return alt ? <p key={block.key} className="text-xs text-[var(--color-text-hint)]">{alt}</p> : null;
          }
          return (
            <figure key={block.key} className="overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-white p-2">
              <img
                src={url}
                alt={String(segment.alt ?? "题目图片")}
                className="max-h-[420px] max-w-full cursor-zoom-in object-contain"
                onClick={() => window.open(url, "_blank")}
              />
              {showTableMetadata && segment.requires_review ? (
                <figcaption className="mt-1 text-[10px] text-amber-700">该视觉片段需要人工核对</figcaption>
              ) : null}
            </figure>
          );
        }
        const text = String(segment.text ?? segment.alt ?? "");
        return text ? (
          <div key={block.key} className="whitespace-pre-wrap"><MathFormula text={text} /></div>
        ) : null;
      })}
    </div>
  );
}
