"use client";

import katex from "katex";
import { useMemo } from "react";

type LatexRendererProps = {
  latex: string;
  displayMode?: boolean;
  className?: string;
  showSourceOnError?: boolean;
};

function hasDelimiter(latex: string): boolean {
  return /^\$[^$]/.test(latex) || /^\$\$/.test(latex) || /^\\\(/.test(latex) || /^\\\[/.test(latex);
}


/**
 * KaTeX warns for enclosed Unicode glyphs such as ② because its math fonts do
 * not have metrics for those code points. Render the common circled
 * alphanumerics with KaTeX's supported \textcircled command instead of
 * passing the raw Unicode symbol through to the parser.
 */
function normalizeEnclosedUnicode(source: string): string {
  return Array.from(source, (char) => {
    const codePoint = char.codePointAt(0);
    if (codePoint === undefined) return char;

    // ①..⑳
    if (codePoint >= 0x2460 && codePoint <= 0x2473) {
      return `\\textcircled{${codePoint - 0x2460 + 1}}`;
    }

    // ⓪
    if (codePoint === 0x24ea) {
      return "\\textcircled{0}";
    }

    // Ⓐ..Ⓩ
    if (codePoint >= 0x24b6 && codePoint <= 0x24cf) {
      return `\\textcircled{${String.fromCharCode(65 + codePoint - 0x24b6)}}`;
    }

    // ⓐ..ⓩ
    if (codePoint >= 0x24d0 && codePoint <= 0x24e9) {
      return `\\textcircled{${String.fromCharCode(97 + codePoint - 0x24d0)}}`;
    }

    return char;
  }).join("");
}

function stripDelimiters(latex: string): string {
  return latex
    .replace(/^\$\$([\s\S]*?)\$\$$/, "$1")
    .replace(/^\$([\s\S]*?)\$$/, "$1")
    .replace(/^\\\(([\s\S]*?)\\\)$/, "$1")
    .replace(/^\\\[([\s\S]*?)\\\]$/, "$1");
}

export function LatexRenderer({
  latex,
  displayMode = false,
  className = "",
  showSourceOnError = true,
}: LatexRendererProps) {
  const html = useMemo(() => {
    if (!latex?.trim()) return "";
    try {
      const rawSource = hasDelimiter(latex) ? stripDelimiters(latex) : latex;
      const source = normalizeEnclosedUnicode(rawSource);
      return katex.renderToString(source, {
        displayMode,
        throwOnError: false,
        // CJK text can legitimately appear in legacy formula payloads. KaTeX
        // renders it, but `warn` floods the browser console with
        // unicodeTextInMathMode messages. Keep warnings for every other strict
        // check while silencing only that known-compatible case.
        strict: (errorCode) => errorCode === "unicodeTextInMathMode" ? "ignore" : "warn",
        trust: false,
        output: "htmlAndMathml",
      });
    } catch {
      return null; // signal error
    }
  }, [latex, displayMode]);

  if (html === null) {
    // KaTeX rendering failed
    if (showSourceOnError) {
      return (
        <span className={`inline-flex items-center gap-1 ${className}`}>
          <span className="text-red-400" title="KaTeX 渲染失败">{latex}</span>
        </span>
      );
    }
    return <span className="text-red-400" title="KaTeX 渲染失败" />;
  }

  if (!html) return null;

  return (
    <span
      className={`katex-container ${className}`}
      style={displayMode ? { display: "block", overflowX: "auto", overflowY: "hidden", padding: "4px 0" } : { display: "inline-block" }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
