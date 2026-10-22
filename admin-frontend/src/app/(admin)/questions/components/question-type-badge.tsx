import { Layers } from "lucide-react";
import { getQuestionTypeLabel } from "@/lib/question-types";

/** Type badge */
export function TypeBadge({ type: t }: { type: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">
      <Layers className="h-3 w-3" />
      {getQuestionTypeLabel(t)}
    </span>
  );
}
