"use client";

import { Fragment, useMemo } from "react";
import { LatexRenderer } from "./latex-renderer";
import { normalizeFormulaText } from "@/lib/formula-normalize";

type MixedLatexRendererProps = {
  text: string;
  className?: string;
};

/**
 * Renders text that mixes plain text with LaTeX math.
 *
 * Design principle: one canonical normaliser.
 * `normalizeFormulaText` (from `@/lib/formula-normalize`) is the sole source of
 * math detection and LaTeX conversion. This component only splits the normalised
 * output by standard delimiters and delegates rendering to LatexRenderer.
 *
 * Supports: \(…\), \[…\], $$…$$, $…$.
 */
export function MixedLatexRenderer({ text, className = "" }: MixedLatexRendererProps) {
  const segments = useMemo(() => {
    if (!text) return [];

    // Normalise non-standard math to \(…\) delimiters (preserves existing ones).
    const normalized = normalizeFormulaText(text) ?? text;

    const parts: Array<{ type: "plain" | "math"; value: string; displayMode: boolean }> = [];
    const delimRe = /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^$]+?\$)/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = delimRe.exec(normalized)) !== null) {
      if (match.index > lastIndex) {
        parts.push({ type: "plain", value: normalized.slice(lastIndex, match.index), displayMode: false });
      }
      const raw = match[1];
      parts.push({ type: "math", value: raw, displayMode: raw.startsWith("$$") || raw.startsWith("\\[") });
      lastIndex = match.index + raw.length;
    }
    if (lastIndex < normalized.length) {
      parts.push({ type: "plain", value: normalized.slice(lastIndex), displayMode: false });
    }

    return parts;
  }, [text]);

  if (!segments.length) return null;

  return (
    <span className={className}>
      {segments.map((seg, i) =>
        seg.type === "math" ? (
          <LatexRenderer key={i} latex={seg.value} displayMode={seg.displayMode} />
        ) : (
          <Fragment key={i}>{seg.value}</Fragment>
        )
      )}
    </span>
  );
}
