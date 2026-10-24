"use client";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  FileText,
  Save,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import {
} from "@/lib/question-types";
import type { ImportQuestionItem } from "@/lib/api/types";
import type { OptionVisualModel } from "@/lib/option-visual-utils";
import type { SegmentData } from "@/lib/segment-utils";
import { getMultiBlankSaveState, type MultiBlankAction } from "./multi-blank-choice-utils";
import { isMultiBlankChoice, type EditState } from "../review-edit-state";
import { ReviewQuestionPreview } from "./review-question-preview";
import { ReviewAnswerPreview } from "./review-answer-preview";
import { ReviewSourceEvidence } from "./review-source-evidence";
import { ReviewJsonView } from "./review-json-view";
import { ReviewDrawerEditForm } from "./review-drawer-edit-form";
import type { useReviewSegmentDrag } from "../hooks/use-review-segment-drag";
import type { ReviewSubjectOption } from "../review-subject-state";

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "published") return "primary";
  return "warning";
}

function renderJson(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

type ReviewDetailDrawerProps = {
  open: boolean;
  item: ImportQuestionItem;
  editState: EditState;
  canWrite: boolean;
  detailView: "formatted" | "json";
  editing: boolean;
  subjectsLoading: boolean;
  subjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  leafSubjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  optionVisualModel: OptionVisualModel;
  completeSuggestion: unknown;
  answerSuggestion: string | null;
  answerSuggestionApplied: boolean;
  completePending: boolean;
  updatePending: boolean;
  previewDetailReady: boolean;
  segmentUploading: number;
  editedSegments: Array<SegmentData> | null;
  segmentDrag: ReturnType<typeof useReviewSegmentDrag>;
  segmentReplaceInputRef: React.RefObject<HTMLInputElement | null>;
  subjectEditDropdownOpen: boolean;
  subjectEditDropdownStyle: React.CSSProperties;
  subjectEditButtonRef: React.RefObject<HTMLButtonElement | null>;
  isBlockedByVisualIssues: boolean;
  onClose: () => void;
  onDetailViewChange: (view: "formatted" | "json") => void;
  onEditStateChange: (state: EditState) => void;
  onRuntimeIssue: (issue: string) => void;
  onApplyAnswerSuggestion: (answer: string) => void;
  onQuestionTypeChange: (code: string) => void;
  onSubjectDropdownOpenChange: (open: boolean) => void;
  onSubjectDropdownStyleChange: (style: React.CSSProperties) => void;
  onSegmentsChange: (segments: SegmentData[]) => void;
  onSegmentFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onSegmentReplace: (index: number) => void;
  onMultiBlankAction: (action: MultiBlankAction) => void;
  onStartEditing: () => void;
  onCancelEditing: () => void;
  onSave: () => void;
  onApprove: () => void;
  onReject: () => void;
  onComplete: () => void;
};

export function ReviewDetailDrawer({
  open,
  item,
  editState,
  canWrite,
  detailView,
  editing,
  subjectsLoading,
  subjectOptions,
  leafSubjectOptions,
  optionVisualModel,
  completeSuggestion,
  answerSuggestion,
  answerSuggestionApplied,
  completePending,
  updatePending,
  previewDetailReady,
  segmentUploading,
  editedSegments,
  segmentDrag,
  segmentReplaceInputRef,
  subjectEditDropdownOpen,
  subjectEditDropdownStyle,
  subjectEditButtonRef,
  isBlockedByVisualIssues,
  onClose,
  onDetailViewChange,
  onEditStateChange,
  onRuntimeIssue,
  onApplyAnswerSuggestion,
  onQuestionTypeChange,
  onSubjectDropdownOpenChange,
  onSubjectDropdownStyleChange,
  onSegmentsChange,
  onSegmentFileChange,
  onSegmentReplace,
  onMultiBlankAction,
  onStartEditing,
  onCancelEditing,
  onSave,
  onApprove,
  onReject,
  onComplete,
}: ReviewDetailDrawerProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.38)] backdrop-blur-[1px]" role="presentation" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-labelledby="drawer-title"
            className="flex h-full w-full max-w-3xl flex-col overflow-y-auto shadow-[var(--shadow-floating)] animate-slide-in bg-noise"
            style={{
              background: 'var(--color-bg)',
              backgroundImage: 'linear-gradient(var(--blueprint-line) 1px, transparent 1px), linear-gradient(90deg, var(--blueprint-line) 1px, transparent 1px), url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23n)\' opacity=\'0.025\'/%3E%3C/svg%3E")',
              backgroundSize: '24px 24px, 24px 24px, 128px 128px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* ===== Compact Status Bar ===== */}
            <div className="sticky top-0 z-10 border-b border-[var(--color-border)] bg-[var(--color-bg)]/90 px-4 py-2 backdrop-blur-xl">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-hint)]">#{item.id}</span>
                  <span className="h-3 w-px bg-[var(--color-border)]" />
                  <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
                  {item.risk_level === "high" ? (
                    <span className="risk-seal risk-seal-high !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 高风险</span>
                  ) : item.risk_level === "medium" ? (
                    <span className="risk-seal risk-seal-medium !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 需检查</span>
                  ) : item.risk_level === "low" ? (
                    <span className="risk-seal risk-seal-low !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 低风险</span>
                  ) : null}
                  {editState.subject_id ? (
                    <span className="hidden sm:inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">{subjectOptions.find((s) => s.id === editState.subject_id)?.name || `#${editState.subject_id}`}</span>
                  ) : null}
                  {/* ── 原题定位 ── */}
                  {item.source_question_no || item.source_image_seq != null ? (
                    <span className="hidden md:inline-flex items-center gap-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)]">
                      {item.source_image_seq != null ? `图${item.source_image_seq}` : null}
                      {item.source_image_seq != null && item.source_page_start != null ? " · " : null}
                      {item.source_page_start != null ? `第${item.source_page_start}页` : null}
                      {((item.source_image_seq != null || item.source_page_start != null) && item.source_question_no) ? " · " : null}
                      {item.source_question_no ? `原题${item.source_question_no}` : null}
                    </span>
                  ) : null}
                  {item.risk_reasons && item.risk_reasons.length > 0 ? (
                    <span className="hidden md:inline-block max-w-[200px] truncate text-[10px] text-red-600" title={item.risk_reasons.join("；")}>
                      {item.risk_reasons[0]}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {/* View toggle */}
                  <div className="flex overflow-hidden rounded-md border border-[var(--color-border)] bg-white/70">
                    <button type="button" className={`px-2 py-1 text-[10px] font-semibold transition ${detailView === "formatted" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => onDetailViewChange("formatted")}>文本</button>
                    <button type="button" className={`px-2 py-1 text-[10px] font-semibold transition ${detailView === "json" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => onDetailViewChange("json")}>JSON</button>
                  </div>
                  <button className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]" onClick={onClose}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>

            {/* ===== Content (main focus) ===== */}
            <div className="relative flex-1 px-6 py-5 space-y-5">
              {completePending ? (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--color-bg)]/70 backdrop-blur-sm">
                  <div className="flex flex-col items-center gap-5">
                    {/* Ink spread animation */}
                    <div className="relative flex items-center justify-center">
                      <div className="absolute h-20 w-20 rounded-full border border-[var(--color-primary)]/10 animate-ink-spread" />
                      <div className="absolute h-14 w-14 rounded-full border border-[var(--color-primary)]/20 animate-ink-spread" style={{ animationDelay: "0.3s" }} />
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-[0_0_20px_rgba(91,123,154,0.15)]">
                        <Sparkles className="h-5 w-5 text-[var(--color-primary)]" />
                      </div>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--color-text-secondary)]">AI 正在审校</p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">分析题目结构，生成补全建议</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {detailView === "formatted" && !editing ? (
                <>
                  <ReviewQuestionPreview
                    content={item.parsed_content}
                    draft={editState}
                    visualModel={optionVisualModel}
                    onRuntimeIssue={(issue) => onRuntimeIssue(issue)}
                  />

                  {/* ── Answer Card ── */}
                  <ReviewAnswerPreview item={item} draft={editState} />

                  {/* ── OCR Raw Data ── */}
                  <ReviewSourceEvidence raw_data={item.raw_data} parsed_content={item.parsed_content} />

                  {/* ── AI Suggestion Stamp ── */}
                  {completeSuggestion ? (
                    <section className="animate-fade-up drawer-section-delay-5 section-scroll section-scroll-ink rounded-2xl border border-[var(--color-primary)]/20 bg-gradient-to-br from-[var(--color-primary-light)]/60 to-white/90 p-5 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-primary)] shadow-sm">
                            <Sparkles className="h-4 w-4 text-white" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-[var(--color-primary-dark)]">AI 补全建议</p>
                            <p className="text-[10px] text-[var(--color-text-hint)]">由语言模型自动生成，请复核后采纳</p>
                          </div>
                        </div>
                        {answerSuggestion ? (
                          <button
                            type="button"
                            disabled={!canWrite || answerSuggestionApplied}
                            onClick={() => {
                              if (!canWrite || answerSuggestionApplied) return;
                              onApplyAnswerSuggestion(answerSuggestion);
                            }}
                            className={cn(
                              "inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold shadow-sm transition",
                              answerSuggestionApplied
                                ? "cursor-not-allowed border-emerald-200 bg-emerald-50 text-emerald-700 opacity-80"
                                : "border-[var(--color-primary)]/30 bg-white text-[var(--color-primary-dark)] hover:bg-[var(--color-primary)] hover:text-white",
                            )}
                          >
                            {answerSuggestionApplied ? <Check className="h-3 w-3" /> : null}
                            {answerSuggestionApplied ? "已应用" : "应用答案"}
                          </button>
                        ) : null}
                      </div>
                      <div className="mt-3 rounded-xl border border-[var(--color-primary)]/10 bg-white/80 p-3">
                        <pre className="max-h-36 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(completeSuggestion)}</pre>
                      </div>
                    </section>
                  ) : null}
                </>
              ) : detailView === "json" && !editing ? (
                /* ── JSON View ── */
                <ReviewJsonView item={item} />
              ) : (
                <ReviewDrawerEditForm
                  editState={editState}
                  canWrite={canWrite}
                  subjectsLoading={subjectsLoading}
                  subjectOptions={subjectOptions}
                  leafSubjectOptions={leafSubjectOptions}
                  optionVisualModel={optionVisualModel}
                  completeSuggestion={completeSuggestion}
                  answerSuggestion={answerSuggestion}
                  answerSuggestionApplied={answerSuggestionApplied}
                  segmentUploading={segmentUploading}
                  editedSegments={editedSegments}
                  segmentDrag={segmentDrag}
                  segmentReplaceInputRef={segmentReplaceInputRef}
                  subjectEditDropdownOpen={subjectEditDropdownOpen}
                  subjectEditDropdownStyle={subjectEditDropdownStyle}
                  subjectEditButtonRef={subjectEditButtonRef}
                  onEditStateChange={onEditStateChange}
                  onRuntimeIssue={onRuntimeIssue}
                  onApplyAnswerSuggestion={onApplyAnswerSuggestion}
                  onQuestionTypeChange={onQuestionTypeChange}
                  onSubjectDropdownOpenChange={onSubjectDropdownOpenChange}
                  onSubjectDropdownStyleChange={onSubjectDropdownStyleChange}
                  onSegmentsChange={onSegmentsChange}
                  onSegmentFileChange={onSegmentFileChange}
                  onSegmentReplace={onSegmentReplace}
                  onMultiBlankAction={onMultiBlankAction}
                />
              )}
              {/* ===== Sticky Bottom Footer ===== */}
              {!editing ? (
                <div className="sticky bottom-0 z-10 border-t border-[var(--color-border)] bg-[var(--color-bg)]/90 px-4 py-3 backdrop-blur-xl">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <Button variant="primary" className="h-8 px-3.5 text-xs" disabled={!canWrite || item.status === "published" || isBlockedByVisualIssues} onClick={() => onApprove()}>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        通过
                      </Button>
                      <Button variant="danger" className="h-8 px-3.5 text-xs" disabled={!canWrite || item.status === "published"} onClick={() => onReject()}>
                        <XCircle className="h-3.5 w-3.5" />
                        驳回
                      </Button>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        disabled={!canWrite || completePending || item.status !== "pending"}
                        onClick={() => {
                          if (canWrite) onComplete();
                        }}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold tracking-wider transition-all ${
                          completePending
                            ? "bg-[var(--color-primary)]/10 text-[var(--color-primary-dark)] cursor-wait"
                            : "bg-[var(--color-primary)]/10 text-[var(--color-primary-dark)] hover:bg-[var(--color-primary)] hover:text-white disabled:opacity-40 disabled:pointer-events-none"
                        }`}
                      >
                        {completePending ? (
                          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--color-primary)] border-t-transparent" />
                        ) : (
                          <Sparkles className="h-3 w-3" />
                        )}
                        {completePending ? "审校中" : "AI 审校"}
                      </button>
                      <Button className="h-8 px-3 text-xs" variant="secondary" disabled={!canWrite || !previewDetailReady || segmentUploading >= 0} onClick={onStartEditing}>
                        <FileText className="h-3.5 w-3.5" />
                        编辑
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (() => {
                const mb = isMultiBlankChoice(editState.question_type) ? (editState.multiBlank ?? null) : null;
                const saveState = mb && mb.groups.length >= 2
                  ? getMultiBlankSaveState(mb.groups, mb.answerMap, mb.dedupWarnings, mb.dedupErrors, mb.hasUnappliedDraft)
                  : null;
                const canSave = saveState ? saveState.canSave : true;
                return (
                <div className="sticky bottom-0 z-10 border-t border-[var(--color-border)] bg-[var(--color-bg)]/90 px-4 py-3 backdrop-blur-xl">
                  {saveState && saveState.errors.length > 0 ? (
                    <div className="mb-3 rounded-xl border border-red-200/50 bg-red-50/70 p-3">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-400"><AlertTriangle className="h-3 w-3" /></span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[11px] font-medium text-red-700">无法保存，请先处理以下问题</p>
                          <ol className="mt-1.5 list-inside list-decimal space-y-0.5">
                            {saveState.errors.map((err, i) => (
                              <li key={i} className="text-[10px] text-red-600">{err}</li>
                            ))}
                          </ol>
                        </div>
                      </div>
                      {saveState.warnings.length > 0 ? (
                        <div className="mt-2 border-t border-red-200/30 pt-2">
                          {saveState.warnings.map((w, i) => (
                            <p key={i} className="text-[10px] text-amber-600">{w}</p>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="flex items-center justify-end gap-2">
                    <Button className="h-8 px-3 text-xs" variant="ghost" onClick={onCancelEditing}>
                      <X className="h-3.5 w-3.5" />
                      取消
                    </Button>
                    <Button className="h-8 px-3 text-xs" variant="primary" disabled={!canWrite || !canSave || updatePending || item.status === "published"} onClick={() => {
                      if (canWrite) onSave();
                    }}>
                      <Save className="h-3.5 w-3.5" />
                      {updatePending ? "保存中..." : "保存"}
                    </Button>
                  </div>
                </div>
                );
              })()}
            </div>
      </aside>
    </div>
  );
}
