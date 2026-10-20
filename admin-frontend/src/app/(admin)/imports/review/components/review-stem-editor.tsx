import { StructuredTableEditor } from "@/components/structured-table-editor";
import { isTableSegment, normalizeStructuredTableSegment } from "@/lib/structured-table";

type Segments = Array<Record<string, unknown>>;

type EditorProps = {
  stem: string;
  segments: Segments | null;
  onStemChange: (stem: string) => void;
  onSegmentsChange: (segments: Segments) => void;
};

function StemTables({ segments, onSegmentsChange }: Pick<EditorProps, "segments" | "onSegmentsChange">) {
  if (!segments || !segments.some((segment) => isTableSegment(segment))) return null;
  return (
    <div className="space-y-4 animate-fade-up drawer-section-delay-3">
      {segments.map((segment, segmentIndex) => {
        const table = normalizeStructuredTableSegment(segment);
        if (!table) return null;
        return (
          <StructuredTableEditor
            key={table.table_id || segmentIndex}
            segment={table}
            onChange={(nextTable) => {
              const next = [...segments];
              next[segmentIndex] = nextTable;
              onSegmentsChange(next);
            }}
            onDelete={() => {
              onSegmentsChange(segments.filter((_, index) => index !== segmentIndex));
            }}
          />
        );
      })}
    </div>
  );
}

export function ReviewStemEditor({ stem, segments, onStemChange, onSegmentsChange }: EditorProps) {
  return (
    <>
      <label className="block space-y-1.5 animate-fade-up drawer-section-delay-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
          题干
        </span>
        <textarea className="min-h-36 w-full rounded-xl border border-[var(--color-border)] bg-white/90 px-3 py-2.5 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15" value={stem} onChange={(event) => onStemChange(event.target.value)} />
      </label>
      <StemTables segments={segments} onSegmentsChange={onSegmentsChange} />
    </>
  );
}
