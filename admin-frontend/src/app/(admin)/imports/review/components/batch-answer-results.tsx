import { AlertTriangle, Check, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BatchAnswerApplyResponse, BatchAnswerPreviewResponse } from "@/lib/api/types";

type PreviewProps = {
  preview: BatchAnswerPreviewResponse;
  executing: boolean;
  onApply: () => void;
};

function AnswerPreviewSummary({ preview }: Pick<PreviewProps, "preview">) {
  return (
    <div className="flex flex-wrap gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)]/30 px-4 py-3 text-xs">
      <span>共 <strong>{preview.summary.parsed_answer_count}</strong> 个答案</span>
      <span className="text-[var(--color-text-hint)]">·</span>
      <span className="text-emerald-700">可写入 <strong>{preview.summary.writable_count}</strong></span>
      {preview.summary.skipped_existing_count > 0 ? (
        <>
          <span className="text-[var(--color-text-hint)]">·</span>
          <span className="text-amber-600">跳过已有 <strong>{preview.summary.skipped_existing_count}</strong></span>
        </>
      ) : null}
      {preview.summary.invalid_count > 0 ? (
        <>
          <span className="text-[var(--color-text-hint)]">·</span>
          <span className="text-red-600">无效 <strong>{preview.summary.invalid_count}</strong></span>
        </>
      ) : null}
      {preview.summary.unsupported_count > 0 ? (
        <>
          <span className="text-[var(--color-text-hint)]">·</span>
          <span className="text-gray-500">不支持 <strong>{preview.summary.unsupported_count}</strong></span>
        </>
      ) : null}
    </div>
  );
}

function AnswerPreviewRow({ item }: { item: BatchAnswerPreviewResponse["items"][number] }) {
  const statusColor = item.will_update
    ? "text-emerald-600"
    : item.status === "skip_existing" || item.status === "skip_existing_same"
      ? "text-amber-600"
      : item.status === "invalid_answer"
        ? "text-red-600"
        : item.status === "unsupported_type"
          ? "text-gray-400"
          : "text-[var(--color-text-secondary)]";
  return (
    <tr className="border-b border-[var(--color-border)]/50 last:border-0 hover:bg-[var(--color-bg-input)]/30">
      <td className="px-3 py-2 align-top font-mono text-[var(--color-text-secondary)]">
        {item.source_question_no ?? item.source_order_index ?? "?"}
      </td>
      <td className="px-3 py-2 align-top max-w-[200px] overflow-hidden text-ellipsis whitespace-nowrap text-[var(--ink)]" title={item.stem_excerpt}>
        {item.stem_excerpt}
      </td>
      <td className="px-3 py-2 align-top font-mono text-[var(--color-text-secondary)]">
        {item.original_answer || <span className="text-[var(--color-text-hint)]">—</span>}
      </td>
      <td className="px-3 py-2 align-top font-mono font-semibold text-[var(--ink)]">
        {item.normalized_answer || <span className="text-[var(--color-text-hint)]">—</span>}
      </td>
      <td className={`px-3 py-2 align-top ${statusColor}`}>
        {item.will_update ? "将写入" : item.status === "skip_existing" ? "跳过" : item.status === "skip_existing_same" ? "相同" : item.status === "invalid_answer" ? "无效" : item.status === "unsupported_type" ? "不支持" : item.status === "order_anomaly" ? "异常" : item.status || "—"}
      </td>
    </tr>
  );
}

function AnswerPreviewTable({ preview }: Pick<PreviewProps, "preview">) {
  return (
    <div className="max-h-[360px] overflow-y-auto rounded-xl border border-[var(--color-border)]">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-[var(--color-bg-input)]/80 backdrop-blur-sm">
          <tr className="border-b border-[var(--color-border)]">
            <th className="px-3 py-2 font-semibold text-[var(--color-text-secondary)]">#</th>
            <th className="px-3 py-2 font-semibold text-[var(--color-text-secondary)]">题干</th>
            <th className="px-3 py-2 font-semibold text-[var(--color-text-secondary)]">原答案</th>
            <th className="px-3 py-2 font-semibold text-[var(--color-text-secondary)]">新答案</th>
            <th className="px-3 py-2 font-semibold text-[var(--color-text-secondary)]">状态</th>
          </tr>
        </thead>
        <tbody>
          {preview.items.map((item) => <AnswerPreviewRow key={item.import_id} item={item} />)}
        </tbody>
      </table>
    </div>
  );
}

export function BatchAnswerPreview({ preview, executing, onApply }: PreviewProps) {
  return (
    <div className="space-y-4">
      <AnswerPreviewSummary preview={preview} />
      <AnswerPreviewTable preview={preview} />
      {preview.warnings.length > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700">
          {preview.warnings.map((w, i) => (
            <p key={i} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{w}</span>
            </p>
          ))}
        </div>
      ) : null}
      <Button
        className="h-9 w-full text-sm"
        disabled={preview.summary.writable_count === 0 || executing}
        onClick={onApply}
      >
        <Check className="mr-1.5 h-4 w-4" />
        确认写入 {preview.summary.writable_count} 题答案
      </Button>
    </div>
  );
}

export function BatchAnswerResult({ result, onClose }: {
  result: BatchAnswerApplyResponse;
  onClose: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
        <div className="flex items-center gap-2 text-emerald-700">
          <CheckCircle2 className="h-5 w-5" />
          <span className="font-semibold">批量答案写入完成</span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-3 text-center text-sm">
          <div className="rounded-lg bg-white/70 px-3 py-2">
            <p className="text-lg font-bold text-emerald-600">{result.updated_count}</p>
            <p className="text-xs text-emerald-700/70">已更新</p>
          </div>
          <div className="rounded-lg bg-white/70 px-3 py-2">
            <p className="text-lg font-bold text-amber-600">{result.skipped_existing_count}</p>
            <p className="text-xs text-amber-700/70">已跳过</p>
          </div>
          <div className="rounded-lg bg-white/70 px-3 py-2">
            <p className="text-lg font-bold text-[var(--color-text-secondary)]">{result.remaining_count}</p>
            <p className="text-xs text-[var(--color-text-hint)]">剩余</p>
          </div>
        </div>
      </div>
      <Button
        variant="secondary"
        className="h-9 w-full text-sm"
        onClick={onClose}
      >
        关闭
      </Button>
    </div>
  );
}
