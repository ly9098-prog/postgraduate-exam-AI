"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ListPlus, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type { AdminQuestion } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type ParsedQuickOption = { key: string; text: string; conflict: boolean; invalid: boolean };

function nextFreeLetter(used: Set<string>): string | null {
  for (let i = 0; i < 26; i++) {
    const letter = String.fromCharCode(65 + i);
    if (!used.has(letter)) return letter;
  }
  return null;
}

/** Parse pasted option lines, mirroring the backend auto letter-assignment. */
export function parseQuickOptions(
  text: string,
  existingKeys: string[],
): ParsedQuickOption[] {
  const used = new Set(existingKeys.map((key) => String(key).trim().toUpperCase()).filter(Boolean));
  const result: ParsedQuickOption[] = [];
  const lines = text
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);
  for (const line of lines) {
    const labeled = line.match(/^([A-Za-z])\s*[.。．、，,:：)）]\s*(.*)$/);
    if (labeled) {
      const key = labeled[1].toUpperCase();
      const optionText = labeled[2].trim();
      result.push({ key, text: optionText, conflict: used.has(key), invalid: !optionText });
      used.add(key);
    } else {
      const key = nextFreeLetter(used);
      if (!key) {
        result.push({ key: "?", text: line, conflict: true, invalid: false });
        used.add("?");
        continue;
      }
      result.push({ key, text: line, conflict: false, invalid: false });
      used.add(key);
    }
  }
  return result;
}

type QuickAddOptionsProps = {
  questionId: number;
  existingKeys: string[];
  disabled?: boolean;
  /** Set when the parent edit form has unsaved changes → confirm before writing. */
  dirty?: boolean;
  /** Persist the parent edit form before the immediate option mutation. */
  beforeDirtyMutation?: () => Promise<boolean>;
  onMutated: (question: AdminQuestion) => void;
};

/** Bulk-paste options editor that writes immediately via POST /questions/{id}/options. */
export function QuickAddOptions({
  questionId,
  existingKeys,
  disabled = false,
  dirty = false,
  beforeDirtyMutation,
  onMutated,
}: QuickAddOptionsProps) {
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmWrite, setConfirmWrite] = useState(false);

  const parsed = useMemo(() => parseQuickOptions(text, existingKeys), [text, existingKeys]);
  const hasConflict = parsed.some((p) => p.conflict);
  const hasInvalid = parsed.some((p) => p.invalid);
  const hasText = parsed.length > 0;

  const add = async () => {
    setError(null);
    if (!hasText || hasConflict || hasInvalid) return;
    setBusy(true);
    try {
      const question = await apiRequest<AdminQuestion>(`/questions/${questionId}/options`, {
        method: "POST",
        body: JSON.stringify({
          options: parsed.map((p) => ({ key: p.key, text: p.text })),
          edit_reason: "快捷添加选项",
        }),
        headers: { "Content-Type": "application/json" },
      });
      onMutated(question);
      setText("");
      setExpanded(false);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const prepareParentIfNeeded = async (): Promise<boolean> => {
    if (!dirty) return true;
    if (!beforeDirtyMutation) {
      setError("请先保存当前题目修改，再添加选项。");
      return false;
    }
    setPreparing(true);
    try {
      return await beforeDirtyMutation();
    } catch (err) {
      setError(getErrorMessage(err));
      return false;
    } finally {
      setPreparing(false);
    }
  };

  const handleAdd = () => {
    if (disabled) return;
    if (dirty) {
      setConfirmWrite(true);
      return;
    }
    void add();
  };

  const confirmAdd = async () => {
    const ready = await prepareParentIfNeeded();
    if (!ready) {
      setConfirmWrite(false);
      return;
    }
    setConfirmWrite(false);
    await add();
  };

  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3.5 py-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={disabled}
        className="flex w-full items-center justify-between gap-2 text-left text-slate-600 transition hover:text-slate-900"
      >
        <span className="flex items-center gap-2 text-xs font-medium">
          <ListPlus className="h-4 w-4 text-slate-400" />
          快捷添加选项
        </span>
        <ChevronDown
          className={cn("h-4 w-4 text-[var(--color-text-hint)] transition-transform", expanded && "rotate-180")}
        />
      </button>

      {expanded ? (
        <div className="mt-3 space-y-3">
          <div>
            <textarea
              className="min-h-24 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs leading-5 text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              placeholder={"每行一个选项，例如：\nA. 首项内容\n第二项内容（自动分配字母）"}
              value={text}
              disabled={busy || preparing || disabled}
              onChange={(e) => setText(e.target.value)}
            />
            <p className="mt-1 text-[10px] text-[var(--color-text-hint)]">
              A./B./C. 前缀保留为字母键；无前缀自动分配下一个字母。
            </p>
          </div>

          {hasText ? (
            <div className="flex flex-wrap gap-1.5">
              {parsed.map((p, i) => (
                <span
                  key={`${p.key}-${i}`}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs",
                    p.conflict || p.invalid
                      ? "border-red-300 bg-red-50 text-red-600"
                      : "border-[var(--color-border)]/60 bg-white/70 text-[var(--color-text-secondary)]",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-4 w-4 items-center justify-center rounded text-[9px] font-bold",
                      p.conflict || p.invalid ? "bg-red-100 text-red-600" : "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]",
                    )}
                  >
                    {p.key}
                  </span>
                  <span className="max-w-48 truncate">{p.text}</span>
                </span>
              ))}
            </div>
          ) : null}

          {disabled ? (
            <p className="text-xs text-amber-700" role="status">
              当前题型不支持选项；请切换为单选题或多选题后再添加。
            </p>
          ) : null}

          {hasConflict ? (
            <p className="text-xs text-red-600" role="alert">
              存在与已有选项重复的键，请调整后重试。
            </p>
          ) : null}
          {hasInvalid ? (
            <p className="text-xs text-red-600" role="alert">
              存在只有选项字母、没有正文的空选项，请补充内容后再添加。
            </p>
          ) : null}
          {error ? (
            <p className="text-xs text-red-600" role="alert">
              {error}
            </p>
          ) : null}

          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={disabled || busy || preparing || !hasText || hasConflict || hasInvalid}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              添加到题目
            </Button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmWrite}
        title="确认添加选项"
        description="当前表单有未保存修改。继续后会先保存这些修改，再添加选项；保存失败则不会添加。"
        confirmText="保存并继续"
        loading={busy || preparing}
        onConfirm={confirmAdd}
        onCancel={() => setConfirmWrite(false)}
      />
    </div>
  );
}
