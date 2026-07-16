"use client";

import { AlertTriangle, X } from "lucide-react";
import { resolveAssetUrl } from "@/lib/asset-url";
import { MissingOptionImageAlert } from "./missing-option-image-alert";
import type { OptionVisualModel } from "@/lib/option-visual-utils";

interface OptionVisualEditorProps {
  model: OptionVisualModel;
  options: Array<{ key: string; text: string; segments?: Array<Record<string, unknown>> }>;
  onChange: (options: Array<{ key: string; text: string; segments?: Array<Record<string, unknown>> }>) => void;
  /** Called when user requests a mode override from placeholder_missing → text. */
  onRequestTextModeOverride?: () => void;
}

/**
 * Editor for image-type options. Preserves segments, metadata, bbox, asset_hash, crop_version.
 * Never overwrites rich option with `{key, text}` only.
 */
export function OptionVisualEditor({
  model,
  options,
  onChange,
  onRequestTextModeOverride,
}: OptionVisualEditorProps) {
  // ── option_group mode ──
  if (model.mode === "option_group" && model.groupImage) {
    const resolvedUrl = resolveAssetUrl(model.groupImage.url);

    return (
      <div className="space-y-3">
        {/* Group image */}
        {resolvedUrl ? (
          <div className="overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-white">
            <img
              src={resolvedUrl}
              alt={model.groupImage.alt || "选项组"}
              className="max-w-full"
              style={{ objectFit: "contain", maxHeight: "200px" }}
            />
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-amber-300/60 bg-amber-50/40 px-3 py-4 text-center text-xs text-amber-600">
            选项组图片不可用
          </div>
        )}

        <p className="text-[10px] text-[var(--color-text-hint)]">此题为图片选项组，文字可留空。</p>

        {/* Text inputs — allow empty */}
        {options.map((opt, index) => (
          <div key={opt.key} className="flex items-start gap-2">
            <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center option-chip">{opt.key}</span>
            <div className="flex-1 space-y-1">
              <input
                className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
                value={opt.text}
                placeholder="（图片选项，文字可留空）"
                onChange={(e) => {
                  const next = [...options];
                  next[index] = { ...next[index], text: e.target.value, segments: next[index].segments };
                  onChange(next);
                }}
              />
              {/* Preserve existing segments */}
              {opt.segments && opt.segments.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {opt.segments.map((seg, si) => (
                    <div key={si} className="flex items-center gap-1 rounded-md border border-[var(--color-border)]/50 bg-white/70 px-2 py-1">
                      <span className="text-[10px] text-[var(--color-text-hint)]">{String(seg.type ?? "")}</span>
                      <span className="max-w-24 truncate font-mono text-[9px] text-[var(--color-text-hint)]">
                        {String(seg.url ?? "")}
                      </span>
                      {seg.option_key ? (
                        <span className="rounded bg-[var(--color-primary-light)] px-1 font-mono text-[9px]">
                          {String(seg.option_key)}
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {/* Legacy warning */}
        {model.legacy ? (
          <div className="rounded-lg border border-amber-200/60 bg-amber-50/70 p-2">
            <p className="flex items-center gap-1 text-[10px] font-medium text-amber-700">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              兼容模式 — 保存时不会丢失图片数据
            </p>
          </div>
        ) : null}
      </div>
    );
  }

  // ── option_images mode ──
  if (model.mode === "option_images") {
    return (
      <div className="space-y-2">
        {model.expectedOptionKeys.map((key) => {
          const opt = options.find((o) => o.key === key);
          const images = model.optionImages[key] ?? [];
          return (
            <div key={key} className="flex items-start gap-2">
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center option-chip">{key}</span>
              <div className="flex-1 space-y-1">
                <input
                  className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
                  value={opt?.text ?? ""}
                  onChange={(e) => {
                    const next = [...options];
                    const idx = next.findIndex((o) => o.key === key);
                    if (idx >= 0) {
                      next[idx] = { ...next[idx], text: e.target.value };
                    }
                    onChange(next);
                  }}
                />
                {images.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {images.map((img, ii) => {
                      const imgUrl = resolveAssetUrl(img.url);
                      return (
                        <div
                          key={ii}
                          className="group/img relative overflow-hidden rounded-lg border border-[var(--color-border)]/50 bg-white"
                        >
                          {imgUrl ? (
                            <img
                              src={imgUrl}
                              alt={img.alt || `选项${key}`}
                              className="max-h-16 max-w-24 object-contain"
                            />
                          ) : (
                            <div className="flex h-12 w-20 items-center justify-center text-[9px] text-amber-600">
                              无图片
                            </div>
                          )}
                          <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover/img:opacity-100">
                            <button
                              type="button"
                              className="flex h-6 w-6 items-center justify-center rounded-full bg-white/90 text-red-500 shadow-sm hover:bg-white"
                              title="移除图片"
                              onClick={() => {
                                // Only remove from UI — actual delete is on save
                                const next = [...options];
                                const idx = next.findIndex((o) => o.key === key);
                                if (idx >= 0) {
                                  const segs = (next[idx].segments ?? []).filter(
                                    (_, sIdx) => sIdx !== ii + (next[idx].segments?.length ?? 0) - images.length + ii,
                                  );
                                  next[idx] = { ...next[idx], segments: segs.length > 0 ? segs : undefined };
                                }
                                onChange(next);
                              }}
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // ── placeholder_missing mode ──
  if (model.mode === "placeholder_missing") {
    return (
      <div className="space-y-3">
        <MissingOptionImageAlert
          placeholderKeys={model.placeholderKeys}
          missingImageKeys={model.missingImageKeys}
        />

        {/* Read-only text inputs */}
        <div className="space-y-2">
          {model.expectedOptionKeys.map((key) => (
            <div key={key} className="flex items-start gap-2 opacity-60">
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center option-chip">{key}</span>
              <input
                className="h-9 w-full rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-bg-input)]/50 px-3 text-sm text-[var(--color-text-hint)] outline-none"
                value=""
                disabled
                placeholder="（图片选项占位，无法编辑）"
              />
            </div>
          ))}
        </div>

        {/* Override to text mode */}
        {onRequestTextModeOverride ? (
          <div className="rounded-lg border border-amber-200/60 bg-amber-50/70 p-3">
            <p className="mb-2 text-[10px] font-medium text-amber-700">如果已知文字答案，可切换为文字编辑模式</p>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-lg border border-amber-300/60 bg-white px-2.5 py-1.5 text-[10px] font-semibold text-amber-700 shadow-sm transition hover:bg-amber-100 hover:text-amber-800"
              onClick={() => {
                if (window.confirm("切换为文字选项模式后，图片关系和历史占位数据将被保留但不再展示。确定继续吗？")) {
                  onRequestTextModeOverride();
                }
              }}
            >
              <AlertTriangle className="h-3 w-3" />
              切换为文字选项模式
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  // ── none mode: standard text inputs ──
  return (
    <div className="space-y-2">
      {options.length === 0 ? <p className="text-sm text-[var(--color-text-hint)]">暂无可编辑选项</p> : null}
      {options.map((opt, index) => (
        <div key={opt.key} className="flex items-start gap-2">
          <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center option-chip">{opt.key}</span>
          <div className="flex-1 space-y-1.5">
            <input
              className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
              value={opt.text}
              onChange={(e) => {
                const next = [...options];
                next[index] = { ...next[index], text: e.target.value };
                onChange(next);
              }}
            />
            {opt.segments && opt.segments.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {opt.segments.map((seg, si) => {
                  const segType = String(seg.type ?? "").toLowerCase();
                  const isImg = ["image", "math_image", "table_image", "code_image"].includes(segType);
                  const label =
                    segType === "math_image"
                      ? "公式"
                      : segType === "table_image"
                        ? "表格"
                        : segType === "code_image"
                          ? "代码"
                          : segType === "newline"
                            ? "换行"
                            : "图片";
                  return (
                    <div key={si} className="flex items-center gap-1 rounded-md border border-[var(--color-border)]/50 bg-white/70 px-2 py-1">
                      {isImg && seg.url ? (
                        <img src={String(seg.url)} alt="" className="h-8 w-8 rounded object-cover" />
                      ) : null}
                      <span className="text-[10px] text-[var(--color-text-hint)]">{label}</span>
                      {seg.option_key ? (
                        <span className="rounded bg-[var(--color-primary-light)] px-1 font-mono text-[9px]">
                          {String(seg.option_key)}
                        </span>
                      ) : null}
                      <button
                        type="button"
                        className="ml-0.5 flex h-4 w-4 items-center justify-center rounded text-[9px] text-red-400 hover:bg-red-50 hover:text-red-600"
                        onClick={() => {
                          const next = [...options];
                          const segs = next[index].segments?.filter((_, i) => i !== si) ?? [];
                          next[index] = { ...next[index], segments: segs.length > 0 ? segs : undefined };
                          onChange(next);
                        }}
                        title="移除该片段"
                      >
                        ✕
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
