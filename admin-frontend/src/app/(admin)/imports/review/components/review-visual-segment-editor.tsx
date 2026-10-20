import type { ChangeEventHandler, RefObject } from "react";
import { Upload, X } from "lucide-react";
import { hasVisualSegments, isImageSegmentType, getSegmentTypeLabel, reorderSegmentUp, reorderSegmentDown, deleteSegmentAtIndex, updateSegOptionKey, type SegmentData } from "@/lib/segment-utils";
import type { useReviewSegmentDrag } from "../hooks/use-review-segment-drag";

type EditorProps = {
  segments: SegmentData[] | null;
  options: Array<{ key: string }>;
  uploading: number;
  drag: ReturnType<typeof useReviewSegmentDrag>;
  inputRef: RefObject<HTMLInputElement | null>;
  onFileChange: ChangeEventHandler<HTMLInputElement>;
  onChange: (segments: SegmentData[]) => void;
  onReplace: (index: number) => void;
};
type CardProps = Omit<EditorProps, "segments" | "inputRef" | "onFileChange"> & {
  segs: SegmentData[];
  seg: SegmentData;
  si: number;
};

function SegmentReorder({ segs, si, onChange }: CardProps) {
  return (
    <div className="flex shrink-0 flex-col gap-0.5 pt-0.5">
      {/* Drag grip hint */}
      <div className="flex h-5 items-center justify-center text-[var(--color-border)]" style={{ cursor: "grab" }} title="拖拽排序">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><circle cx="2" cy="2" r="1.2"/><circle cx="8" cy="2" r="1.2"/><circle cx="2" cy="5" r="1.2"/><circle cx="8" cy="5" r="1.2"/><circle cx="2" cy="8" r="1.2"/><circle cx="8" cy="8" r="1.2"/></svg>
      </div>
      <button
        type="button"
        className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--color-text-hint)] transition-all hover:bg-[var(--color-warning-light)] hover:text-[var(--color-warning)] disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:text-[var(--color-text-hint)]"
        disabled={si === 0}
        onClick={() => {
          onChange(reorderSegmentUp(segs, si));
        }}
        title="上移"
      ><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m18 15-6-6-6 6"/></svg></button>
      <button
        type="button"
        className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--color-text-hint)] transition-all hover:bg-[var(--color-warning-light)] hover:text-[var(--color-warning)] disabled:opacity-20 disabled:hover:bg-transparent disabled:hover:text-[var(--color-text-hint)]"
        disabled={si >= segs.length - 1}
        onClick={() => {
          onChange(reorderSegmentDown(segs, si));
        }}
        title="下移"
      ><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="m6 9 6 6 6-6"/></svg></button>
    </div>
  );
}

function SegmentAssignment({ segs, si, seg, options, onChange }: CardProps) {
  const segLabel = getSegmentTypeLabel(String(seg.type ?? "").toLowerCase());
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="rounded-full bg-[var(--color-warning-light)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-warning)]">{segLabel}</span>
      <select
        className="rounded-lg border border-[var(--color-border)] bg-white/90 px-2 py-1 text-[10px] font-medium text-[var(--ink)] outline-none transition focus:border-[var(--color-warning)] focus:ring-2 focus:ring-[var(--color-warning)]/15"
        value={String(seg.option_key ?? "")}
        onChange={(e) => {
          const val = e.target.value;
          onChange(updateSegOptionKey(segs, si, val));
        }}
      >
        <option value="">归属：题干</option>
        {options.map((o) => (
          <option key={o.key} value={o.key}>归属：选项 {o.key}</option>
        ))}
      </select>
      <span className="ml-auto text-[9px] text-[var(--color-text-hint)]">{si + 1}/{segs.length}</span>
    </div>
  );
}

function SegmentImage(props: CardProps) {
  const { seg, si, uploading, onReplace } = props;
  const segLabel = getSegmentTypeLabel(String(seg.type ?? "").toLowerCase());
  return (
    <div className="min-w-0 flex-1">
      <SegmentAssignment {...props} />
      {seg.url ? (
        <div className="seg-image-preview overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/30">
          <img src={String(seg.url)} alt={String(seg.alt ?? segLabel)} className="max-h-32 max-w-full object-contain" />
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-amber-300/60 bg-amber-50/40 px-3 py-3 text-center text-[10px] font-medium text-amber-600">暂无图片</div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)]/60 bg-white px-2.5 py-1 text-[10px] font-medium text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)] disabled:opacity-40"
          disabled={uploading === si}
          onClick={() => {
            onReplace(si);
          }}
        >
          {uploading === si ? (
            <><span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--color-primary)]/30 border-t-[var(--color-primary)]" /> 上传中…</>
          ) : (
            <><Upload className="h-3 w-3" /> 替换图片</>
          )}
        </button>
      </div>
    </div>
  );
}

function SegmentCard(props: CardProps) {
  const { segs, seg, si, drag, onChange } = props;
  const segType = String(seg.type ?? "").toLowerCase();
  const isImageSeg = isImageSegmentType(segType);
  if (!isImageSeg && segType !== "newline") return null;
  const _isDragging = drag.dragIndex === si;
  return (
    <div
      draggable
      className={`seg-card relative flex items-start gap-2.5 rounded-xl border bg-white p-3 ${
        _isDragging
          ? "dragging border-[var(--color-warning)] shadow-lg"
          : "border-[var(--color-border)]/50"
      } ${drag.overIndex === si && !_isDragging ? "drop-target" : ""}`}
      onDragStart={(event) => drag.start(si, event)}
      onDragOver={(event) => drag.over(si, event)}
      onDragLeave={drag.leave}
      onDrop={(event) => drag.drop(si, event)}
      onDragEnd={drag.end}
    >
      <SegmentReorder {...props} />
      {isImageSeg ? (
        <SegmentImage {...props} />
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div className="h-px flex-1 bg-[var(--color-border)]/40" />
          <span className="text-[10px] font-medium text-[var(--color-text-hint)]">换行</span>
          <div className="h-px flex-1 bg-[var(--color-border)]/40" />
        </div>
      )}
      <button
        type="button"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--color-text-hint)] transition-all hover:bg-red-50 hover:text-red-500"
        onClick={() => {
          const next = deleteSegmentAtIndex(segs, si);
          onChange(next);
        }}
        title="删除此片段"
      ><X className="h-3.5 w-3.5" /></button>
    </div>
  );
}

export function ReviewVisualSegmentEditor({
  segments: segs, inputRef, onFileChange, ...cardProps
}: EditorProps) {
  if (!segs || !hasVisualSegments(segs)) return null;
  return (
    <section className="animate-fade-up drawer-section-delay-3 rounded-2xl border border-[var(--color-border)]/80 bg-gradient-to-br from-[var(--porcelain)] via-white to-[var(--color-warning-light)]/30 p-5 shadow-[var(--shadow-card)]">
      <div className="seg-section-header mb-5 flex items-center gap-2.5 pb-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-warning-light)] shadow-sm">
          <svg className="h-3.5 w-3.5 text-[var(--color-warning)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
        </span>
        <div>
          <p className="text-xs font-bold text-[var(--ink)]">视觉片段编辑器</p>
          <p className="text-[10px] text-[var(--color-text-hint)]">拖拽排序 · 归属选项 · 替换图片</p>
        </div>
      </div>
      <div className="space-y-2">
        <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" ref={inputRef} onChange={onFileChange} />
        {segs.map((seg, si) => <SegmentCard key={si} {...cardProps} segs={segs} seg={seg} si={si} />)}
      </div>
      {segs.length === 0 || !segs.some((segment) => isImageSegmentType(String(segment.type ?? ""))) ? (
        <p className="mt-3 text-center text-[10px] italic text-[var(--color-text-hint)]">— 无可编辑的视觉片段 —</p>
      ) : null}
    </section>
  );
}
