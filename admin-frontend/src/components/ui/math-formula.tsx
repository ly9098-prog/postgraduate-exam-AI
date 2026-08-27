import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";

/**
 * Compatibility facade for mixed prose + LaTeX question content.
 *
 * Numeric dimensions written with a plain `x` (for example `12x12`) are
 * normalized to the multiplication sign before math tokenization. This keeps
 * the `x` from being interpreted as an italic algebra variable by KaTeX while
 * preserving ordinary variable expressions such as `ax+b`.
 */
export function MathFormula({ text, className = "" }: { text: string; className?: string }) {
  const normalizedText = String(text ?? "").replace(/(\d)\s*[xX]\s*(\d)/g, "$1×$2");
  return <MixedLatexRenderer text={normalizedText} className={className} />;
}
