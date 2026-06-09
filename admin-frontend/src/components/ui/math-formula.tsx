/**
 * Renders question stem text with $...$ (inline) and $$...$$ (block) math
 * patterns highlighted with distinct styling.
 *
 * Uses a simple regex parser — no KaTeX/MathJax dependency needed for admin UI.
 */

import type { ReactNode } from "react";

interface Segment {
  type: "text" | "inline-math" | "block-math";
  value: string;
}

function parseMath(text: string): Segment[] {
  const segments: Segment[] = [];
  // Block math $$...$$ must be matched before inline $...$
  const pattern = /(\$\$[\s\S]*?\$\$|\$(?:[^$\n]+?)\$)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    // Text before this match
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    const raw = match[1];
    if (raw.startsWith("$$") && raw.endsWith("$$")) {
      segments.push({ type: "block-math", value: raw.slice(2, -2).trim() });
    } else {
      // Ensure it ends with $ (should always per pattern)
      segments.push({ type: "inline-math", value: raw.endsWith("$") ? raw.slice(1, -1) : raw.slice(1) });
    }
    lastIndex = match.index + raw.length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }

  return segments;
}

function renderSegments(segments: Segment[]): ReactNode[] {
  return segments.map((seg, i) => {
    if (seg.type === "text") {
      return <span key={i}>{seg.value}</span>;
    }
    if (seg.type === "inline-math") {
      return <strong key={i} className="font-bold text-[var(--ink)]">{seg.value}</strong>;
    }
    // block-math
    return (
      <div key={i} className="my-2 font-bold text-[var(--ink)]">
        {seg.value}
      </div>
    );
  });
}

export function MathFormula({ text, className = "" }: { text: string; className?: string }) {
  const segments = parseMath(text);
  const hasMath = segments.some((s) => s.type !== "text");

  if (!hasMath) {
    return <span className={className}>{text}</span>;
  }

  return <span className={className}>{renderSegments(segments)}</span>;
}
