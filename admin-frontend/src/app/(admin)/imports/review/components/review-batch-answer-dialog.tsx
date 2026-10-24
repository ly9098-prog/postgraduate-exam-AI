"use client";

import { Eye, FileText, Upload, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  BatchAnswerApplyResponse,
  BatchAnswerImageApplyResponse,
  BatchAnswerImagePreviewResponse,
  BatchAnswerPreviewResponse,
} from "@/lib/api/types";
import {
  batchAnswerLoadingLabel,
  type BatchAnswerFillTab,
  type BatchAnswerViewState,
} from "../review-batch-answer-view-state";
import type { ImageAnswerMode } from "../hooks/use-review-image-answer-flow";
import { ImageAnswerPreview, ImageAnswerResult } from "./image-answer-results";
import { BatchAnswerPreview, BatchAnswerResult } from "./batch-answer-results";

type ReviewBatchAnswerDialogProps = {
  open: boolean;
  batchId: string;
  view: BatchAnswerViewState;
  tab: BatchAnswerFillTab;
  rawText: string;
  textPreview: BatchAnswerPreviewResponse | null;
  textResult: BatchAnswerApplyResponse | null;
  textExecuting: boolean;
  textError: string | null;
  imageFiles: File[];
  imageMode: ImageAnswerMode;
  imagePreview: BatchAnswerImagePreviewResponse | null;
  imageResult: BatchAnswerImageApplyResponse | null;
  imageExecuting: boolean;
  imageError: string | null;
  onTabChange: (tab: BatchAnswerFillTab) => void;
  onRawTextChange: (text: string) => void;
  onTextPreview: () => void;
  onTextApply: () => void;
  onReset: () => void;
  onClose: () => void;
  onImageFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onRemoveImageFile: (index: number) => void;
  onImageModeChange: (mode: ImageAnswerMode) => void;
  onImagePreview: () => void;
  onImageApply: () => void;
};

export function ReviewBatchAnswerDialog({
  open,
  batchId,
  view,
  tab,
  rawText,
  textPreview,
  textResult,
  textExecuting,
  textError,
  imageFiles,
  imageMode,
  imagePreview,
  imageResult,
  imageExecuting,
  imageError,
  onTabChange,
  onRawTextChange,
  onTextPreview,
  onTextApply,
  onReset,
  onClose,
  onImageFileChange,
  onRemoveImageFile,
  onImageModeChange,
  onImagePreview,
  onImageApply,
}: ReviewBatchAnswerDialogProps) {
  if (!open) return null;
  const executing = textExecuting || imageExecuting;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" role="presentation" onClick={() => { if (!executing) { onClose(); } }}>
      <aside role="dialog" aria-modal="true" className="scholar-panel flex h-full w-full max-w-xl flex-col overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="scholar-panel-header sticky top-0 z-10 px-6 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h4 className="font-display text-xl font-bold text-[var(--ink)]">快速补充答案</h4>
                  <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                    批次 <span className="font-mono text-xs font-semibold text-[var(--ink)]">{batchId}</span>
                    {view.summary ? <span className="ml-2">{view.summary}</span> : null}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {textResult ? (
                    <Button variant="ghost" className="h-7 px-2 text-[11px] text-[var(--color-text-hint)]" onClick={onReset}>
                      清空
                    </Button>
                  ) : null}
                  <button className="shrink-0 rounded-lg p-1.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition disabled:opacity-40" onClick={() => { if (!executing) onClose(); }} disabled={executing}>
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              {/* Tab switcher */}
              {view.showTabs ? (
                <div className="mt-3 flex gap-0.5 rounded-xl border border-[var(--color-border-light)] bg-[var(--color-bg)]/70 p-0.5">
                  <button
                    className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-150 ${
                      tab === "text"
                        ? "bg-white text-[var(--ink)] shadow-sm border border-[var(--color-border-light)]"
                        : "text-[var(--color-text-secondary)] hover:text-[var(--ink)] border border-transparent"
                    }`}
                    onClick={() => onTabChange("text")}
                  >
                    文字输入
                  </button>
                  <button
                    className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-150 ${
                      tab === "image"
                        ? "bg-white text-[var(--ink)] shadow-sm border border-[var(--color-border-light)]"
                        : "text-[var(--color-text-secondary)] hover:text-[var(--ink)] border border-transparent"
                    }`}
                    onClick={() => onTabChange("image")}
                  >
                    图片导入
                  </button>
                </div>
              ) : null}
              {textExecuting || imageExecuting ? (
                <div className="absolute bottom-0 left-0 right-0 z-20 h-0.5 overflow-hidden bg-[var(--color-primary)]/10">
                  <div className="h-full w-1/2 rounded-full bg-[var(--color-primary)]" style={{ animation: "loadingBar 1.2s cubic-bezier(0.4, 0, 0.2, 1) infinite" }} />
                </div>
              ) : null}
            </div>

            <div className="relative flex-1 px-6 py-5 space-y-6">
              {textExecuting ? (
                <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                  <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                    <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                    <span className="text-sm text-[var(--color-text-secondary)]">
                      {batchAnswerLoadingLabel({ mode: "text", hasPreview: Boolean(textPreview) })}
                    </span>
                  </div>
                </div>
              ) : null}

              {/* Error */}
              {textError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  <div className="flex items-start gap-2">
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                    <span>{textError}</span>
                  </div>
                </div>
              ) : null}

              {/* Step 1: Input */}
              {view.showTextInput ? (
                <div className="space-y-4">
                  <div>
                    <p className="mb-1 text-sm font-semibold text-[var(--ink)]">输入答案串</p>
                    <p className="mb-3 text-xs text-[var(--color-text-secondary)]">
                      输入连续的答案字母（如 abcda），或使用逗号/空格/换行分隔。也支持 AB/AC 等多选题格式。
                    </p>
                    <textarea
                      className="w-full h-32 rounded-xl border border-[var(--color-border)] bg-white p-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)] resize-none font-mono"
                      placeholder="示例：abcda&#10;或：A,B,C,D,A&#10;或：A&#10;B&#10;C&#10;D&#10;A&#10;或：AB, CD, A（多选题用分隔符）"
                      value={rawText}
                      onChange={(e) => onRawTextChange(e.target.value)}
                    />
                  </div>
                  <Button
                    className="h-9 w-full text-sm"
                    disabled={!rawText.trim() || textExecuting}
                    onClick={onTextPreview}
                  >
                    <Eye className="mr-1.5 h-4 w-4" />
                    预览解析结果
                  </Button>
                </div>
              ) : null}

              {/* Step 2: Preview table */}
              {view.showTextPreview && textPreview ? (
                <BatchAnswerPreview
                  preview={textPreview}
                  executing={textExecuting}
                  onApply={onTextApply}
                />
              ) : null}

              {/* Step 3: Apply result */}
              {view.showTextResult && textResult ? (
                <BatchAnswerResult result={textResult} onClose={() => onClose()} />
              ) : null}

              {/* ── Image Tab Content ── */}
              {view.showImageContent ? (
                <>
                  {imageExecuting ? (
                    <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                      <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                        <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                        <span className="text-sm text-[var(--color-text-secondary)]">
                          {batchAnswerLoadingLabel({ mode: "image", hasPreview: Boolean(imagePreview) })}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  {imageError ? (
                    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                      <div className="flex items-start gap-2">
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                        <span>{imageError}</span>
                      </div>
                    </div>
                  ) : null}

                  {/* Step 1: Upload */}
                  {view.showImageInput ? (
                    <div className="space-y-4">
                      <div className="rounded-xl border-2 border-dashed border-[var(--color-border)] p-6 text-center transition hover:border-[var(--color-primary)]/40">
                        <input
                          type="file"
                          accept="image/jpeg,image/png"
                          multiple
                          className="hidden"
                          id="image-upload-input"
                          onChange={onImageFileChange}
                          disabled={imageExecuting}
                        />
                        <label htmlFor="image-upload-input" className="cursor-pointer">
                          <Upload className="mx-auto h-8 w-8 text-[var(--color-text-hint)]" />
                          <p className="mt-2 text-sm font-medium text-[var(--ink)]">点击选择图片</p>
                          <p className="mt-1 text-xs text-[var(--color-text-hint)]">支持 JPG、PNG 格式，最多 50 张，每张不超过 10MB</p>
                        </label>
                      </div>

                      {imageFiles.length > 0 ? (
                        <div className="space-y-1.5">
                          <p className="text-xs font-semibold text-[var(--color-text-secondary)]">已选 {imageFiles.length} 张图片</p>
                          <div className="max-h-[160px] overflow-y-auto space-y-1">
                            {imageFiles.map((file, idx) => (
                              <div key={idx} className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white px-3 py-2 text-xs">
                                <FileText className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-hint)]" />
                                <span className="min-w-0 flex-1 truncate text-[var(--ink)]">{file.name}</span>
                                <span className="shrink-0 text-[var(--color-text-hint)]">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                                <button
                                  onClick={() => onRemoveImageFile(idx)}
                                  disabled={imageExecuting}
                                  className="shrink-0 rounded p-0.5 text-[var(--color-text-hint)] hover:bg-red-50 hover:text-red-600 transition disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      <div className="space-y-2">
                        <p className="text-xs font-semibold text-[var(--color-text-secondary)]">识别模式</p>
                        <div className="flex gap-2">
                          <button
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
                              imageMode === "answer_only"
                                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
                                : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/30"
                            }`}
                            onClick={() => onImageModeChange("answer_only")}
                            disabled={imageExecuting}
                          >
                            仅答案
                          </button>
                          <button
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
                              imageMode === "answer_analysis"
                                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
                                : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/30"
                            }`}
                            onClick={() => onImageModeChange("answer_analysis")}
                            disabled={imageExecuting}
                          >
                            答案+解析
                          </button>
                        </div>
                      </div>

                      <Button
                        className="h-9 w-full text-sm"
                        disabled={imageFiles.length === 0 || imageExecuting}
                        onClick={() => onImagePreview()}
                      >
                        <Eye className="mr-1.5 h-4 w-4" />
                        预览识别结果
                      </Button>
                    </div>
                  ) : null}

                  {/* Step 2: Preview results */}
                  {view.showImagePreview && imagePreview ? (
                    <ImageAnswerPreview
                      preview={imagePreview}
                      executing={imageExecuting}
                      onApply={() => onImageApply()}
                    />
                  ) : null}

                  {/* Step 3: Apply result */}
                  {view.showImageResult && imageResult ? (
                    <ImageAnswerResult result={imageResult} onClose={() => onClose()} />
                  ) : null}
                </>
              ) : null}
            </div>
      </aside>
    </div>
  );
}
