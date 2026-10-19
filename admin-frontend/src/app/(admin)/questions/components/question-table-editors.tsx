import { StructuredTableEditor } from "@/components/structured-table-editor";
import { isTableSegment, normalizeStructuredTableSegment } from "@/lib/structured-table";
import type { ContentSegment } from "../question-content-editing";

type TableEditorsProps = {
  segments: ContentSegment[];
  onReplace: (segments: ContentSegment[]) => void;
};

export function QuestionTableEditors({ segments, onReplace }: TableEditorsProps) {
  if (!segments.some((segment) => isTableSegment(segment))) return null;
  return (
    <div className="space-y-4">
      {segments.map((segment, index) => {
        const table = normalizeStructuredTableSegment(segment);
        if (!table) return null;
        return (
          <StructuredTableEditor
            key={table.table_id || index}
            segment={table}
            onChange={(nextTable) => {
              const next = [...segments];
              next[index] = nextTable;
              onReplace(next);
            }}
            onDelete={() => onReplace(segments.filter((_, position) => position !== index))}
          />
        );
      })}
    </div>
  );
}
