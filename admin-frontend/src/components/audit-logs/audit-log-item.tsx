"use client";

import { memo } from "react";
import { StatusBadge } from "@/components/status-badge";
import { TONE_MAP, actionLabel, severityLabel, statusLabel } from "./action-labels";
import { formatLocalDateTime, truncate } from "./date-utils";
import type { AuditLogListItem } from "@/lib/api/types";

type AuditLogItemProps = {
  log: AuditLogListItem;
  onOpen: (id: number) => void;
};

export const AuditLogItem = memo(function AuditLogItem({ log, onOpen }: AuditLogItemProps) {
  const summary = log.detail_summary;

  return (
    <button
      className="group w-full rounded-xl border border-[var(--color-border)] bg-white/70 p-4 text-left transition-all duration-150 hover:border-[var(--color-primary)]/50 hover:bg-white hover:shadow-sm motion-reduce:transition-none"
      onClick={() => onOpen(log.id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(log.id); } }}
      aria-label={`${actionLabel(log.action)} 日志详情`}
    >
      {/* Row 1: badges + action + time */}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <StatusBadge tone={log.status === "failed" ? "danger" : "success"}>
          {statusLabel(log.status)}
        </StatusBadge>
        <StatusBadge tone={TONE_MAP[log.severity] ?? "neutral"}>
          {severityLabel(log.severity)}
        </StatusBadge>
        <span className="text-sm font-semibold text-[var(--ink)]">{actionLabel(log.action)}</span>
        <span className="ml-auto text-xs text-[var(--color-text-hint)]" title={log.created_at}>
          {formatLocalDateTime(log.created_at)}
        </span>
      </div>

      {/* Row 2: resource info + operator */}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-[var(--color-text-secondary)]">
        {log.resource_type && (
          <span>
            <span className="font-medium text-[var(--color-text-hint)]">{log.resource_type}</span>
            {log.resource_id ? <span className="font-mono text-[var(--color-text-hint)]"> #{log.resource_id}</span> : null}
          </span>
        )}
        <span>
          by {log.operator_name ?? log.operator_id != null ? `#${log.operator_id}` : "system"}
        </span>
        {log.ip && <span className="font-mono text-[10px] text-[var(--color-text-hint)]">{log.ip}</span>}
      </div>

      {/* Question summary */}
      {summary && (
        <div className="mt-1.5 text-xs text-[var(--color-text-hint)] line-clamp-2">
          {[
            summary.subject_name,
            summary.question_type,
            truncate(
              typeof summary.content_preview === "string" ? summary.content_preview : null,
              80,
            ),
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      )}

      {/* Error message */}
      {log.error_message && (
        <div className="mt-2 rounded-lg border border-[var(--color-danger)]/30 bg-[var(--color-danger-light)] px-3 py-2 text-xs text-[var(--color-danger)]">
          {truncate(log.error_message, 150)}
        </div>
      )}
    </button>
  );
});
