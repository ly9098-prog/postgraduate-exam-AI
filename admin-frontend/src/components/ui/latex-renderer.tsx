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
      const source = hasDelimiter(latex) ? stripDelimiters(latex) : latex;
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
