import type { AdminQuestion, AdminQuestionImportSummary } from "@/lib/api/types";

type QuestionWithImport = AdminQuestion & {
  import_record?: AdminQuestionImportSummary | null;
};

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-2">
      <p className="text-[11px] text-[var(--color-text-hint)]">{label}</p>
      <p className="mt-1 break-words text-sm font-medium text-[var(--color-text-secondary)]">
        {value}
      </p>
    </div>
  );
}

function ImportRecordDetails({ importRecord }: { importRecord: AdminQuestionImportSummary }) {
  return (
    <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <p className="text-[11px] text-[var(--color-text-hint)]">题目 hash</p>
          <p className="mt-1 break-all font-mono text-xs text-[var(--color-text-secondary)]">
            {importRecord.question_hash || "—"}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-[var(--color-text-hint)]">正式题关联</p>
          <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
            {importRecord.duplicate_of_question_id
              ? `#${importRecord.duplicate_of_question_id}`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-[11px] text-[var(--color-text-hint)]">导入项关联</p>
          <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
            {importRecord.duplicate_of_import_id
              ? `#${importRecord.duplicate_of_import_id}`
              : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}

export function QuestionSecondaryInfo({ question }: { question: QuestionWithImport }) {
  const importRecord = question.import_record;
  return (
    <details className="rounded-2xl border border-[var(--color-border)] bg-white/55 p-4 text-sm">
      <summary className="cursor-pointer list-none">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-semibold text-[var(--ink)]">辅助信息</p>
            <p className="mt-1 text-xs text-[var(--color-text-hint)]">
              科目、年份、启用状态与导入关联信息
            </p>
          </div>
        </div>
      </summary>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <InfoRow label="科目" value={question.subject_name || question.subject_code || "—"} />
        <InfoRow label="年份" value={String(question.year || "—")} />
        <InfoRow label="启用状态" value={question.is_active ? "启用" : "停用"} />
        <InfoRow label="题目 ID" value={`#${question.id}`} />
      </div>
      {importRecord ? <ImportRecordDetails importRecord={importRecord} /> : null}
    </details>
  );
}
