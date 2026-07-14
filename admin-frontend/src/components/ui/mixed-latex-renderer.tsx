"use client";

import { Fragment, useMemo } from "react";
import { LatexRenderer } from "./latex-renderer";
import { tokenizeMathText } from "@/lib/math-text";

type MixedLatexRendererProps = {
  text: unknown;
  className?: string;
  mathClassName?: string;
};

/**
 * Render Chinese/plain text and mathematical expressions in one string.
 *
 * It accepts explicit delimiters as well as raw backend values such as:
 * - 二次函数 y=ax^2+bx+c
 * - a>0 时 [\\frac{4ac-b^2}{4a}, +\\infty)
 * - 顶点 (-b/(2a), (4ac-b^2)/(4a))
 */
export function MixedLatexRenderer({
  text,
  className = "",
  mathClassName = "",
}: MixedLatexRendererProps) {
  const segments = useMemo(() => tokenizeMathText(text), [text]);
  if (!segments.length) return null;

  return (
    <span className={`math-text-renderer ${className}`}>
      {segments.map((segment, index) => {
        if (segment.type === "text") {
          return <Fragment key={`text-${index}`}>{segment.value}</Fragment>;
        }

        // Fractions and large operators are easier to read with display-style
        // glyphs even when they occur inside a prose line.
        // Skip if the expression already has \displaystyle to avoid duplication.
        const source = !segment.displayMode && /\\(?:frac|sum|prod|int|lim)(?![a-zA-Z])/.test(segment.value)
          ? (segment.value.includes("\\displaystyle")
            ? segment.value
            : `\\displaystyle ${segment.value}`)
          : segment.value;

        return (
          <LatexRenderer
            key={`math-${index}`}
            latex={source}
            displayMode={segment.displayMode}
            className={mathClassName}
          />
        );
      })}
    </span>
  );
}
