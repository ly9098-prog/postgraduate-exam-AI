import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  codeSegmentText, comparableText, isCodeSegment, type ContentSegment,
} from "../question-content-editing";
import { updateCodeSegmentField } from "../question-segment-editing";

type SegmentListProps = {
  segments: ContentSegment[];
  onReplace: (segments: ContentSegment[]) => void;
  onAdd: () => void;
};
type CodeRowProps = {
  segment: ContentSegment;
  onChange: (segment: ContentSegment) => void;
  onDelete: () => void;
};

function CodeMetadataField({
  segment, field, onChange,
}: Pick<CodeRowProps, "segment" | "onChange"> & { field: "caption" | "language" }) {
  const caption = field === "caption";
  return (
    <label className="space-y-1">
      <span className="text-[11px] font-medium text-slate-500">
        {caption ? "显示标题（可选）" : "语言（可选）"}
      </span>
      <input
        className={caption
          ? "h-9 w-full rounded-lg border border-slate-200 bg-slate-50/60 px-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
          : "h-9 w-full rounded-lg border border-slate-200 bg-slate-50/60 px-3 font-mono text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"}
        value={String(segment[field] ?? "")}
        placeholder={caption ? "留空则不在题干中显示标题" : "assembly / c / cpp"}
        onChange={(event) => onChange(updateCodeSegmentField(segment, field, event.target.value))}
      />
    </label>
  );
}

function CodeMetadataEditor({ segment, onChange, onDelete }: CodeRowProps) {
  return (
    <div className="grid gap-3 border-b border-slate-200 bg-white px-4 py-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
      <CodeMetadataField segment={segment} field="caption" onChange={onChange} />
      <CodeMetadataField segment={segment} field="language" onChange={onChange} />
      <div className="flex items-end">
        <Button
          type="button"
          variant="secondary"
          className="h-9 border-red-100 bg-white px-3 text-xs text-red-600 shadow-none hover:border-red-200 hover:bg-red-50"
          onClick={onDelete}
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </Button>
      </div>
    </div>
  );
}

function CodeBodyEditor({ segment, onChange }: Pick<CodeRowProps, "segment" | "onChange">) {
  const code = codeSegmentText(segment);
  return (
    <>
      <textarea
        wrap="off"
        spellCheck={false}
        className="min-h-48 w-full resize-y overflow-auto whitespace-pre border-0 bg-slate-950 px-4 py-4 font-mono text-[13px] leading-6 text-slate-100 outline-none [tab-size:2]"
        value={code}
        placeholder="在这里输入代码内容……"
        onChange={(event) => onChange(updateCodeSegmentField(segment, "code", event.target.value))}
      />
      {!comparableText(code) ? (
        <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-[11px] text-amber-800">
          代码正文不能为空。输入内容后即可保存，或删除该空代码块。
        </div>
      ) : null}
    </>
  );
}

function CodeRow(props: CodeRowProps) {
  return (
    <div
      className={`overflow-hidden rounded-xl border bg-slate-50/50 ${
        comparableText(codeSegmentText(props.segment)) ? "border-slate-200" : "border-amber-300"
      }`}
    >
      <CodeMetadataEditor {...props} />
      <CodeBodyEditor segment={props.segment} onChange={props.onChange} />
    </div>
  );
}

function CodeSectionHeader({ count, onAdd }: { count: number; onAdd: () => void }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="text-sm font-semibold text-slate-950">代码块</p>
        <p className="mt-1 text-[11px] text-slate-400">
          可手动插入代码内容；只有显式 caption 才作为可见标题，segment.alt 仅保留为辅助描述。
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[11px] tabular-nums text-slate-400">
          {count} 个代码块
        </span>
        <Button
          type="button"
          variant="secondary"
          className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
          onClick={onAdd}
        >
          <Plus className="h-3.5 w-3.5" />
          添加代码块
        </Button>
      </div>
    </div>
  );
}

export function QuestionCodeEditor({ segments, onReplace, onAdd }: SegmentListProps) {
  return (
    <section className="border-b border-slate-200 py-5">
      <CodeSectionHeader count={segments.filter(isCodeSegment).length} onAdd={onAdd} />
      {segments.some(isCodeSegment) ? (
        <div className="space-y-4">
          {segments.map((segment, index) => !isCodeSegment(segment) ? null : (
            <CodeRow
              key={String(segment.region_id ?? `code-${index}`)}
              segment={segment}
              onChange={(nextSegment) => {
                const next = [...segments];
                next[index] = nextSegment;
                onReplace(next);
              }}
              onDelete={() => onReplace(segments.filter((_, position) => position !== index))}
            />
          ))}
        </div>
      ) : (
        <button
          type="button"
          onClick={onAdd}
          className="flex min-h-24 w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/40 px-4 text-sm text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
        >
          <span className="flex items-center gap-2">
            <Plus className="h-4 w-4" />
            插入代码块
          </span>
        </button>
      )}
    </section>
  );
}
