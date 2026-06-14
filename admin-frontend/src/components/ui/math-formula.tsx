/**
 * Renders common imported math notation without adding KaTeX/MathJax.
 */

import type { ReactNode } from "react";

interface Segment {
  type: "text" | "inline-math" | "block-math";
  value: string;
}

const subscript: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "-": "₋", a: "ₐ", e: "ₑ", h: "ₕ", i: "ᵢ", j: "ⱼ", k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ", p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ", u: "ᵤ", v: "ᵥ", x: "ₓ",
};

const superscript: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", n: "ⁿ",
};

function toScript(value: string, map: Record<string, string>) {
  return value.split("").map((ch) => map[ch] ?? ch).join("");
}

function formatMathText(text: string) {
  return text
    .replace(/\*\*([^*]+?)\*\*/g, "$1")
    .replace(/\\\(([\s\S]*?)\\\)/g, "$1")
    .replace(/\\\[([\s\S]*?)\\\]/g, "$1")
    .replace(/\$\$([\s\S]*?)\$\$/g, "$1")
    .replace(/\$([^$\n]+?)\$/g, "$1")
    .replace(/\\{1,}(leq|le)/g, "≤")
    .replace(/\\{1,}(geq|ge)/g, "≥")
    .replace(/\\{1,}neq/g, "≠")
    .replace(/\\{1,}times/g, "×")
    .replace(/\\{1,}div/g, "÷")
    .replace(/\\{1,}cdot/g, "·")
    .replace(/\\{1,}pm/g, "±")
    .replace(/\\{1,}to/g, "→")
    .replace(/\\{1,}lt/g, "<")
    .replace(/\\{1,}gt/g, ">")
    .replace(/\\{1,}(log|ln|sin|cos|tan)/g, "$1")
    .replace(/_\{([0-9A-Za-z+-]+)\}/g, (_, sub: string) => toScript(sub, subscript))
    .replace(/\^\{([0-9A-Za-z+-]+)\}/g, (_, sup: string) => toScript(sup, superscript))
    .replace(/(log|ln|sin|cos|tan)_([0-9]+)/g, (_, name: string, sub: string) => `${name}${toScript(sub, subscript)}`)
    .replace(/([A-Za-z0-9)])_([0-9A-Za-z])/g, (_, base: string, sub: string) => `${base}${toScript(sub, subscript)}`)
    .replace(/([A-Za-z0-9)])\^([0-9A-Za-z])/g, (_, base: string, sup: string) => `${base}${toScript(sup, superscript)}`)
    .replace(/([A-Za-z0-9)])\s*(=|\+|×|÷|≤|≥|≠|→)\s*/g, "$1 $2 ")
    .replace(/\s*(-)\s*/g, " − ")
    .replace(/(?<![*/])\s*([*/])\s*(?![*/])/g, " $1 ")
    .replace(/([A-Za-z0-9)])(log[₀-₉₊₋]+)/g, "$1 $2")
    .replace(/(log[₀-₉₊₋]+)([A-Za-z])/g, "$1 $2")
    .replace(/[ \t]+/g, " ")
    .replace(/\s+([，。！？；：,.!?;:)])/g, "$1")
    .replace(/([(])\s+/g, "$1")
    .trim();
}

function parseMath(text: string): Segment[] {
  const segments: Segment[] = [];
  const pattern = /(\$\$[\s\S]*?\$\$|\$(?:[^$\n]+?)\$)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    const raw = match[1];
    if (raw.startsWith("$$") && raw.endsWith("$$")) {
      segments.push({ type: "block-math", value: raw.slice(2, -2).trim() });
    } else {
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
    const value = formatMathText(seg.value);
    if (seg.type === "text") {
      return <span key={i}>{value}</span>;
    }
    if (seg.type === "inline-math") {
      return <strong key={i} className="font-semibold text-[var(--ink)]">{value}</strong>;
    }
    return (
      <div key={i} className="my-2 whitespace-normal break-words font-semibold leading-relaxed text-[var(--ink)]">
        {value}
      </div>
    );
  });
}

export function MathFormula({ text, className = "" }: { text: string; className?: string }) {
  const segments = parseMath(text);
  const formatted = formatMathText(text);
  const hasMath = segments.some((s) => s.type !== "text");

  if (!hasMath) {
    return <span className={className}>{formatted}</span>;
  }

  return <span className={className}>{renderSegments(segments)}</span>;
}
