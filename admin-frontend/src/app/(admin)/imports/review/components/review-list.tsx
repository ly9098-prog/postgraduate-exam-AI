"use client";

import { Check, CheckCircle2, Eye, XCircle } from "lucide-react";
import type { ImportQuestionItem } from "@/lib/api/types";
import {
  canonicalizeQuestionType,
  getQuestionTypeLabel,
  getQuestionTypeShortLabel,
} from "@/lib/question-types";
import { textFromImport } from "../review-edit-state";
import { getReviewListBadges, getReviewTableBadges } from "../review-queue-badges";
import { getSourceLocator, getSourceQuestionNo } from "../review-source-location";

type ReviewAction = "approve" | "reject";

type ReviewListProps = {
  viewMode: "list" | "table";
  items: ImportQuestionItem[];
  selectedIds: Set<number>;
  allChecked: boolean;
  canWrite: boolean;
  quickAnswerDrafts: Record<number, string>;
  quickAnswerPending: boolean;
  verifyAnswerPending: boolean;
  onToggleAll: () => void;
  onToggleOne: (id: number) => void;
  onOpenPreview: (item: ImportQuestionItem) => void;
  onQuickAnswerDraftChange: (id: number, answer: string) => void;
  onQuickAnswerDraftReset: (id: number) => void;
  onQuickAnswerSave: (id: number, answer: string) => void;
  onVerifyAnswer: (id: number) => void;
  onReviewAction: (action: ReviewAction, id: number) => void;
};

export function ReviewList({
  viewMode,
  items,
  selectedIds,
  allChecked,
  canWrite,
  quickAnswerDrafts,
  quickAnswerPending,
  verifyAnswerPending,
  onToggleAll,
  onToggleOne,
  onOpenPreview,
  onQuickAnswerDraftChange,
  onQuickAnswerDraftReset,
  onQuickAnswerSave,
  onVerifyAnswer,
  onReviewAction,
}: ReviewListProps) {
  if (items.length === 0) return null;

  return (
    <>
      {items.length > 0 && viewMode === "table" ? (
                <div className="w-full overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
                  <table className="w-full table-fixed text-[11px]">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-input)]/50">
                        <th className="w-9 px-2.5 py-2 text-left font-semibold text-[var(--color-text-secondary)]">
                          <label className="group/cb relative flex cursor-pointer items-center justify-center">
                            <span className="flex h-[16px] w-[16px] items-center justify-center rounded border-2 border-[var(--color-border)] bg-white transition-all group-hover/cb:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                              <input type="checkbox" checked={allChecked} onChange={onToggleAll} className="peer absolute inset-0 cursor-pointer opacity-0" />
                              <Check className="h-2.5 w-2.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                            </span>
                          </label>
                        </th>
                        <th className="w-[56px] px-2 py-2 text-left font-semibold text-[var(--color-text-secondary)]">题号</th>
                        <th className="w-[100px] px-2 py-2 text-left font-semibold text-[var(--color-text-secondary)]">来源</th>
                        <th className="px-2 py-2 text-left font-semibold text-[var(--color-text-secondary)]">题干</th>
                        <th className="w-[60px] px-2 py-2 text-center font-semibold text-[var(--color-text-secondary)]">题型</th>
                        <th className="w-[132px] px-2 py-2 text-center font-semibold text-[var(--color-text-secondary)]">答案</th>
                        <th className="w-[72px] px-2 py-2 text-center font-semibold text-[var(--color-text-secondary)]">状态</th>
                        <th className="w-[52px] px-2 py-2 text-center font-semibold text-[var(--color-text-secondary)]">风险</th>
                        <th className="w-[136px] px-2 py-2 text-center font-semibold text-[var(--color-text-secondary)]">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item, index) => {
                        const { answerStatusLabel, answerStatusStyle, riskLabel, riskStyle } = getReviewTableBadges(item);
                        const srcNo = getSourceQuestionNo(item);
                        const questionTypeCode = canonicalizeQuestionType(item.question_type);
                        const isSingleChoice = questionTypeCode === "single_choice";
                        const isMultiChoice = questionTypeCode === "multiple_choice";
                        const isTrueFalse = questionTypeCode === "true_false";
                        const draftAnswer = quickAnswerDrafts[item.id] ?? item.parsed_answer ?? "";
                        const hasDraftChanged = draftAnswer !== (item.parsed_answer ?? "");
                        const sourceLocator = getSourceLocator(item);
                        const stemText = item.content_preview || textFromImport(item) || "—";
                        const typeLabel = getQuestionTypeLabel(item.question_type);
                        const shortTypeLabel = getQuestionTypeShortLabel(item.question_type);
                        return (
                          <tr key={item.id} className={`border-b border-[var(--color-border)]/40 transition-colors hover:bg-[var(--color-bg-input)]/30 ${index % 2 === 0 ? "bg-white" : "bg-[var(--color-bg-input)]/20"}`}>
                            <td className="px-2.5 py-2">
                              <label className="group/cb relative flex cursor-pointer items-center justify-center">
                                <span className="flex h-[16px] w-[16px] items-center justify-center rounded border-2 border-[var(--color-border)] bg-white transition-all group-hover/cb:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                                  <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => onToggleOne(item.id)} className="peer absolute inset-0 cursor-pointer opacity-0" />
                                  <Check className="h-2.5 w-2.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                                </span>
                              </label>
                            </td>
                            <td className="w-[56px] px-2 py-2">
                              <span className="block min-w-0 truncate font-mono text-[11px] font-medium text-[var(--color-text-secondary)]" title={srcNo || ""}>{srcNo || "—"}</span>
                            </td>
                            <td className="w-[100px] px-2 py-2">
                              <span className="block min-w-0 truncate text-[10px] text-[var(--color-text-hint)]" title={sourceLocator}>{sourceLocator || "—"}</span>
                            </td>
                            <td className="px-2 py-2">
                              <span className="block min-w-0 truncate text-[11px] text-[var(--ink)]" title={stemText}>{stemText}</span>
                            </td>
                            <td className="w-[60px] px-2 py-2 text-center">
                              <span className="block min-w-0 truncate text-[10px] text-[var(--color-text-hint)]" title={typeLabel}>{shortTypeLabel}</span>
                            </td>
                            <td className="w-[132px] px-2 py-2 text-center">
                              {isSingleChoice ? (
                                <div className="grid w-full grid-cols-4 gap-1">
                                  {["A","B","C","D"].map((opt) => (
                                    <button
                                      key={opt}
                                      onClick={() => onQuickAnswerDraftChange(item.id, draftAnswer === opt ? "" : opt)}
                                      disabled={!canWrite}
                                      className={`h-6 min-w-0 rounded text-[10px] font-bold transition border ${
                                        draftAnswer === opt
                                          ? "bg-[var(--color-primary)] text-white border-[var(--color-primary)]"
                                          : "bg-white text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-primary)]"
                                      }`}
                                    >
                                      {opt}
                                    </button>
                                  ))}
                                </div>
                              ) : isTrueFalse ? (
                                <div className="flex items-center justify-center gap-1">
                                  {["T","F"].map((opt) => (
                                    <button
                                      key={opt}
                                      onClick={() => onQuickAnswerDraftChange(item.id, draftAnswer === opt ? "" : opt)}
                                      disabled={!canWrite}
                                      className={`h-6 shrink-0 rounded px-2 text-[10px] font-bold transition border ${
                                        draftAnswer === opt
                                          ? "bg-[var(--color-primary)] text-white border-[var(--color-primary)]"
                                          : "bg-white text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-primary)]"
                                      }`}
                                    >
                                      {opt === "T" ? "正确" : "错误"}
                                    </button>
                                  ))}
                                </div>
                              ) : (
                                <input
                                  className="h-6 w-full rounded border border-[var(--color-border)] bg-white px-1.5 text-center text-[10px] font-mono font-bold outline-none transition focus:border-[var(--color-primary)]"
                                  value={draftAnswer}
                                  onChange={(e) => onQuickAnswerDraftChange(item.id, e.target.value)}
                                  placeholder={isMultiChoice ? "如 AC" : "答案"}
                                  disabled={!canWrite}
                                />
                              )}
                            </td>
                            <td className="w-[72px] px-2 py-2 text-center">
                              <span className="block min-w-0 truncate text-[10px]" style={answerStatusStyle} title={answerStatusLabel}>{answerStatusLabel}</span>
                            </td>
                            <td className="w-[52px] px-2 py-2 text-center">
                              <span className="block min-w-0 truncate text-[10px]" style={riskStyle}>{riskLabel}</span>
                            </td>
                            <td className="w-[136px] px-2 py-2 text-center">
                              <div className="inline-flex w-[124px] items-center justify-end gap-1">
                                <button className="w-9 rounded border border-[var(--color-border)] bg-white px-1 py-1 text-[9px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]" onClick={() => onOpenPreview(item)} title="查看详情">查</button>
                                <button
                                  onClick={() => {
                                    if (canWrite) onQuickAnswerSave(item.id, draftAnswer);
                                  }}
                                  disabled={!canWrite || quickAnswerPending || !hasDraftChanged}
                                  className={`w-9 rounded border px-1 py-1 text-[9px] font-semibold transition-opacity duration-150 ${
                                    hasDraftChanged
                                      ? "visible opacity-100 border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                                      : "invisible opacity-0 border-transparent"
                                  }`}
                                  title="保存答案"
                                >
                                  存
                                </button>
                                <button
                                  className={`w-9 rounded border px-1 py-1 text-[9px] font-semibold transition-opacity duration-150 ${
                                    hasDraftChanged
                                      ? "visible opacity-100 border-[var(--color-border)] bg-white text-[var(--color-text-secondary)]"
                                      : "invisible opacity-0 border-transparent"
                                  }`}
                                  onClick={() => onQuickAnswerDraftReset(item.id)}
                                  title="取消编辑"
                                >
                                  消
                                </button>
                                <button
                                  onClick={() => {
                                    if (canWrite) onVerifyAnswer(item.id);
                                  }}
                                  disabled={!canWrite || verifyAnswerPending || !item.parsed_answer}
                                  className={`w-9 rounded border px-1 py-1 text-[9px] font-semibold transition-opacity duration-150 ${
                                    item.parsed_answer
                                      ? "visible opacity-100 border-[var(--color-success)] bg-[var(--color-success-light)] text-[var(--color-success)] hover:bg-[var(--color-success)] hover:text-white"
                                      : "invisible opacity-0 border-transparent"
                                  }`}
                                  title="确认答案"
                                >
                                  确
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {items.length > 0 && viewMode === "list" ? (
              <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
                <div className="flex items-center gap-3 border-b border-[var(--color-border)]/50 px-3.5 py-2">
                  <label className="group/cb relative flex cursor-pointer items-center gap-2">
                    <span className="flex h-[16px] w-[16px] items-center justify-center rounded border-2 border-[var(--color-border)] bg-white transition-all group-hover/cb:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                      <input type="checkbox" checked={allChecked} onChange={onToggleAll} className="peer absolute inset-0 cursor-pointer opacity-0" />
                      <Check className="h-2.5 w-2.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                    </span>
                    <span className="text-xs text-[var(--color-text-secondary)]">全选本页</span>
                  </label>
                </div>
                {items.map((item, index) => {
                  const { riskColor, hasAnswerMissing, reasonCount, sourceLabel, answerStatusLabel, answerStatusColor } = getReviewListBadges(item);

                  return (
                    <div key={item.id}>
                      {index > 0 && <div className="h-px bg-[var(--color-border)]/50" />}
                      <div
                        className="group flex items-center gap-2.5 px-3.5 py-2.5 transition-colors hover:bg-[var(--color-bg-input)]/40"
                      >
                        {/* Risk dot */}
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: riskColor }} />

                        {/* Checkbox */}
                        <label className="group/cb relative flex shrink-0 cursor-pointer items-center justify-center">
                          <span className="flex h-[18px] w-[18px] items-center justify-center rounded border-2 border-[var(--color-border)] bg-white transition-all group-hover/cb:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                            <input
                              type="checkbox"
                              checked={selectedIds.has(item.id)}
                              onChange={() => onToggleOne(item.id)}
                              className="peer absolute inset-0 cursor-pointer opacity-0"
                            />
                            <Check className="h-3 w-3 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                          </span>
                        </label>

                        {/* ID */}
                        <span className="w-[38px] shrink-0 font-mono text-[11px] text-[var(--color-text-hint)]">#{item.id}</span>

                        {/* Subject */}
                        {item.subject_name || item.subject_code ? (
                          <span className="shrink-0 rounded bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">
                            {item.subject_name || item.subject_code}
                          </span>
                        ) : (
                          <span className="w-9 shrink-0 text-center text-[10px] text-[var(--color-text-hint)]">未分类</span>
                        )}

                        {/* Type */}
                        <span className="w-6 shrink-0 text-center text-[10px] text-[var(--color-text-hint)]">
                          {getQuestionTypeLabel(item.question_type)}
                        </span>

                        {/* Source question badge */}
                        {sourceLabel ? (
                          <span className="shrink-0 rounded bg-[var(--color-bg-input)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)]">{sourceLabel}</span>
                        ) : null}

                        {/* Stem (truncated single line) */}
                        <p className="min-w-0 flex-1 cursor-pointer truncate text-[13px] leading-snug text-[var(--ink)]" onClick={() => onOpenPreview(item)}>
                          {item.content_preview || textFromImport(item) || <span className="italic text-xs text-[var(--color-text-hint)]">导入题目 #{item.id}</span>}
                        </p>

                        {/* Flags */}
                        <div className="flex shrink-0 items-center gap-1">
                          {item.risk_level === "high" && (
                            <span className="rounded bg-[#fef2f2] px-1.5 py-0.5 text-[9px] font-semibold text-[#b03a3a]">高风险</span>
                          )}
                          {item.risk_level === "medium" && (
                            <span className="rounded bg-[#fffbeb] px-1.5 py-0.5 text-[9px] font-semibold text-[#b87a30]">需检查</span>
                          )}
                          {answerStatusLabel ? (
                            <span className="rounded bg-white px-1.5 py-0.5 text-[9px] font-semibold border" style={{ color: answerStatusColor, borderColor: answerStatusColor }}>{answerStatusLabel}</span>
                          ) : null}
                          {hasAnswerMissing && !answerStatusLabel && (
                            <span className="rounded bg-[#fef2f2] px-1.5 py-0.5 text-[9px] font-semibold text-[#b03a3a]">无答案</span>
                          )}
                          {item.ai_answer_flag && !answerStatusLabel && (
                            <span className="rounded bg-[#fef7f0] px-1.5 py-0.5 text-[9px] font-semibold text-[#c46a3a]">AI</span>
                          )}
                          {item.duplicate_status === "possible_duplicate" && (
                            <span className="rounded bg-[#fffbeb] px-1.5 py-0.5 text-[9px] font-semibold text-[#b87a30]">疑似重复</span>
                          )}
                          {reasonCount > 0 && (
                            <span className="rounded bg-[var(--color-bg-input)] px-1.5 py-0.5 text-[9px] text-[var(--color-text-hint)]" title={item.risk_reasons?.join("；")}>
                              ⚠ {reasonCount}
                            </span>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            className="grid h-7 w-7 place-items-center rounded-md border border-[var(--color-border)] bg-white text-[11px] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]"
                            onClick={() => onOpenPreview(item)}
                            title="预览详情"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="flex h-7 items-center gap-1 rounded-md border border-[var(--color-success)] bg-[var(--color-success-light)] px-2.5 text-[10px] font-semibold text-[var(--color-success)] transition-colors hover:bg-[var(--color-success)] hover:text-white disabled:opacity-30"
                            disabled={!canWrite || item.status === "published"}
                            onClick={() => onReviewAction("approve", item.id)}
                          >
                            <CheckCircle2 className="h-3 w-3" />
                            通过
                          </button>
                          <button
                            className="flex h-7 items-center gap-1 rounded-md border border-[var(--color-danger)] bg-white px-2.5 text-[10px] font-semibold text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)] hover:text-white disabled:opacity-30"
                            disabled={!canWrite || item.status === "published"}
                            onClick={() => onReviewAction("reject", item.id)}
                          >
                            <XCircle className="h-3 w-3" />
                            驳回
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
      ) : null}
    </>
  );
}
