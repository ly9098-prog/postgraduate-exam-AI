"use client";

import type { ReactNode } from "react";
import { DATA_SOURCE_LABELS } from "./action-labels";
import { cn } from "@/lib/utils";
import type { QuestionAuditDetail } from "@/lib/api/types";
import { QuestionContentRenderer } from "@/components/question-content-renderer";

function renderValue(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[序列化异常]";
  }
}

function friendlyStatus(value: string | null | undefined): string {
  if (!value) return "—";
  const map: Record<string, string> = {
    approved: "已通过",
    pending: "待审核",
    rejected: "已拒绝",
    draft: "草稿",
  };
  return map[value] || value;
}

export function QuestionDetailCard({ qd }: { qd: QuestionAuditDetail }) {
  const isCurrentDb = qd.data_source === "current_database";
  const dataSourceLabel = DATA_SOURCE_LABELS[qd.data_source ?? ""] ?? qd.data_source;

  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold text-[var(--ink)]">题目详情</h4>

      {isCurrentDb ? (
        <p className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-light)] px-3 py-2 text-xs text-[#9b6f3b]">
          该内容来自当前题目数据，可能与日志发生时的内容不同。
        </p>
      ) : dataSourceLabel ? (
        <p className="rounded-lg border border-[var(--color-primary)]/30 bg-[var(--color-primary-light)] px-3 py-1.5 text-xs text-[var(--color-primary-dark)]">
          {dataSourceLabel}
        </p>
      ) : null}

      {/* Content / Stem — visually prominent */}
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
        <p className="mb-2 text-xs font-medium text-[var(--color-text-hint)]">题干</p>
        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[var(--color-text-primary)]">
          <QuestionContentRenderer content={qd.content} fallbackText={qd.content_text || renderValue(qd.content)} showTableMetadata />
        </div>
      </div>

      {/* Grid fields */}
      <div className="grid gap-3 sm:grid-cols-2">
        <FieldBlock label="题目 ID" value={qd.id != null ? String(qd.id) : "—"} mono />
        <FieldBlock label="科目" value={qd.subject_name ?? qd.subject_code ?? "—"} />
        <FieldBlock label="题型" value={qd.question_type ?? "—"} />
        <FieldBlock label="难度" value={qd.difficulty != null ? String(qd.difficulty) : "—"} />
        <FieldBlock label="年份" value={qd.year != null ? String(qd.year) : "—"} />
        <FieldBlock label="审核状态" value={friendlyStatus(qd.review_status)} />
        <FieldBlock
          label="启用状态"
          value={qd.is_active === null ? "—" : qd.is_active ? "启用" : "停用"}
        />
      </div>

      {/* Options */}
      {hasOptions(qd.options) && (
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-4">
          <p className="mb-2 text-xs font-medium text-[var(--color-text-hint)]">选项</p>
          <div className="space-y-1">
            {renderOptionsLines(qd.options)}
          </div>
        </div>
      )}

      {/* Answer */}
      {qd.answer != null && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--color-text-hint)]">答案</span>
          <span className="inline-flex items-center rounded-full border border-[var(--color-success)] bg-[var(--color-success-light)] px-2.5 py-0.5 text-xs font-semibold text-[var(--color-success)]">
            {renderValue(qd.answer)}
          </span>
        </div>
      )}

      {/* Analysis — collapsible if long */}
      {qd.analysis != null && (
        <CollapsibleBlock label="解析" content={renderValue(qd.analysis)} />
      )}

      {/* Knowledge points */}
      {qd.knowledge_points != null && (
        <FieldBlock label="知识点" value={renderValue(qd.knowledge_points)} />
      )}
    </section>
  );
}

function hasOptions(options: unknown): options is NonNullable<unknown> {
  return options != null;
}

function FieldBlock({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-3 py-2.5">
      <p className="text-xs font-medium text-[var(--color-text-hint)]">{label}</p>
      <p className={cn("mt-0.5 text-sm text-[var(--color-text-primary)]", mono && "font-mono text-xs")}>
        {value}
      </p>
    </div>
  );
}

function CollapsibleBlock({ label, content }: { label: string; content: string }) {
  return (
    <details className="group rounded-lg border border-[var(--color-border)] bg-white">
      <summary className="cursor-pointer px-3 py-2.5 text-xs font-medium text-[var(--color-text-hint)] transition-colors hover:text-[var(--ink)]">
        {label}
      </summary>
      <div className="border-t border-[var(--color-border)] px-3 py-2.5">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--color-text-secondary)]">
          {content}
        </pre>
      </div>
    </details>
  );
}

function renderOptionsLines(options: unknown): ReactNode {
  if (!options) return null;
  if (typeof options === "string") {
    return <p className="text-sm text-[var(--color-text-secondary)]">{options}</p>;
  }
  if (typeof options === "object") {
    if (Array.isArray(options)) {
      return options.map((opt, i) => {
        if (typeof opt === "string") return <OptionLine key={i} label={String.fromCharCode(65 + i)} text={opt} />;
        if (typeof opt === "object" && opt !== null) {
          const key = opt.key || String.fromCharCode(65 + i);
          const text = opt.text || opt.value || opt.label || JSON.stringify(opt);
          return <OptionLine key={i} label={key} text={text} />;
        }
        return <OptionLine key={i} label={String.fromCharCode(65 + i)} text={String(opt)} />;
      });
    }
    const obj = options as Record<string, unknown>;
    return Object.entries(obj).map(([key, val]) => (
      <OptionLine key={key} label={key} text={typeof val === "string" ? val : JSON.stringify(val)} />
    ));
  }
  return <p className="text-sm text-[var(--color-text-secondary)]">{String(options)}</p>;
}

function OptionLine({ label, text }: { label: string; text: string }) {
  return (
    <p className="text-sm text-[var(--color-text-secondary)]">
      <span className="font-mono text-xs font-semibold text-[var(--ink)]">{label}.</span> {text}
    </p>
  );
}
