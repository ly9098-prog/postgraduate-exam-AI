"use client";

import { AlertTriangle } from "lucide-react";

interface MissingOptionImageAlertProps {
  placeholderKeys: string[];
  missingImageKeys: string[];
  importId?: number;
  sourceQuestionNo?: string;
  /** Original placeholder values for audit trail. */
  legacyPlaceholders?: Record<string, string>;
}

/**
 * Alert card shown when image-type options have no valid image assets.
 * Blocks approval — the affected question cannot be passed until resolved.
 */
export function MissingOptionImageAlert({
  placeholderKeys,
  missingImageKeys,
  importId,
  sourceQuestionNo,
  legacyPlaceholders,
}: MissingOptionImageAlertProps) {
  const allAffectedKeys = Array.from(new Set([...placeholderKeys, ...missingImageKeys])).sort();
  if (allAffectedKeys.length === 0) return null;

  return (
    <div className="rounded-xl border border-red-200/60 bg-red-50/80 p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-100">
          <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-sm font-bold text-red-800">图片选项资产缺失</p>
          <p className="text-xs leading-relaxed text-red-700">
            检测到以下选项包含图片占位符，但 <code className="rounded bg-red-100/80 px-1 font-mono text-[10px]">parsed_content</code>{" "}
            和 <code className="rounded bg-red-100/80 px-1 font-mono text-[10px]">parsed_options</code> 中没有可用图片资源：
          </p>

          <div className="flex flex-wrap gap-1.5">
            {allAffectedKeys.map((k) => (
              <span
                key={k}
                className="inline-flex items-center gap-1 rounded-md bg-red-100/70 px-2 py-0.5 font-mono text-xs font-bold text-red-700"
              >
                {k}
                {missingImageKeys.includes(k) ? (
                  <span className="text-[9px] font-normal text-red-500">(缺图)</span>
                ) : null}
              </span>
            ))}
          </div>

          {importId || sourceQuestionNo ? (
            <div className="flex flex-wrap gap-2 text-[10px] text-red-600">
              {importId ? <span>import_id={importId}</span> : null}
              {sourceQuestionNo ? <span>source_question_no={sourceQuestionNo}</span> : null}
            </div>
          ) : null}

          {/* Legacy placeholder audit trail */}
          {legacyPlaceholders && Object.keys(legacyPlaceholders).length > 0 ? (
            <details className="rounded-lg border border-red-200/40 bg-red-50/60 p-2">
              <summary className="cursor-pointer text-[10px] font-semibold text-red-600 hover:text-red-800">
                原始占位数据（审计追溯）
              </summary>
              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap font-mono text-[9px] leading-relaxed text-red-500">
                {JSON.stringify(legacyPlaceholders, null, 2)}
              </pre>
            </details>
          ) : null}

          <div className="rounded-lg border border-red-200/40 bg-white/60 p-2.5">
            <p className="text-[10px] font-medium text-red-700">风险标记</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {placeholderKeys.length > 0 ? (
                <span className="rounded bg-red-100 px-1.5 py-0.5 font-mono text-[9px] text-red-600">
                  legacy_option_placeholder
                </span>
              ) : null}
              {missingImageKeys.length > 0 ? (
                <span className="rounded bg-red-100 px-1.5 py-0.5 font-mono text-[9px] text-red-600">
                  missing_option_image_asset
                </span>
              ) : null}
              <span className="rounded bg-red-100 px-1.5 py-0.5 font-mono text-[9px] text-red-600">
                requires_manual_review
              </span>
            </div>
          </div>

          <div className="rounded-lg border border-amber-200/60 bg-amber-50/70 p-2">
            <p className="text-[10px] font-medium text-amber-700">当前状态</p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-amber-600">
              该题禁止审核通过。请返回补图流程重新生成选项图片，或手动替换图片。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
