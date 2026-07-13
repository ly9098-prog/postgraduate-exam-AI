"use client";

import { Fragment, useMemo } from "react";
import { LatexRenderer } from "./latex-renderer";

type MixedLatexRendererProps = {
  text: string;
  className?: string;
};

/* ── Unicode math symbols → LaTeX commands ── */
const UNI_TO_LATEX: Record<string, string> = {
  "→": "\\to",
  "∞": "\\infty",
  "×": "\\times",
  "÷": "\\div",
  "≥": "\\ge",
  "≤": "\\le",
  "≠": "\\ne",
  "±": "\\pm",
  "∑": "\\sum",
  "∫": "\\int",
  "∂": "\\partial",
  "Δ": "\\Delta",
  "π": "\\pi",
  "α": "\\alpha",
  "β": "\\beta",
  "γ": "\\gamma",
  "θ": "\\theta",
  "λ": "\\lambda",
  "μ": "\\mu",
  "σ": "\\sigma",
  "φ": "\\phi",
  "ω": "\\omega",
};

/* ── Math function names that should be \prefixed ── */
const MATH_FUNCS = [
  "lim",
  "sin",
  "cos",
  "tan",
  "cot",
  "sec",
  "csc",
  "arcsin",
  "arccos",
  "arctan",
  "log",
  "ln",
  "lg",
  "max",
  "min",
  "sup",
  "inf",
  "det",
  "deg",
];

/* ── Heuristics: is an ASCII/Unicode-math run math-like? ── */
function isMathLike(s: string): boolean {
  if (!s || s.length < 1) return false;
  if (/^[a-zA-Z0-9]+$/.test(s) && s.length <= 3) return false;
  if (/^[.,;:!?()\[\]{}"'\-\\/]+$/.test(s)) return false;

  for (const ch of s) {
    if (UNI_TO_LATEX[ch]) return true;
  }
  if (/\^[\d{}]/.test(s) || /_[\d{}]/.test(s)) return true;
  if (/\\[a-zA-Z]/.test(s)) return true;
  for (const func of MATH_FUNCS) {
    if (new RegExp("\\b" + func + "\\b").test(s)) return true;
  }
  if (/=/.test(s) && /[a-zA-Z0-9)]/.test(s)) return true;
  if (/\([^)]+\)\/\([^)]+\)/.test(s)) return true;
  if (/[a-zA-Z0-9)][+\-*/][a-zA-Z0-9(]/.test(s)) return true;

  return false;
}

/* ── Convert a detected math segment to LaTeX ── */
function convertToLatex(s: string): string {
  let r = s;
  for (const [uni, latex] of Object.entries(UNI_TO_LATEX)) {
    const esc = uni.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    r = r.replace(new RegExp(esc, "g"), latex);
  }
  for (const func of MATH_FUNCS) {
    const re = new RegExp("(?<=^|[\\s(])" + func + "(?=[\\s(]|$)", "g");
    r = r.replace(re, "\\" + func);
  }
  r = r.replace(/\s+/g, " ").trim();
  return r;
}

/* ── Regex: runs of ASCII + common math Unicode (non-CJK) ── */
const MATH_RUN_RE = /([\x20-\x7F°±×÷←-⇿∀-⋿≠≤≥]+)/g;

/* ── Split a processed string (may contain $…$) into parts ── */
function splitProcessed(
  processed: string,
  parts: Array<{ type: "plain" | "math"; value: string; displayMode: boolean }>
) {
  const re = /(\$[^$]+?\$)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(processed)) !== null) {
    if (m.index > last) {
      parts.push({ type: "plain", value: processed.slice(last, m.index), displayMode: false });
    }
    parts.push({ type: "math", value: m[1], displayMode: false });
    last = m.index + m[1].length;
  }
  if (last < processed.length) {
    parts.push({ type: "plain", value: processed.slice(last), displayMode: false });
  }
}

/* ── Auto-detect math-like segments in plain text, wrap in $…$ ── */
function autoWrapLatex(plain: string): string {
  const result: string[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = MATH_RUN_RE.exec(plain)) !== null) {
    if (match.index > lastIndex) {
      result.push(plain.slice(lastIndex, match.index));
    }
    const run = match[1];
    if (isMathLike(run)) {
      result.push("$" + convertToLatex(run) + "$");
    } else {
      result.push(run);
    }
    lastIndex = match.index + run.length;
  }
  if (lastIndex < plain.length) {
    result.push(plain.slice(lastIndex));
  }
  return result.join("");
}

/**
 * Renders text that mixes plain text with LaTeX math.
 * Supports:
 * 1. Explicit $…$ / $$…$$ delimiters
 * 2. Auto-detection of math-like segments (→, ∞, lim, sin, ^{…}, etc.)
 */
export function MixedLatexRenderer({ text, className = "" }: MixedLatexRendererProps) {
  const segments = useMemo(() => {
    if (!text) return [];

    const parts: Array<{ type: "plain" | "math"; value: string; displayMode: boolean }> = [];
    const delimRe = /(\$\$[^$]+?\$\$|\$[^$]+?\$)/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = delimRe.exec(text)) !== null) {
      if (match.index > lastIndex) {
        splitProcessed(autoWrapLatex(text.slice(lastIndex, match.index)), parts);
      }
      const raw = match[1];
      parts.push({ type: "math", value: raw, displayMode: raw.startsWith("$$") });
      lastIndex = match.index + raw.length;
    }
    if (lastIndex < text.length) {
      splitProcessed(autoWrapLatex(text.slice(lastIndex)), parts);
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
