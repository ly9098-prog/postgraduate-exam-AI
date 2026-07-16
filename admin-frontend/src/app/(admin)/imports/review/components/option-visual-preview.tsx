"use client";

import { useState, useCallback, useRef } from "react";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { MathFormula } from "@/components/ui/math-formula";
import { resolveAssetUrl } from "@/lib/asset-url";
import { MissingOptionImageAlert } from "./missing-option-image-alert";
import type { OptionVisualModel, OptionVisualSegment } from "@/lib/option-visual-utils";

interface OptionVisualPreviewProps {
  model: OptionVisualModel;
  options: Array<{ key: string; text: string; segments?: Array<Record<string, unknown>> }>;
  onRuntimeIssue?: (issue: string) => void;
}

/**
 * Read-only preview of options based on OptionVisualModel mode.
 */
export function OptionVisualPreview({ model, options, onRuntimeIssue }: OptionVisualPreviewProps) {
  // Track only image load failures — NOT stored on the model (model is useMemo derived)
  const [failedUrls, setFailedUrls] = useState<Set<string>>(new Set());

  const handleImageError = useCallback(
    (url: string) => {
      if (failedUrls.has(url)) return;
      setFailedUrls((prev) => new Set(prev).add(url));
      onRuntimeIssue?.(`图片加载失败: ${url} — HTTP 状态未知，请通过后端资产校验接口确认`);
    },
    [failedUrls, onRuntimeIssue],
  );

  // ── option_group mode ──
  if (model.mode === "option_group" && model.groupImage) {
    const gi = model.groupImage;
    const resolvedUrl = resolveAssetUrl(gi.url);
    const isFailed = failedUrls.has(gi.url);

    return (
      <div className="space-y-3">
        {/* Group image */}
        <div className="overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-white shadow-sm">
          {isFailed || !resolvedUrl ? (
            <ImageErrorCard segment={gi} url={resolvedUrl} />
          ) : (
            <div className="relative group/img">
              <img
                src={resolvedUrl}
                alt={gi.alt || "选项组"}
                className="max-w-full cursor-zoom-in"
                style={{ objectFit: "contain", maxHeight: "200px" }}
                onClick={() => window.open(resolvedUrl, "_blank")}
                onError={() => handleImageError(gi.url)}
              />
              <div className="absolute inset-0 rounded-xl ring-1 ring-inset ring-black/5 pointer-events-none" />
              {/* Metadata overlay */}
              <div className="absolute bottom-0 left-0 right-0 flex flex-wrap gap-1 bg-gradient-to-t from-black/50 to-transparent p-2 opacity-0 transition-opacity group-hover/img:opacity-100">
                {gi.regionType ? (
                  <span className="rounded bg-black/60 px-1.5 py-0.5 text-[9px] text-white">{gi.regionType}</span>
                ) : null}
                {gi.bbox ? (
                  <span className="rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9px] text-white">
                    {JSON.stringify(gi.bbox)}
                  </span>
                ) : null}
                {gi.cropVersion ? (
                  <span className="rounded bg-black/60 px-1.5 py-0.5 text-[9px] text-white">{gi.cropVersion}</span>
                ) : null}
                {gi.assetHash ? (
                  <span className="rounded bg-black/60 px-1.5 py-0.5 font-mono text-[8px] text-white/80">
                    {gi.assetHash.slice(0, 12)}...
                  </span>
                ) : null}
              </div>
            </div>
          )}
        </div>

        {/* Option keys labels */}
        <div className="flex flex-wrap gap-2">
          {model.expectedOptionKeys.map((key) => (
            <div key={key} className="flex items-center gap-1.5">
              <span className="option-chip">{key}</span>
              {model.legacy ? (
                <span className="text-[10px] text-[var(--color-text-hint)]">图形见上方选项图</span>
              ) : null}
            </div>
          ))}
        </div>

        {/* Legacy warning */}
        {model.legacy ? (
          <div className="rounded-lg border border-amber-200/60 bg-amber-50/70 p-2">
            <p className="text-[10px] font-medium text-amber-700">
              兼容模式：此选项组使用旧格式识别，可能缺少元数据。建议重新生成。
            </p>
          </div>
        ) : null}

        {/* Issues */}
        {model.issues.length > 0 ? (
          <div className="space-y-1">
            {model.issues.map((issue, i) => (
              <p key={i} className="flex items-center gap-1 text-[10px] text-amber-600">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                {issue}
              </p>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  // ── option_images mode ──
  if (model.mode === "option_images") {
    return (
      <div className="space-y-3">
        {model.expectedOptionKeys.map((key) => {
          const opt = options.find((o) => o.key === key);
          const images = model.optionImages[key] ?? [];
          return (
            <div key={key} className="flex items-start gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center option-chip">{key}</span>
              <div className="min-w-0 flex-1 space-y-1">
                {/* Text (if any) */}
                {opt?.text && (
                  <span className="text-sm text-[var(--color-text-secondary)]">
                    <MathFormula text={opt.text} />
                  </span>
                )}
                {/* Images */}
                {images.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {images.map((img, ii) => {
                      const imgUrl = resolveAssetUrl(img.url);
                      const isImgFailed = failedUrls.has(img.url);
                      if (isImgFailed || !imgUrl) {
                        return <ImageErrorCard key={ii} segment={img} url={imgUrl} compact />;
                      }
                      return (
                        <div key={ii} className="group/img relative overflow-hidden rounded-lg border border-[var(--color-border)]/50">
                          <img
                            src={imgUrl}
                            alt={img.alt || `选项${key}`}
                            className="max-h-20 max-w-28 cursor-zoom-in rounded-lg object-contain"
                            onClick={() => window.open(imgUrl, "_blank")}
                            onError={() => handleImageError(img.url)}
                          />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <span className="text-[10px] text-amber-600">（选项 {key} 无对应图片）</span>
                )}
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
      <MissingOptionImageAlert
        placeholderKeys={model.placeholderKeys}
        missingImageKeys={model.missingImageKeys}
      />
    );
  }

  // ── none mode: standard text rendering ──
  return (
    <div className="space-y-2">
      {options.length === 0 ? (
        <p className="text-sm text-[var(--color-text-hint)]">（无选项）</p>
      ) : (
        options.map((opt) => (
          <div key={opt.key} className="flex items-center gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center option-chip">{opt.key}</span>
            <span className="text-sm text-[var(--color-text-secondary)]">
              <MathFormula text={opt.text} />
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ─── Image error card ───────────────────────────────────────────

function ImageErrorCard({
  segment,
  url,
  compact,
}: {
  segment: OptionVisualSegment;
  url: string;
  compact?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-dashed border-red-300 bg-red-50/50 ${
        compact ? "max-w-28 p-2" : "p-3"
      }`}
    >
      <div className="flex items-center gap-1.5 text-red-600">
        <AlertTriangle className="h-3 w-3 shrink-0" />
        <span className="text-[10px] font-medium">图片加载失败</span>
      </div>
      <div className="mt-1 space-y-0.5 text-[9px] text-red-500">
        <p className="truncate" title={url || segment.url}>
          URL: {url || segment.url || "无"}
        </p>
        <p>HTTP 状态: 未知 — 请通过后端资产校验接口确认</p>
        {segment.regionId && <p>region_id: {segment.regionId}</p>}
        {segment.assetHash && <p className="font-mono">{segment.assetHash.slice(0, 16)}...</p>}
        {segment.cropVersion && <p>{segment.cropVersion}</p>}
      </div>
    </div>
  );
}
