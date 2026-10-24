"use client";

import { createPortal } from "react-dom";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import { cn } from "@/lib/utils";
import {
  QUESTION_TYPE_OPTIONS,
  canonicalizeQuestionType,
  formatUnknownType,
} from "@/lib/question-types";
import type { OptionVisualModel } from "@/lib/option-visual-utils";
import type { SegmentData } from "@/lib/segment-utils";
import type { MultiBlankAction } from "./multi-blank-choice-utils";
import type { EditState } from "../review-edit-state";
import type { ReviewSubjectOption } from "../review-subject-state";
import type { useReviewSegmentDrag } from "../hooks/use-review-segment-drag";
import { ReviewStemEditor } from "./review-stem-editor";
import { ReviewVisualSegmentEditor } from "./review-visual-segment-editor";
import { ReviewOptionEditor } from "./review-option-editor";
import { ReviewAnswerEditor } from "./review-answer-editor";

function renderJson(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

type ReviewDrawerEditFormProps = {
  editState: EditState;
  canWrite: boolean;
  subjectsLoading: boolean;
  subjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  leafSubjectOptions: Array<ReviewSubjectOption & { code: string; name: string }>;
  optionVisualModel: OptionVisualModel;
  completeSuggestion: unknown;
  answerSuggestion: string | null;
  answerSuggestionApplied: boolean;
  segmentUploading: number;
  editedSegments: SegmentData[] | null;
  segmentDrag: ReturnType<typeof useReviewSegmentDrag>;
  segmentReplaceInputRef: React.RefObject<HTMLInputElement | null>;
  subjectEditDropdownOpen: boolean;
  subjectEditDropdownStyle: React.CSSProperties;
  subjectEditButtonRef: React.RefObject<HTMLButtonElement | null>;
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
};

export function ReviewDrawerEditForm({
  editState,
  canWrite,
  subjectsLoading,
  subjectOptions,
  leafSubjectOptions,
  optionVisualModel,
  completeSuggestion,
  answerSuggestion,
  answerSuggestionApplied,
  segmentUploading,
  editedSegments,
  segmentDrag,
  segmentReplaceInputRef,
  subjectEditDropdownOpen,
  subjectEditDropdownStyle,
  subjectEditButtonRef,
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
}: ReviewDrawerEditFormProps) {
  return (
    <div className="space-y-5 pb-16">
                  {/* Subject / Type */}
                  <div className="grid gap-3 md:grid-cols-2 animate-fade-up drawer-section-delay-1">
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
                        科目
                      </label>
                      <div className="relative">
                        <button
                          ref={subjectEditButtonRef}
                          type="button"
                          className="flex h-11 w-full items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-sm text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20"
                          onClick={() => {
                            const next = !subjectEditDropdownOpen;
                            onSubjectDropdownOpenChange(next);
                            if (next && subjectEditButtonRef.current) {
                              const r = subjectEditButtonRef.current.getBoundingClientRect();
                              const maxRight = window.innerWidth - 16;
                              const w = Math.min(r.width, maxRight - 16);
                              onSubjectDropdownStyleChange({ top: r.bottom + 4, left: Math.min(r.left, maxRight - w), width: w });
                            }
                          }}
                          onBlur={() => setTimeout(() => onSubjectDropdownOpenChange(false), 150)}
                        >
                          <span className={`min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-left ${editState.subject_id ? "" : "text-[var(--color-text-hint)]"}`} title={editState.subject_id ? (subjectOptions.find((s) => s.id === editState.subject_id)?.name || "") : ""}>
                            {editState.subject_id
                              ? (subjectOptions.find((s) => s.id === editState.subject_id)?.name || `#${editState.subject_id}`)
                              : "选择科目"}
                          </span>
                          {subjectsLoading ? (
                            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-primary)]" />
                          ) : (
                            <ChevronDown className={`h-4 w-4 text-[var(--color-text-hint)] transition-transform ${subjectEditDropdownOpen ? "rotate-180" : ""}`} />
                          )}
                        </button>
                        {subjectEditDropdownOpen ? createPortal(
                          <div className="fixed z-[200] max-h-56 overflow-y-auto scrollbar-hide rounded-xl border border-[var(--color-border)] bg-white py-1 shadow-lg" style={subjectEditDropdownStyle}>
                            <button
                              type="button"
                              className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition hover:bg-[var(--color-primary-light)]/40 ${
                                !editState.subject_id
                                  ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                                  : "text-[var(--color-text-hint)]"
                              }`}
                              onMouseDown={(e) => { e.preventDefault(); onEditStateChange({ ...editState, subject_id: null }); onSubjectDropdownOpenChange(false); }}
                            >
                              {!editState.subject_id ? <Check className="h-4 w-4 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-4 shrink-0" />}
                              不设置
                            </button>
                            {leafSubjectOptions.map((s) => (
                              <button
                                key={s.id}
                                type="button"
                                className={`flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm transition hover:bg-[var(--color-primary-light)]/40 ${
                                  editState.subject_id === s.id
                                    ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                                    : "text-[var(--color-text-primary)]"
                                }`}
                                onMouseDown={(e) => { e.preventDefault(); onEditStateChange({ ...editState, subject_id: s.id }); onSubjectDropdownOpenChange(false); }}
                              >
                                {editState.subject_id === s.id ? <Check className="h-4 w-4 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-4 shrink-0" />}
                                <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap" title={s.name}>{s.name}</span>
                                <span className="ml-auto shrink-0 text-[10px] text-[var(--color-text-hint)]">{s.code}</span>
                              </button>
                            ))}
                          </div>,
                          document.body
                        ) : null}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-secondary)]">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]/60" />
                        题型
                      </label>
                      <CustomSelect
                        value={editState.question_type}
                        onChange={onQuestionTypeChange}
                        options={
                          canonicalizeQuestionType(editState.question_type) || !editState.question_type
                            ? QUESTION_TYPE_OPTIONS
                            : [...QUESTION_TYPE_OPTIONS, { value: editState.question_type, label: formatUnknownType(editState.question_type), disabled: true }]
                        }
                        placeholder="选择题型"
                        clearable={false}
                      />
                    </div>
                  </div>
                  {/* Stem edit */}
                  <ReviewStemEditor
                    stem={editState.stem}
                    segments={editedSegments}
                    onStemChange={(stem) => onEditStateChange({ ...editState, stem })}
                    onSegmentsChange={onSegmentsChange}
                  />

                  {/* ── Visual Segment Editor (stem) ── */}
                  <ReviewVisualSegmentEditor
                    segments={editedSegments}
                    options={editState.options}
                    uploading={segmentUploading}
                    drag={segmentDrag}
                    inputRef={segmentReplaceInputRef}
                    onFileChange={onSegmentFileChange}
                    onChange={onSegmentsChange}
                    onReplace={(index) => {
                      onSegmentReplace(index);
                    }}
                  />

                  {/* Options edit */}
                  <ReviewOptionEditor
                    questionType={editState.question_type}
                    options={editState.options}
                    multiBlank={editState.multiBlank}
                    visualModel={optionVisualModel}
                    onOptionsChange={(options) => onEditStateChange({ ...editState, options })}
                    onMultiBlankAction={onMultiBlankAction}
                    onRequestTextModeOverride={() => {
                      onRuntimeIssue("placeholder_missing → text mode override requires explicit confirmation");
                    }}
                  />

                  {/* Answer & Analysis edit */}
                  <ReviewAnswerEditor
                    questionType={editState.question_type}
                    options={editState.options}
                    answer={editState.answer}
                    analysis={editState.analysis}
                    onAnswerChange={(answer) => onEditStateChange({ ...editState, answer })}
                    onAnalysisChange={(analysis) => onEditStateChange({ ...editState, analysis })}
                  />

                  {/* AI suggestion in edit mode */}
                  {completeSuggestion ? (
                    <section className="animate-fade-up drawer-section-delay-5 section-scroll section-scroll-ink rounded-2xl border border-[var(--color-primary)]/20 bg-gradient-to-br from-[var(--color-primary-light)]/60 to-white/90 p-4 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-primary)] shadow-sm">
                            <Sparkles className="h-3.5 w-3.5 text-white" />
                          </div>
                          <p className="text-sm font-bold text-[var(--color-primary-dark)]">AI 补全建议</p>
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
                      <pre className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--color-primary)]/10 bg-white/80 p-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">{renderJson(completeSuggestion)}</pre>
                    </section>
                  ) : null}
    </div>
  );
}
