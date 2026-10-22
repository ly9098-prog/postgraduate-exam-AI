"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Code2, Eye, FileText, Save, Search, Sparkles, Upload, X, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import { formatChinaClock } from "@/lib/time";
import { apiRequest, toQuery } from "@/lib/api/client";
import { updateSegUrl } from "@/lib/segment-utils";
import { QUESTION_TYPE_OPTIONS, QUESTION_TYPE_LABELS, canonicalizeQuestionType, getQuestionTypeLabel, getQuestionTypeShortLabel, formatUnknownType } from "@/lib/question-types";
import type { SelectOption } from "@/components/ui/custom-select";
import type { BatchAnswerImageApplyResponse, BatchAnswerImagePreviewResponse, BatchAnswerPreviewResponse, BatchAnswerApplyResponse, BatchCompleteResponse, ImportBatchListItem, ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";
import {
  getMultiBlankSaveState,
  reduceMultiBlankEditState,
  syncDerivedMultiBlankFields,
  type MultiBlankAction,
  type MultiBlankEditState,
} from "./components/multi-blank-choice-utils";
import { editStateFromItem, isMultiBlankChoice, textFromImport, type EditState } from "./review-edit-state";
import { ReviewAnswerPreview } from "./components/review-answer-preview";
import { ReviewStemEditor } from "./components/review-stem-editor";
import { buildReviewQueueParams } from "./review-query-state";
import { getLeafSubjectOptions } from "./review-subject-state";
import { getSourceLocator, getSourceQuestionNo } from "./review-source-location";
import {
  type ReviewActionState,
  type ReviewBatchActionResult,
} from "./review-action-requests";
import { useReviewActionMutation } from "./hooks/use-review-action-mutation";
import { useReviewUpdateMutation } from "./hooks/use-review-update-mutation";
import { useReviewAnswerMutations } from "./hooks/use-review-answer-mutations";
import { useReviewCompleteMutation } from "./hooks/use-review-complete-mutation";
import { useReviewBatchAnswerMutations } from "./hooks/use-review-batch-answer-mutations";
import { useReviewImageAnswerMutations } from "./hooks/use-review-image-answer-mutations";
import { useReviewSegmentDrag } from "./hooks/use-review-segment-drag";
import { ReviewVisualSegmentEditor } from "./components/review-visual-segment-editor";
import { ReviewAnswerEditor } from "./components/review-answer-editor";
import { ImageAnswerPreview, ImageAnswerResult } from "./components/image-answer-results";
import { BatchAnswerPreview, BatchAnswerResult } from "./components/batch-answer-results";
import { ReviewQuestionPreview } from "./components/review-question-preview";
import { ReviewOptionEditor } from "./components/review-option-editor";
import { ReviewSourceEvidence } from "./components/review-source-evidence";
import { ReviewJsonView } from "./components/review-json-view";
import { MissingOptionImageAlert } from "./components/missing-option-image-alert";
import { extractOptionVisualModel, type OptionVisualModel } from "@/lib/option-visual-utils";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";

type FilterDropdownOption = {
  value: string;
  label: string;
  shortLabel?: string;
};

function FilterDropdown({
  label,
  value,
  options,
  open,
  setOpen,
  onChange,
}: {
  label: string;
  value: string;
  options: FilterDropdownOption[];
  open: boolean;
  setOpen: (open: boolean | ((current: boolean) => boolean)) => void;
  onChange: (value: string) => void;
}) {
  const activeOption = options.find((o) => o.value === value);
  const buttonLabel = value
    ? `${label}：${activeOption?.shortLabel || activeOption?.label || value}`
    : label;

  return (
    <div className="relative">
      <button
        type="button"
        className={`flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs outline-none transition ${
          value
            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
            : "border-[var(--color-border)] bg-white text-[var(--color-text-primary)] hover:border-[var(--color-primary)]/50"
        }`}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{buttonLabel}</span>
        <ChevronDown className={`h-3 w-3 text-[var(--color-text-hint)] transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 min-w-[120px] overflow-hidden rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
          {options.map((opt) => {
            const active = value === opt.value;
            return (
              <button
                key={opt.value || "all"}
                type="button"
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                  active
                    ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                    : "text-[var(--color-text-primary)]"
                }`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {active ? (
                  <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
                ) : (
                  <span className="inline-block w-3.5 shrink-0" />
                )}
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

type ConfirmState = ReviewActionState | null;

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function completeSuggestionFromItem(item: ImportQuestionItem | null | undefined) {
  const suggestion = item?.ai_metadata?.complete_suggestion;
  if (suggestion && typeof suggestion === "object" && !Array.isArray(suggestion)) return suggestion as Record<string, unknown>;
  return null;
}

function stringSuggestion(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function normalizeAnswerForCompare(value: unknown): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const compact = text.replace(/[，、；;\s]+/g, ",").replace(/^,+|,+$/g, "");
  const upper = compact.toUpperCase();
  if (/^[A-Z](?:,[A-Z])*$/.test(upper)) {
    return upper.split(",").filter(Boolean).sort().join(",");
  }
  return compact;
}

function answersEquivalent(left: unknown, right: unknown): boolean {
  const a = normalizeAnswerForCompare(left);
  const b = normalizeAnswerForCompare(right);
  return Boolean(a && b && a === b);
}

const ALL_BATCH_FIELDS = ["answer", "analysis", "knowledge_points", "difficulty", "subject_id", "question_type", "stem", "options", "tips", "tags"];

const STATUS_OPTIONS = [
  { value: "pending", label: "待审核" },
  { value: "approved", label: "已通过" },
  { value: "rejected", label: "已驳回" },
  { value: "published", label: "已发布" },
  { value: "", label: "全部状态" },
] as const;

const RISK_FILTER_OPTIONS = [
  { value: "", label: "全部", shortLabel: "全部" },
  { value: "high", label: "高风险", shortLabel: "高" },
  { value: "medium", label: "中风险", shortLabel: "中" },
  { value: "low", label: "低风险", shortLabel: "低" },
];

const ANSWER_STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部", shortLabel: "全部" },
  { value: "missing", label: "答案缺失", shortLabel: "缺失" },
  { value: "ai_filled", label: "AI补全", shortLabel: "AI补全" },
  { value: "imported", label: "已导入", shortLabel: "已导入" },
  { value: "manual_verified", label: "已验证", shortLabel: "已验证" },
  { value: "abnormal", label: "答案异常", shortLabel: "异常" },
];

function statusTone(status: string) {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  if (status === "published") return "primary";
  return "warning";
}

export default function ImportReviewPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState({ batch_id: "", status: "pending", subject_id: "", source_type: "", keyword: "", risk_level: "", answer_status: "" });
  const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
  const [subjectDropdownOpen, setSubjectDropdownOpen] = useState(false);
  const subjectBtnRef = useRef<HTMLButtonElement>(null);
  const [subjectDropdownStyle, setSubjectDropdownStyle] = useState<React.CSSProperties>({});
  const [subjectEditDropdownOpen, setSubjectEditDropdownOpen] = useState(false);
  const subjectEditBtnRef = useRef<HTMLButtonElement>(null);
  const [subjectEditDropdownStyle, setSubjectEditDropdownStyle] = useState<React.CSSProperties>({});
  const [riskDropdownOpen, setRiskDropdownOpen] = useState(false);
  const [answerStatusDropdownOpen, setAnswerStatusDropdownOpen] = useState(false);
  const [batchDropdownOpen, setBatchDropdownOpen] = useState(false);
  const batchDropdownRef = useRef<HTMLDivElement>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [completedItem, setCompletedItem] = useState<ImportQuestionItem | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(t);
  }, [message]);
  const [debouncedKeyword, setDebouncedKeyword] = useState(filters.keyword);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKeyword(filters.keyword), 300);
    return () => clearTimeout(timer);
  }, [filters.keyword]);
  const [page, setPage] = useState(1);
  // Reset page to 1 whenever filters change
  useEffect(() => {
    setPage(1);
  }, [filters.batch_id, filters.status, filters.subject_id, filters.source_type, filters.risk_level, filters.answer_status, debouncedKeyword]);
  const [detailView, setDetailView] = useState<"formatted" | "json">("formatted");
  const [editing, setEditing] = useState(false);
  // Track visual segment edits (stem & option segments) during editing
  const [editedSegments, setEditedSegments] = useState<Array<Record<string, unknown>> | null>(null);
  // Track which segment index is uploading a replacement image (-1 = none)
  const [segmentUploading, setSegmentUploading] = useState(-1);
  const editSnapshotRef = useRef("");
  const segmentSnapshotRef = useRef("");

  const [viewMode, setViewMode] = useState<"list" | "table">("list");
  const [showBatchComplete, setShowBatchComplete] = useState(false);
  const [batchFields, setBatchFields] = useState<string[]>(["answer", "analysis", "knowledge_points", "difficulty"]);
  const [batchStrategy, setBatchStrategy] = useState<"fill_empty" | "force_overwrite">("fill_empty");
  const [batchResult, setBatchResult] = useState<BatchCompleteResponse | null>(null);
  const [executing, setExecuting] = useState(false);
  const [draftRestored, setDraftRestored] = useState(false);
  const [autoSaveHint, setAutoSaveHint] = useState<string | null>(null);
  const [runtimeIssues, setRuntimeIssues] = useState<string[]>([]);
  // Reset runtime issues when switching questions
  useEffect(() => {
    setRuntimeIssues([]);
  }, [previewId]);
  const [quickAnswerDrafts, setQuickAnswerDrafts] = useState<Record<number, string>>({});
  const [showBatchAnswerFill, setShowBatchAnswerFill] = useState(false);
  const [batchAnswerRawText, setBatchAnswerRawText] = useState("");
  const [batchAnswerPreview, setBatchAnswerPreview] = useState<BatchAnswerPreviewResponse | null>(null);
  const [batchAnswerApplyResult, setBatchAnswerApplyResult] = useState<BatchAnswerApplyResponse | null>(null);
  const [batchAnswerError, setBatchAnswerError] = useState<string | null>(null);

  // Phase 2: 图片导入
  const [batchAnswerFillTab, setBatchAnswerFillTab] = useState<"text" | "image">("text");
  const [imageFiles, setImageFiles] = useState<File[]>([]);
  const [imageImportMode, setImageImportMode] = useState<"answer_only" | "answer_analysis">("answer_only");
  const [imagePreviewResult, setImagePreviewResult] = useState<BatchAnswerImagePreviewResponse | null>(null);
  const [imageApplyResult, setImageApplyResult] = useState<BatchAnswerImageApplyResponse | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const currentBatchId = filters.batch_id || batchIdParam;

  const syncedDetailRef = useRef<Set<number>>(new Set());
  const segmentReplaceInputRef = useRef<HTMLInputElement>(null);
  const segmentReplaceIdxRef = useRef(-1);
  const segmentDrag = useReviewSegmentDrag(editedSegments, setEditedSegments);

  // Close batch dropdown on outside click
  useEffect(() => {
    if (!batchDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (batchDropdownRef.current && !batchDropdownRef.current.contains(e.target as Node)) {
        setBatchDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [batchDropdownOpen]);

  // Close subject dropdown on outside click (portal bypasses drawer's onBlur chain)
  useEffect(() => {
    if (!subjectDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (subjectBtnRef.current && !subjectBtnRef.current.contains(e.target as Node)) {
        setSubjectDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [subjectDropdownOpen]);

  // Close subject edit dropdown on outside click (portal bypasses drawer's onBlur chain)
  useEffect(() => {
    if (!subjectEditDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (subjectEditBtnRef.current && !subjectEditBtnRef.current.contains(e.target as Node)) {
        setSubjectEditDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [subjectEditDropdownOpen]);

  const DRAFT_KEY = "batch-complete-draft";

  const saveDraft = (fields: string[], strategy: string) => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ fields, strategy, savedAt: Date.now() }));
    } catch { /* quota exceeded, silently ignore */ }
  };

  const clearDraft = () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
  };

  const loadDraft = (): { fields: string[]; strategy: string } | null => {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed?.fields)) return null;
      return { fields: parsed.fields, strategy: parsed.strategy === "force_overwrite" ? "force_overwrite" : "fill_empty" };
    } catch { return null; }
  };

  // restore draft on mount
  useEffect(() => {
    const draft = loadDraft();
    if (draft) {
      setBatchFields(draft.fields);
      setBatchStrategy(draft.strategy as "fill_empty" | "force_overwrite");
      setDraftRestored(true);
    }
  }, []);

  // auto-save when form changes
  useEffect(() => {
    if (!showBatchComplete) return;
    saveDraft(batchFields, batchStrategy);
    setAutoSaveHint("已自动保存草稿");
  }, [batchFields, batchStrategy, showBatchComplete]);

  // clear auto-save hint after 3s
  useEffect(() => {
    if (!autoSaveHint) return;
    const t = setTimeout(() => setAutoSaveHint(null), 3000);
    return () => clearTimeout(t);
  }, [autoSaveHint]);

  const queryParams = useMemo(
    () => buildReviewQueueParams({
      batch_id: filters.batch_id,
      status: filters.status,
      subject_id: filters.subject_id,
      source_type: filters.source_type,
      risk_level: filters.risk_level,
      answer_status: filters.answer_status,
    }, page, batchIdParam, debouncedKeyword),
    [page, batchIdParam, filters.batch_id, filters.status, filters.subject_id, filters.source_type, filters.risk_level, filters.answer_status, debouncedKeyword],
  );

  const queue = useQuery({
    queryKey: ["import-review-queue", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<ImportQuestionItem>>(`/imports/review-queue${toQuery(queryParams)}`),
    retry: false,
    placeholderData: (prev: PaginatedResponse<ImportQuestionItem> | undefined) => prev,
  });

  const items = queue.data?.items ?? [];

  // Fetch full detail when drawer opens
  const detail = useQuery({
    queryKey: ["import-question-detail", previewId],
    queryFn: () => apiRequest<ImportQuestionItem>(`/imports/questions/${previewId}`),
    enabled: previewId !== null,
    retry: false,
  });

  const queuedPreviewItem = items.find((item) => item.id === previewId) ?? null;
  const previewItem = detail.data ?? (completedItem?.id === previewId ? completedItem : queuedPreviewItem);

  // Derive option visual model from preview item data
  const optionVisualModel: OptionVisualModel = useMemo(() => {
    if (!previewItem) return { mode: "none", optionImages: {}, placeholderKeys: [], missingImageKeys: [], hasValidVisual: false, expectedOptionKeys: [], detectedOptionKeys: [], consumedSegmentIds: [], legacy: false, issues: [] };
    return extractOptionVisualModel(previewItem.parsed_content, previewItem.parsed_options);
  }, [previewItem]);

  const unresolvedTableCount = useMemo(() => {
    const sourceSegments = editing
      ? (editedSegments ?? [])
      : ((previewItem?.parsed_content?.segments as Array<Record<string, unknown>> | undefined) ?? []);
    return sourceSegments.reduce((count, segment) => {
      const table = normalizeStructuredTableSegment(segment);
      return count + (table?.requires_review ? 1 : 0);
    }, 0);
  }, [editing, editedSegments, previewItem]);

  const isBlockedByVisualIssues =
    optionVisualModel.mode === "placeholder_missing" ||
    optionVisualModel.mode === "unknown_visual" ||
    (optionVisualModel.legacy && optionVisualModel.issues.length > 0) ||
    unresolvedTableCount > 0 ||
    runtimeIssues.length > 0;

  // When full detail loads for the first time after drawer open, sync editState
  useEffect(() => {
    if (detail.data && previewId === detail.data.id) {
      if (!syncedDetailRef.current.has(previewId)) {
        syncedDetailRef.current.add(previewId);
        setEditState(editStateFromItem(detail.data));
      }
    }
  }, [detail.data, previewId]);

  const subjectsQuery = useQuery({
    queryKey: ["import-subject-options"],
    queryFn: () => apiRequest<Array<{id: number; code: string; name: string; path: string; level: number; parent_id?: number | null; is_leaf?: boolean; has_children?: boolean}>>("/imports/subject-options"),
    staleTime: 5 * 60 * 1000,
  });
  const subjectOptions = subjectsQuery.data ?? [];

  // ── 批次列表（供批次选择器使用）──
  const batchesQuery = useQuery({
    queryKey: ["import-batches-for-selector"],
    queryFn: () => apiRequest<PaginatedResponse<ImportBatchListItem>>(`/imports${toQuery({ page: 1, page_size: 100 })}`),
    staleTime: 30 * 1000,
    enabled: batchDropdownOpen,
  });

  const leafSubjectOptions = useMemo(() => {
    return getLeafSubjectOptions(subjectOptions ?? []);
  }, [subjectOptions]);

  const completeSuggestion = completeSuggestionFromItem(previewItem);
  const answerSuggestion = stringSuggestion(completeSuggestion?.answer);
  const answerSuggestionApplied = Boolean(
    answerSuggestion && answersEquivalent(editState?.answer ?? previewItem?.parsed_answer, answerSuggestion),
  );
  const allChecked = items.length > 0 && items.every((item) => selectedIds.has(item.id));

  const actionMutation = useReviewActionMutation({
      batchId: filters.batch_id,
      batchIdParam,
      selectedIds,
      rejectReason,
      request: apiRequest,
    }, {
      onSuccess: (result, action) => {
        if (action.action === "approve") {
          setMessage(`导入题目 #${action.id} 已通过审核。`);
          closeDrawer();
        } else if (action.action === "reject") {
          setMessage(`导入题目 #${action.id} 已驳回。`);
          closeDrawer();
        } else if (action.action === "batch-approve") {
          const affected = "affected_count" in result ? result.affected_count : 0;
          const errors = "errors" in result ? (result as ReviewBatchActionResult).errors : undefined;
          if (errors && errors.length > 0) {
            const failedIds = errors.map((e) => `#${e.id}`).join("、");
            setMessage(`批量审核通过部分完成：成功 ${affected}，失败 ${errors.length}（${failedIds}）。`);
          } else {
            setMessage(`批量审核通过完成，影响 ${affected} 条导入题目。`);
          }
        } else if (action.action === "batch-reject") {
          const affected = "affected_count" in result ? result.affected_count : 0;
          const errors = "errors" in result ? (result as ReviewBatchActionResult).errors : undefined;
          if (errors && errors.length > 0) {
            const failedIds = errors.map((e) => `#${e.id}`).join("、");
            setMessage(`批量驳回部分完成：成功 ${affected}，失败 ${errors.length}（${failedIds}）。`);
          } else {
            setMessage(`批量驳回完成，影响 ${affected} 条导入题目。`);
          }
        } else if (action.action === "low-risk-batch-approve") {
          const res = result as { affected_count: number; skipped_count: number; skipped_reasons: string[] };
          const msg = `低风险批量通过完成：通过 ${res.affected_count} 题，跳过 ${res.skipped_count} 题`;
          setMessage(res.skipped_count > 0 ? `${msg}（部分高风险/需检查题已跳过）` : msg);
        }
      },
      onReset: () => {
        setSelectedIds(new Set());
        setConfirmState(null);
        setRejectReason("");
      },
      onError: (error) => {
        setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
      },
  });

  const visualBlockReasons = isBlockedByVisualIssues ? [
    ...(optionVisualModel.mode === "placeholder_missing" ? ["选项图片缺失"] : []),
    ...(optionVisualModel.mode === "unknown_visual" ? ["选项状态未知，需人工确认"] : []),
    ...(unresolvedTableCount > 0 ? [`${unresolvedTableCount} 个结构化表格尚未人工核验`] : []),
    ...runtimeIssues,
  ] : null;

  const updateMutation = useReviewUpdateMutation({
    previewId,
    editState,
    previewItem,
    editedSegments,
    visualBlockReasons,
    request: apiRequest,
  }, {
    onSaved: (result) => {
      setMessage(`导入题目 #${result.id} 已保存。`);
      setEditState(editStateFromItem(result));
      setEditedSegments(null);
      setCompletedItem(result);
      syncedDetailRef.current.delete(result.id);
    },
    onAfterInvalidation: () => setEditing(false),
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    },
  });

  const completeMutation = useReviewCompleteMutation(apiRequest, {
    onCompleted: (result) => {
      const missingFields = result.missing.length > 0 ? `（补全字段：${result.missing.join("、")}）` : "";
      setMessage(
        result.missing.length === 0
          ? "当前题目信息已完整，无需补全。"
          : `AI 补全完成${missingFields}，请复核后保存/通过。`,
      );
    },
    onDetailSynced: (result) => {
      // Keep the active drawer in sync immediately.  The detail query has higher
      // precedence than completedItem, so leaving its old cache entry in place
      // makes freshly completed parsed_analysis look as if it was never saved.
      syncedDetailRef.current.add(result.item.id);
      setPreviewId(result.item.id);
      setCompletedItem(result.item);
      setEditState(editStateFromItem(result.item));
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "AI 补全失败，请稍后重试。"),
  });

  const { quickAnswer: quickAnswerMutation, verifyAnswer: verifyAnswerMutation } = useReviewAnswerMutations(
    apiRequest,
    {
      onQuickAnswerSaved: (result) => {
        const srcNo = getSourceQuestionNo(result);
        setMessage(srcNo ? `原题${srcNo} 答案已保存` : `导入题目 #${result.id} 答案已保存`);
        setQuickAnswerDrafts((prev) => {
          const next = { ...prev };
          delete next[result.id];
          return next;
        });
      },
      onAnswerVerified: (result) => {
        const srcNo = getSourceQuestionNo(result);
        setMessage(srcNo ? `原题${srcNo} 答案已确认为正确` : `导入题目 #${result.id} 答案已确认为正确`);
      },
      onError: (error, action) => {
        setMessage(error instanceof Error
          ? error.message
          : action === "save" ? "保存失败，请稍后重试。" : "确认失败，请稍后重试。");
      },
    },
  );

  const { preview: previewBatchAnswerMutation, apply: applyBatchAnswerMutation } =
    useReviewBatchAnswerMutations(apiRequest, {
      onPreviewStarted: () => {
        setBatchAnswerError(null);
        setBatchAnswerPreview(null);
        setBatchAnswerApplyResult(null);
      },
      onPreviewed: setBatchAnswerPreview,
      onPreviewError: (error) => setBatchAnswerError(error instanceof Error ? error.message : "预览失败"),
      onApplyStarted: () => setBatchAnswerError(null),
      onApplied: setBatchAnswerApplyResult,
      onApplyError: (error) => setBatchAnswerError(error instanceof Error ? error.message : "写入失败"),
    });
  const { mutate: previewBatchAnswers, isPending: isPreviewingBatchAnswers } = previewBatchAnswerMutation;
  const { mutate: applyBatchAnswers, isPending: isApplyingBatchAnswers } = applyBatchAnswerMutation;
  const batchAnswerExecuting = isPreviewingBatchAnswers || isApplyingBatchAnswers;
  const { preview: previewImageMutation, apply: applyImageMutation } = useReviewImageAnswerMutations(
    apiRequest,
    {
      onPreviewStarted: () => {
        setImageError(null);
        setImagePreviewResult(null);
        setImageApplyResult(null);
      },
      onPreviewed: setImagePreviewResult,
      onPreviewError: (error) => setImageError(error instanceof Error ? error.message : "预览生成失败"),
      onApplyStarted: () => setImageError(null),
      onApplied: setImageApplyResult,
      onApplyError: (error) => setImageError(error instanceof Error ? error.message : "写入失败"),
    },
  );
  const { mutate: previewImageAnswers, isPending: isPreviewingImageAnswers } = previewImageMutation;
  const { mutate: applyImageAnswers, isPending: isApplyingImageAnswers } = applyImageMutation;
  const imageExecuting = isPreviewingImageAnswers || isApplyingImageAnswers;

  const handleBatchAnswerPreview = useCallback(() => {
    if (!currentBatchId || !batchAnswerRawText.trim()) return;
    previewBatchAnswers({ batchId: currentBatchId, rawText: batchAnswerRawText });
  }, [currentBatchId, batchAnswerRawText, previewBatchAnswers]);

  const handleBatchAnswerApply = useCallback(() => {
    if (!currentBatchId || !batchAnswerPreview?.preview_token) return;
    applyBatchAnswers({
      batchId: currentBatchId,
      previewToken: batchAnswerPreview.preview_token,
      operationId: batchAnswerPreview.operation_id || "",
    });
  }, [currentBatchId, batchAnswerPreview, applyBatchAnswers]);

  const handleBatchAnswerReset = useCallback(() => {
    setBatchAnswerRawText("");
    setBatchAnswerPreview(null);
    setBatchAnswerApplyResult(null);
    setBatchAnswerError(null);
  }, []);

  // Phase 2: 图片导入 handlers
  const handleImageReset = useCallback(() => {
    setImageFiles([]);
    setImagePreviewResult(null);
    setImageApplyResult(null);
    setImageError(null);
  }, []);

  const handleImagePreview = useCallback(() => {
    if (!currentBatchId || imageFiles.length === 0) return;
    previewImageAnswers({ batchId: currentBatchId, files: imageFiles, mode: imageImportMode });
  }, [currentBatchId, imageFiles, imageImportMode, previewImageAnswers]);

  const handleImageApply = useCallback(() => {
    if (!currentBatchId || !imagePreviewResult?.preview_token) return;
    applyImageAnswers({
      batchId: currentBatchId,
      previewToken: imagePreviewResult.preview_token,
      operationId: imagePreviewResult.operation_id || "",
    });
  }, [currentBatchId, imagePreviewResult, applyImageAnswers]);

  const handleImageFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setImageFiles((prev) => [...prev, ...files]);
    setImagePreviewResult(null);
    setImageApplyResult(null);
    setImageError(null);
    e.target.value = "";
  }, []);

  const removeImageFile = useCallback((index: number) => {
    setImageFiles((prev) => prev.filter((_, i) => i !== index));
    setImagePreviewResult(null);
    setImageApplyResult(null);
    setImageError(null);
  }, []);

  const toggleBatchField = (field: string) => {
    setDraftRestored(false);
    setBatchFields((prev) => (prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]));
  };

  const executeBatchComplete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      setMessage("请先选择需要补全的题目。");
      return;
    }
    if (batchFields.length === 0) {
      setMessage("请选择至少一个补全字段。");
      return;
    }
    setExecuting(true);
    setBatchResult(null);
    try {
      const result = await apiRequest<BatchCompleteResponse>("/imports/questions/batch-complete", {
        method: "POST",
        body: JSON.stringify({ import_ids: ids, fields: batchFields, strategy: batchStrategy }),
      });
      setBatchResult(result);
      clearDraft();
      const failedItems = result.items.filter((i) => i.status === "failed");
      const failedIdStr = failedItems.length > 0 ? `（${failedItems.map((i) => `#${i.import_id}`).join("、")}）` : "";
      setMessage(`批量补全完成：成功 ${result.succeeded}，失败 ${result.failed}，跳过 ${result.skipped}${failedIdStr}`);
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["import-question-detail"] });

      // If the completed question is currently open, refresh it eagerly so the
      // newly persisted answer/analysis is visible in the drawer without closing
      // it or manually reloading the page.
      if (previewId !== null && ids.includes(previewId)) {
        try {
          const refreshed = await apiRequest<ImportQuestionItem>(`/imports/questions/${previewId}`);
          queryClient.setQueryData(["import-question-detail", previewId], refreshed);
          syncedDetailRef.current.add(previewId);
          setCompletedItem(refreshed);
          setEditState(editStateFromItem(refreshed));
        } catch {
          // The completion itself has succeeded; a transient detail refresh must
          // not turn the whole batch operation into a failure message.
        }
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "批量补全失败，请稍后重试。");
    } finally {
      setExecuting(false);
    }
  };

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedIds(new Set());
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
  };

  const toggleAll = () => {
    setSelectedIds(() => (allChecked ? new Set() : new Set(items.map((item) => item.id))));
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openPreview = (item: ImportQuestionItem) => {
    setPreviewId(item.id);
    setCompletedItem(null);
    const snapshot = editStateFromItem(item);
    setEditState(snapshot);
    editSnapshotRef.current = JSON.stringify(snapshot);
    segmentSnapshotRef.current = JSON.stringify(item.parsed_content?.segments ?? []);
    setEditing(false);
    setDetailView("formatted");
  };

  const closeDrawer = () => {
    const hasEditStateChanges = editing && editState && JSON.stringify(editState) !== editSnapshotRef.current;
    const hasSegmentChanges = editing && JSON.stringify(editedSegments ?? []) !== segmentSnapshotRef.current;
    if (hasEditStateChanges || hasSegmentChanges) {
      if (!window.confirm("有未保存的修改，确定关闭吗？")) return;
    }
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
    setEditedSegments(null);
    setEditing(false);
    syncedDetailRef.current.clear();
  };

  const startEditing = () => {
    if (!previewId) return;
    // Copy current segments from previewItem for editing
    const segs = previewItem?.parsed_content?.segments as Array<Record<string, unknown>> | undefined;
    const clonedSegments = segs && segs.length > 0
      ? JSON.parse(JSON.stringify(segs)) as Array<Record<string, unknown>>
      : null;
    setEditedSegments(clonedSegments);
    segmentSnapshotRef.current = JSON.stringify(clonedSegments ?? []);
    editSnapshotRef.current = JSON.stringify(editState);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditState(previewItem ? editStateFromItem(previewItem) : null);
    setEditedSegments(null);
    setEditing(false);
  };

  /** 安全切换题型：保护多空选择题结构化数据；在单选/多选多空之间切换时保留分组 */
  const handleQuestionTypeChange = useCallback((newCode: string) => {
    if (!editState) return;
    if (editState.question_type === newCode) return;
    const wasMultiBlank = isMultiBlankChoice(editState.question_type);
    const isMultiBlankTarget = isMultiBlankChoice(newCode);
    if (wasMultiBlank && !isMultiBlankTarget && editState.multiBlank?.groups && editState.multiBlank.groups.length > 0) {
      const confirmed = window.confirm("切换题型将清空多空选择分组数据，是否继续？");
      if (!confirmed) return;
      setEditState({
        ...editState,
        question_type: newCode,
        multiBlank: undefined,
        options: [],
      });
      return;
    }
    if (wasMultiBlank && isMultiBlankTarget) {
      // 单选 ↔ 多选互转：保留分组数据，仅更新题型 code
      setEditState({ ...editState, question_type: newCode });
      return;
    }
    if (isMultiBlankTarget) {
      setEditState({
        ...editState,
        question_type: newCode,
        multiBlank: {
          groups: [],
          answerMap: {},
          usesSharedOptions: false,
          sharedOptions: [],
        },
      });
      return;
    }
    setEditState({ ...editState, question_type: newCode });
  }, [editState]);

  /** Multi-blank choice reducer action dispatcher — runs inside functional setState */
  const onMultiBlankAction = useCallback((action: MultiBlankAction) => {
    setEditState((prev) => {
      if (!prev?.multiBlank) return prev;
      const nextMultiBlank = reduceMultiBlankEditState(
        prev.multiBlank as MultiBlankEditState,
        action,
      );
      const synced = syncDerivedMultiBlankFields(prev, nextMultiBlank);
      return {
        ...prev,
        answer: synced.answer,
        multiBlank: synced.multiBlank,
      };
    });
  }, []);

  useEffect(() => {
    if (previewId === null) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [previewId, editing, editState]);

  const handleSegmentReplace = useCallback(async (si: number, file: File) => {
    if (!file) return;
    setSegmentUploading(si);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await apiRequest<{ url: string; filename: string }>("/imports/segment-image/upload", {
        method: "POST",
        body: formData,
      });
      setEditedSegments((prev) => {
        if (!prev || si >= prev.length) return prev;
        return updateSegUrl(prev, si, result.url);
      });
      setMessage(`图片已替换：${result.filename}`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "图片上传失败");
    } finally {
      setSegmentUploading(-1);
    }
  }, []);

  const handleSegmentFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    const idx = segmentReplaceIdxRef.current;
    segmentReplaceIdxRef.current = -1;
    if (file && idx >= 0) handleSegmentReplace(idx, file);
  }, [handleSegmentReplace]);

  const canBatchOperate = items.length > 0 && (selectedIds.size > 0 || Boolean(filters.batch_id || batchIdParam));

  return (
    <div className="space-y-6">
      <style>{`
@keyframes loadingBar { 0% { transform: translateX(-100%); } 50% { transform: translateX(100%); } 100% { transform: translateX(300%); } }
@keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes inkSpread { 0% { transform: scale(0.3); opacity: 0.8; } 50% { transform: scale(1); opacity: 0.4; } 100% { transform: scale(1.3); opacity: 0; } }
@keyframes stampPop { 0% { transform: scale(0.8) rotate(-3deg); opacity: 0; } 60% { transform: scale(1.05) rotate(0.5deg); opacity: 1; } 100% { transform: scale(1) rotate(0deg); opacity: 1; } }
@keyframes paperSlide { 0% { transform: translateX(100%) rotate(2deg); opacity: 0; } 100% { transform: translateX(0) rotate(0deg); opacity: 1; } }
@keyframes sealStamp { 0% { transform: scale(2) rotate(-8deg); opacity: 0; } 50% { transform: scale(1.1) rotate(1deg); opacity: 1; } 100% { transform: scale(1) rotate(0deg); opacity: 1; } }
@keyframes cardLift { 0% { box-shadow: var(--shadow-card); transform: translateY(0); } 100% { box-shadow: 0 20px 50px rgba(45, 62, 80, 0.12), 0 6px 14px rgba(45, 62, 80, 0.06); transform: translateY(-2px); } }
@keyframes shimmer { 0% { background-position: -200% center; } 100% { background-position: 200% center; } }
.animate-slide-in { animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.animate-fade-up { animation: fadeUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
.animate-ink-spread { animation: inkSpread 1.5s ease-out infinite; }
.animate-paper-slide { animation: paperSlide 0.35s cubic-bezier(0.16, 1, 0.3, 1) both; }
.animate-seal-stamp { animation: sealStamp 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.drawer-section-delay-1 { animation-delay: 0.05s; }
.drawer-section-delay-2 { animation-delay: 0.1s; }
.drawer-section-delay-3 { animation-delay: 0.15s; }
.drawer-section-delay-4 { animation-delay: 0.2s; }
.drawer-section-delay-5 { animation-delay: 0.25s; }
.bg-noise { background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E"); background-size: 128px 128px; }
.risk-seal { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 700; letter-spacing: 0.03em; border: 1.5px solid; }
.risk-seal-high { color: #b03a3a; border-color: #b03a3a; background: linear-gradient(135deg, #fef2f2, #fde8e8); }
.risk-seal-medium { color: #b87a30; border-color: #b87a30; background: linear-gradient(135deg, #fffbeb, #fef3c7); }
.risk-seal-low { color: #3a7a5a; border-color: #3a7a5a; background: linear-gradient(135deg, #f0fdf4, #dcfce7); }
.card-hover { transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1); }
.card-hover:hover { animation: cardLift 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards; border-color: rgba(91, 123, 154, 0.25); }
.card-linen { background-image: url("data:image/svg+xml,%3Csvg width='100' height='100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='l'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='1.5' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100' height='100' filter='url(%23l)' opacity='0.03'/%3E%3C/svg%3E"); background-size: 100px 100px; }
.scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
.scrollbar-hide::-webkit-scrollbar { display: none; }
.card-risk-border { position: relative; overflow: hidden; }
.card-risk-border::before { content: ""; position: absolute; top: 0; left: 0; width: 4px; height: 100%; border-radius: 2px 0 0 2px; }
.card-risk-high::before { background: linear-gradient(180deg, #b03a3a, #c47a7a); }
.card-risk-medium::before { background: linear-gradient(180deg, #b87a30, #c49a6b); }
.card-risk-low::before { background: linear-gradient(180deg, #3a7a5a, #6b9b6b); }
.card-risk-none::before { background: linear-gradient(180deg, transparent, rgba(91,123,154,0.15)); }
.section-scroll { position: relative; overflow: hidden; padding-left: 16px; }
.section-scroll::before { content: ""; position: absolute; top: 0; left: 0; width: 3px; height: 100%; border-radius: 0 2px 2px 0; }
.section-scroll-warm::before { background: linear-gradient(180deg, transparent, rgba(196, 154, 107, 0.4), rgba(196, 154, 107, 0.2), transparent); }
.section-scroll-ink::before { background: linear-gradient(180deg, transparent, rgba(91, 123, 154, 0.35), rgba(91, 123, 154, 0.15), transparent); }
.section-scroll-jade::before { background: linear-gradient(180deg, transparent, rgba(107, 155, 107, 0.35), rgba(107, 155, 107, 0.15), transparent); }
.section-scroll-purple::before { background: linear-gradient(180deg, transparent, rgba(154, 122, 186, 0.3), rgba(154, 122, 186, 0.12), transparent); }
.stem-text { font-size: 0.9375rem; line-height: 1.75; color: var(--ink); white-space: pre-wrap; }
.stem-text code { font-family: var(--font-mono); font-size: 0.8125rem; background: rgba(91,123,154,0.08); padding: 1px 5px; border-radius: 4px; }
.stem-text pre { font-family: var(--font-mono); font-size: 0.8125rem; background: rgba(45,62,80,0.04); border: 1px solid rgba(232,229,224,0.6); border-radius: 10px; padding: 12px 14px; overflow-x: auto; white-space: pre-wrap; margin: 8px 0; line-height: 1.6; }
.option-chip { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 8px; font-size: 11px; font-weight: 700; background: rgba(196,154,107,0.12); color: #8a6a3a; flex-shrink: 0; }
.answer-box { display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid rgba(107,155,107,0.2); background: rgba(107,155,107,0.06); border-radius: 10px; padding: 6px 14px; font-family: var(--font-mono); font-size: 0.875rem; font-weight: 700; color: #3a7a5a; }
/* ── Segment Editor ── */
@keyframes segLiftIn { from { opacity: 0; transform: translateY(6px) scale(0.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes segPopOut { from { opacity: 1; transform: scale(1); max-height: 120px; } to { opacity: 0; transform: scale(0.92); max-height: 0; margin-top: 0; margin-bottom: 0; padding-top: 0; padding-bottom: 0; } }
@keyframes imageGlow { 0% { box-shadow: 0 0 0 0 rgba(196,154,107,0.0); } 50% { box-shadow: 0 0 0 3px rgba(196,154,107,0.25), 0 4px 20px rgba(196,154,107,0.08); } 100% { box-shadow: 0 0 0 0 rgba(196,154,107,0.0); } }
@keyframes gripPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.7; } }
.seg-card { transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.18s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.18s ease, background-color 0.18s ease; }
.seg-card:hover { transform: translateY(-1px); }
.seg-card.dragging { transform: scale(0.97); opacity: 0.6; filter: grayscale(0.1); }
.seg-card.drop-target { transform: translateY(0); border-color: var(--color-warning); background: rgba(196,154,107,0.04); box-shadow: 0 0 0 2px rgba(196,154,107,0.15), 0 4px 16px rgba(196,154,107,0.08); }
.seg-card.drop-target::before { content: ""; position: absolute; top: -2px; left: 8px; right: 8px; height: 2px; background: linear-gradient(90deg, transparent, var(--color-warning), transparent); border-radius: 1px; }
.seg-image-preview { transition: all 0.25s ease; }
.seg-image-preview:hover { transform: scale(1.02); box-shadow: 0 4px 20px rgba(27,39,51,0.1), 0 1px 4px rgba(27,39,51,0.06); }
.seg-section-header { position: relative; }
.seg-section-header::after { content: ""; position: absolute; bottom: -8px; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, rgba(196,154,107,0.3), transparent 70%); }
`}</style>
      {message ? (
        <div role="status" aria-live="polite" className="animate-paper-slide fixed right-6 top-6 z-[60] max-w-sm overflow-hidden rounded-2xl border border-[var(--color-border)]/60 bg-white/98 shadow-[0_20px_60px_rgba(45,62,80,0.12),0_4px_16px_rgba(45,62,80,0.06)] backdrop-blur-xl">
          <div className="h-1 bg-gradient-to-r from-[var(--color-primary)] via-[var(--color-warning)] to-[var(--color-success)]" />
          <div className="px-5 py-4">
          <div className="flex items-start gap-3.5">
            <div className="relative mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--color-success-light)] shadow-sm">
              <div className="absolute inset-0 rounded-xl animate-seal-stamp border-2 border-[var(--color-success)]/15" />
              <CheckCircle2 className="relative h-4 w-4 text-[var(--color-success)]" />
            </div>
            <p className="min-w-0 flex-1 pt-0.5 text-sm leading-relaxed text-[var(--ink)]">{message}</p>
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-[var(--color-border)]/30 pt-2.5">
            <span className="text-[10px] text-[var(--color-text-hint)]">{formatChinaClock()}</span>
            <div className="ml-auto">
              <button aria-label="关闭提示" className="rounded-lg px-3 py-1 text-[10px] font-medium text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]" onClick={() => setMessage(null)}>关闭</button>
            </div>
          </div>
          </div>
        </div>
      ) : null}
      <Card className="!border-[var(--color-border)]/80 !shadow-[0_24px_60px_rgba(45,62,80,0.06)]">
        <CardHeader className="space-y-2 pb-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-lg font-bold text-[var(--ink)]">待审核题目</h3>
              <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">审核导入题目，通过后发布到正式题库</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <div className="flex items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/60 p-1">
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过
                </Button>
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!(filters.batch_id || batchIdParam)} onClick={() => setConfirmState({ action: "low-risk-batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过低风险
                </Button>
                <Button variant="danger" className="h-8 px-3 text-xs" disabled={!canBatchOperate} onClick={() => setConfirmState({ action: "batch-reject" })}>
                  <XCircle className="h-3.5 w-3.5" />
                  批量驳回
                </Button>
                <Button
                  variant="secondary"
                  className="h-8 px-3 text-xs"
                  disabled={selectedIds.size === 0}
                  onClick={() => { setShowBatchComplete(true); setBatchResult(null); }}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  AI 批量补全
                </Button>
                <Button
                  variant="secondary"
                  className="h-8 px-3 text-xs"
                  disabled={!currentBatchId}
                  onClick={() => { setShowBatchAnswerFill(true); handleBatchAnswerReset(); }}
                >
                  <FileText className="h-3.5 w-3.5" />
                  快速补充答案
                </Button>
                <div className="h-6 w-px bg-[var(--color-border)]" />
                <div className="flex overflow-hidden rounded-md border border-[var(--color-border)] bg-white/70">
                  <button type="button" className={`px-2.5 py-1.5 text-[10px] font-semibold transition ${viewMode === "list" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => setViewMode("list")}>列表</button>
                  <button type="button" className={`px-2.5 py-1.5 text-[10px] font-semibold transition ${viewMode === "table" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => setViewMode("table")}>核答案</button>
                </div>
              </div>
            </div>
          </div>
          {/* ── Inline filter bar ── */}
          <div className="filter-bar flex flex-wrap items-center gap-2 px-3 py-2">
            {/* Search */}
            <div className="relative min-w-[180px] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <input
                className="h-8 w-full rounded-lg border border-[var(--color-border)] bg-white pl-8 pr-3 text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
                placeholder="搜索题干 / OCR 原文..."
                value={filters.keyword}
                onChange={(event) => setFilters((current) => ({ ...current, keyword: event.target.value }))}
              />
            </div>

            {/* Risk dropdown */}
            <FilterDropdown
              label="风险"
              value={filters.risk_level}
              options={RISK_FILTER_OPTIONS}
              open={riskDropdownOpen}
              setOpen={(fn) => { setRiskDropdownOpen(fn); setAnswerStatusDropdownOpen(false); setSubjectDropdownOpen(false); setStatusDropdownOpen(false); }}
              onChange={(value) => updateFilter("risk_level", value)}
            />

            {/* Answer Status dropdown */}
            <FilterDropdown
              label="答案"
              value={filters.answer_status}
              options={ANSWER_STATUS_FILTER_OPTIONS}
              open={answerStatusDropdownOpen}
              setOpen={(fn) => { setAnswerStatusDropdownOpen(fn); setRiskDropdownOpen(false); setSubjectDropdownOpen(false); setStatusDropdownOpen(false); }}
              onChange={(value) => updateFilter("answer_status", value)}
            />

            {/* Subject dropdown */}
            <div className="relative">
              <button
                ref={subjectBtnRef}
                type="button"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-2.5 text-xs text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)]"
                onClick={() => setSubjectDropdownOpen((v) => !v)}
              >
                <span className="max-w-[160px] overflow-hidden text-ellipsis whitespace-nowrap" title={filters.subject_id ? (subjectOptions.find((s) => String(s.id) === filters.subject_id)?.name || filters.subject_id) : ""}>
                  {filters.subject_id ? (subjectOptions.find((s) => String(s.id) === filters.subject_id)?.name || filters.subject_id) : "全部科目"}
                </span>
                <ChevronDown className={`h-3 w-3 shrink-0 text-[var(--color-text-hint)] transition-transform ${subjectDropdownOpen ? "rotate-180" : ""}`} />
              </button>
              {subjectDropdownOpen ? (
                <div className="absolute left-0 top-full z-20 mt-1 min-w-[220px] max-w-[320px] max-h-72 overflow-y-auto scrollbar-hide rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                      !filters.subject_id ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-primary)]"
                    }`}
                    onMouseDown={(e) => { e.preventDefault(); updateFilter("subject_id", ""); setSubjectDropdownOpen(false); }}
                  >
                    {!filters.subject_id ? <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-3.5 shrink-0" />}
                    <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">全部科目</span>
                  </button>
                  {leafSubjectOptions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                        filters.subject_id === String(s.id) ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-primary)]"
                      }`}
                      onMouseDown={(e) => { e.preventDefault(); updateFilter("subject_id", String(s.id)); setSubjectDropdownOpen(false); }}
                    >
                      {filters.subject_id === String(s.id) ? <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" /> : <span className="inline-block w-3.5 shrink-0" />}
                      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap" title={s.name}>{s.name}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            {/* Batch ID selector */}
            <div className="relative" ref={batchDropdownRef}>
              <div className="relative">
                <input
                  className="h-8 w-48 rounded-lg border border-[var(--color-border)] bg-white px-2.5 pr-14 text-xs outline-none transition-colors focus:border-[var(--color-primary)]"
                  placeholder="批次 ID"
                  value={filters.batch_id || batchIdParam}
                  onChange={(event) => updateFilter("batch_id", event.target.value)}
                  onFocus={() => setBatchDropdownOpen(true)}
                />
                {(filters.batch_id || batchIdParam) ? (
                  <button
                    type="button"
                    className="absolute right-6 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-[var(--color-text-hint)] hover:text-[var(--color-danger)] transition"
                    onClick={() => { updateFilter("batch_id", ""); setBatchDropdownOpen(false); }}
                    title="清空批次"
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : null}
                <button
                  type="button"
                  className="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition"
                  onClick={() => setBatchDropdownOpen((v) => !v)}
                >
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${batchDropdownOpen ? "rotate-180" : ""}`} />
                </button>
              </div>
              {batchDropdownOpen ? (
                <div className="scholar-dropdown absolute left-0 top-full z-20 mt-1 min-w-[300px] max-w-[360px] max-h-60">
                  {batchesQuery.isLoading ? (
                    <div className="px-4 py-5 text-center text-xs text-[var(--color-text-hint)]">加载中…</div>
                  ) : batchesQuery.data?.items?.length ? (
                    batchesQuery.data.items
                      .filter((b) => b.batch_id && b.batch_id.trim() && b.pending_count > 0)
                      .map((b) => (
                      <button
                        key={b.batch_id}
                        type="button"
                        className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs transition cursor-pointer hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] ${
                          (filters.batch_id || batchIdParam) === b.batch_id ? "bg-[var(--color-primary-light)]/20 font-semibold text-[var(--color-primary-dark)]" : "text-[var(--color-text-primary)]"
                        }`}
                        onMouseDown={(e) => { e.preventDefault(); updateFilter("batch_id", b.batch_id); setBatchDropdownOpen(false); }}
                      >
                        {(filters.batch_id || batchIdParam) === b.batch_id ? (
                          <Check className="h-3 w-3 shrink-0 text-[var(--color-primary)]" />
                        ) : (
                          <span className="inline-block w-3 shrink-0" />
                        )}
                        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px]" title={b.batch_id}>{b.batch_id}</span>
                        <span className="tag-chip shrink-0 bg-[var(--color-success-light)] text-[var(--color-success)]">{b.pending_count}</span>
                      </button>
                    ))
                  ) : (
                    <div className="px-4 py-5 text-center text-xs text-[var(--color-text-hint)]">暂无可选批次</div>
                  )}
                </div>
              ) : null}
            </div>

            {/* Status dropdown */}
            <div className="relative">
              <button
                type="button"
                className="flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-2.5 text-xs text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)]"
                onClick={() => setStatusDropdownOpen((v) => !v)}
                onBlur={() => setTimeout(() => setStatusDropdownOpen(false), 150)}
              >
                <span>{STATUS_OPTIONS.find((o) => o.value === filters.status)?.label}</span>
                <ChevronDown className={`h-3 w-3 text-[var(--color-text-hint)] transition-transform ${statusDropdownOpen ? "rotate-180" : ""}`} />
              </button>
              {statusDropdownOpen ? (
                <div className="absolute right-0 top-full z-20 mt-1 min-w-[120px] overflow-hidden rounded-lg border border-[var(--color-border)] bg-white py-1 shadow-lg">
                  {STATUS_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition hover:bg-[var(--color-primary-light)]/40 ${
                        filters.status === opt.value
                          ? "bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)] font-semibold"
                          : "text-[var(--color-text-primary)]"
                      }`}
                      onMouseDown={(e) => { e.preventDefault(); updateFilter("status", opt.value); setStatusDropdownOpen(false); }}
                    >
                      {filters.status === opt.value ? (
                        <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
                      ) : (
                        <span className="inline-block w-3.5 shrink-0" />
                      )}
                      {opt.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            {(filters.batch_id || filters.subject_id || filters.risk_level || filters.answer_status || filters.keyword) ? (
              <button
                type="button"
                className="flex h-7 items-center gap-1 rounded-lg px-2 text-[10px] font-medium text-[var(--color-text-hint)] hover:text-[var(--color-danger)] transition-colors"
                onClick={() => setFilters({ batch_id: "", status: "pending", subject_id: "", source_type: "", keyword: "", risk_level: "", answer_status: "" })}
              >
                重置
              </button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-1.5 pt-0">
          <section className="space-y-1">
              <div className={`flex items-center gap-2 rounded-lg border border-[var(--color-border)]/40 bg-[var(--color-primary-light)]/10 px-3 py-1.5 ${selectedIds.size > 0 ? "" : "invisible"}`}>
                <span className="text-xs font-medium text-[var(--color-primary-dark)]">已选 {selectedIds.size} 题</span>
              </div>
              {items.length > 0 && viewMode === "table" ? (
                <div className="w-full overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
                  <table className="w-full table-fixed text-[11px]">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg-input)]/50">
                        <th className="w-9 px-2.5 py-2 text-left font-semibold text-[var(--color-text-secondary)]">
                          <label className="group/cb relative flex cursor-pointer items-center justify-center">
                            <span className="flex h-[16px] w-[16px] items-center justify-center rounded border-2 border-[var(--color-border)] bg-white transition-all group-hover/cb:border-[var(--color-primary)]/50 [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                              <input type="checkbox" checked={allChecked} onChange={toggleAll} className="peer absolute inset-0 cursor-pointer opacity-0" />
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
                        const answerStatusLabel =
                          item.answer_status === "missing" ? "缺失" :
                          item.answer_status === "ai_filled" ? "AI" :
                          item.answer_status === "imported" ? "导入" :
                          item.answer_status === "manual_filled" ? "已填" :
                          item.answer_status === "manual_verified" ? "已验" :
                          item.answer_status === "abnormal" ? "异常" : "—";
                        const answerStatusStyle: React.CSSProperties =
                          item.answer_status === "missing" ? { color: "#b03a3a", fontWeight: 700 } :
                          item.answer_status === "ai_filled" ? { color: "#c46a3a", fontWeight: 600 } :
                          item.answer_status === "abnormal" ? { color: "#b03a3a", fontWeight: 700 } :
                          {};
                        const riskLabel = item.risk_level === "high" ? "高" : item.risk_level === "medium" ? "中" : "低";
                        const riskStyle: React.CSSProperties =
                          item.risk_level === "high" ? { color: "#b03a3a", fontWeight: 700 } :
                          item.risk_level === "medium" ? { color: "#b87a30", fontWeight: 600 } :
                          { color: "#3a7a5a" };
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
                                  <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleOne(item.id)} className="peer absolute inset-0 cursor-pointer opacity-0" />
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
                                      onClick={() => setQuickAnswerDrafts((prev) => ({ ...prev, [item.id]: draftAnswer === opt ? "" : opt }))}
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
                                      onClick={() => setQuickAnswerDrafts((prev) => ({ ...prev, [item.id]: draftAnswer === opt ? "" : opt }))}
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
                                  onChange={(e) => setQuickAnswerDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))}
                                  placeholder={isMultiChoice ? "如 AC" : "答案"}
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
                                <button className="w-9 rounded border border-[var(--color-border)] bg-white px-1 py-1 text-[9px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary)]" onClick={() => openPreview(item)} title="查看详情">查</button>
                                <button
                                  onClick={() => quickAnswerMutation.mutate({ id: item.id, answer: draftAnswer })}
                                  disabled={quickAnswerMutation.isPending || !hasDraftChanged}
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
                                  onClick={() => {
                                    setQuickAnswerDrafts((prev) => {
                                      const next = { ...prev };
                                      delete next[item.id];
                                      return next;
                                    });
                                  }}
                                  title="取消编辑"
                                >
                                  消
                                </button>
                                <button
                                  onClick={() => verifyAnswerMutation.mutate(item.id)}
                                  disabled={verifyAnswerMutation.isPending || !item.parsed_answer}
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
                      <input type="checkbox" checked={allChecked} onChange={toggleAll} className="peer absolute inset-0 cursor-pointer opacity-0" />
                      <Check className="h-2.5 w-2.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                    </span>
                    <span className="text-xs text-[var(--color-text-secondary)]">全选本页</span>
                  </label>
                </div>
                {items.map((item, index) => {
                  const riskColor = item.risk_level === "high" ? "#b03a3a" : item.risk_level === "medium" ? "#b87a30" : item.risk_level === "low" ? "#3a7a5a" : "var(--color-border)";
                  const hasAnswerMissing = (!item.parsed_answer || item.parsed_answer.trim() === "") && item.risk_level !== "low";
                  const reasonCount = item.risk_reasons?.length ?? 0;
                  // ── 原题定位显示 ──
                  const sourceLabel = item.source_image_seq != null
                    ? `图${item.source_image_seq}${item.source_question_no ? ` · 原题${item.source_question_no}` : ""}`
                    : (item.source_question_no ? `原题${item.source_question_no}` : null);
                  // ── 答案状态标签 ──
                  const answerStatusLabel =
                    item.answer_status === "missing" ? "答案缺失" :
                    item.answer_status === "ai_filled" ? "AI补全" :
                    item.answer_status === "imported" ? "已导入" :
                    item.answer_status === "manual_filled" ? "已填写" :
                    item.answer_status === "manual_verified" ? "已验证" :
                    item.answer_status === "abnormal" ? "答案异常" : null;
                  const answerStatusColor =
                    item.answer_status === "missing" ? "#b03a3a" :
                    item.answer_status === "ai_filled" ? "#c46a3a" :
                    item.answer_status === "abnormal" ? "#b03a3a" :
                    "var(--color-text-hint)";

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
                              onChange={() => toggleOne(item.id)}
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
                        <p className="min-w-0 flex-1 cursor-pointer truncate text-[13px] leading-snug text-[var(--ink)]" onClick={() => openPreview(item)}>
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
                            onClick={() => openPreview(item)}
                            title="预览详情"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="flex h-7 items-center gap-1 rounded-md border border-[var(--color-success)] bg-[var(--color-success-light)] px-2.5 text-[10px] font-semibold text-[var(--color-success)] transition-colors hover:bg-[var(--color-success)] hover:text-white disabled:opacity-30"
                            disabled={item.status === "published"}
                            onClick={() => setConfirmState({ action: "approve", id: item.id })}
                          >
                            <CheckCircle2 className="h-3 w-3" />
                            通过
                          </button>
                          <button
                            className="flex h-7 items-center gap-1 rounded-md border border-[var(--color-danger)] bg-white px-2.5 text-[10px] font-semibold text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)] hover:text-white disabled:opacity-30"
                            disabled={item.status === "published"}
                            onClick={() => setConfirmState({ action: "reject", id: item.id })}
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
              {!queue.isLoading && items.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-14 text-center">
                  <div className="empty-ink-drop mb-4" />
                  <p className="font-display text-lg font-semibold text-[var(--color-text-secondary)]">暂无待审核题目</p>
                  <p className="mt-1.5 max-w-xs text-xs text-[var(--color-text-hint)] leading-relaxed">所有导入题目已完成审核，或当前筛选条件没有匹配的记录</p>
                </div>
              ) : null}
              {queue.isError ? <p className="text-sm text-[var(--color-danger)]">待审核接口当前不可用。</p> : null}
            </section>

            {/* ── Pagination ── */}
            {queue.data && queue.data.total_pages > 1 ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--blueprint-line)] bg-white/80 px-5 py-3 shadow-[var(--shadow-crisp)]">
                <span className="font-display text-sm tracking-wide text-[var(--color-text-secondary)]">
                  <span className="font-semibold text-[var(--ink)]">{queue.data.total}</span>{" "}
                  条记录
                  <span className="mx-2 text-[var(--color-text-hint)]">/</span>
                  <span className="text-[var(--color-text-hint)]">第 </span>
                  <span className="font-semibold text-[var(--ink)]">{queue.data.page}</span>
                  <span className="text-[var(--color-text-hint)]"> / {queue.data.total_pages} 页</span>
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
                    上一页
                  </button>
                  {Array.from(
                    { length: Math.min(queue.data.total_pages, 5) },
                    (_, i) => {
                      const start = Math.max(1, Math.min(page - 2, queue.data.total_pages - 4));
                      const p = start + i;
                      if (p > queue.data.total_pages) return null;
                      const isActive = p === page;
                      return (
                        <button
                          key={p}
                          disabled={isActive}
                          onClick={() => setPage(p)}
                          className={
                            isActive
                              ? "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-bold text-white shadow-[var(--shadow-crisp)]"
                              : "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white/80 text-sm font-medium text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                          }
                        >
                          {p}
                        </button>
                      );
                    },
                  )}
                  <button
                    disabled={page >= (queue.data?.total_pages ?? 1)}
                    onClick={() => setPage((p) => p + 1)}
                    className="inline-flex h-9 items-center gap-1 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                  >
                    下一页
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
                  </button>
                </div>
              </div>
            ) : null}
        </CardContent>
      </Card>

      {/* ── Scholar's Study Detail Drawer ── */}
      {previewId !== null && previewItem && editState ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.38)] backdrop-blur-[1px]" role="presentation" onClick={closeDrawer}>
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
                  <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-hint)]">#{previewItem.id}</span>
                  <span className="h-3 w-px bg-[var(--color-border)]" />
                  <StatusBadge tone={statusTone(previewItem.status)}>{previewItem.status}</StatusBadge>
                  {previewItem.risk_level === "high" ? (
                    <span className="risk-seal risk-seal-high !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 高风险</span>
                  ) : previewItem.risk_level === "medium" ? (
                    <span className="risk-seal risk-seal-medium !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 需检查</span>
                  ) : previewItem.risk_level === "low" ? (
                    <span className="risk-seal risk-seal-low !py-0 !text-[10px]"><span className="text-current opacity-60">◉</span> 低风险</span>
                  ) : null}
                  {editState.subject_id ? (
                    <span className="hidden sm:inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">{subjectOptions.find((s) => s.id === editState.subject_id)?.name || `#${editState.subject_id}`}</span>
                  ) : null}
                  {/* ── 原题定位 ── */}
                  {previewItem.source_question_no || previewItem.source_image_seq != null ? (
                    <span className="hidden md:inline-flex items-center gap-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)]">
                      {previewItem.source_image_seq != null ? `图${previewItem.source_image_seq}` : null}
                      {previewItem.source_image_seq != null && previewItem.source_page_start != null ? " · " : null}
                      {previewItem.source_page_start != null ? `第${previewItem.source_page_start}页` : null}
                      {((previewItem.source_image_seq != null || previewItem.source_page_start != null) && previewItem.source_question_no) ? " · " : null}
                      {previewItem.source_question_no ? `原题${previewItem.source_question_no}` : null}
                    </span>
                  ) : null}
                  {previewItem.risk_reasons && previewItem.risk_reasons.length > 0 ? (
                    <span className="hidden md:inline-block max-w-[200px] truncate text-[10px] text-red-600" title={previewItem.risk_reasons.join("；")}>
                      {previewItem.risk_reasons[0]}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {/* View toggle */}
                  <div className="flex overflow-hidden rounded-md border border-[var(--color-border)] bg-white/70">
                    <button type="button" className={`px-2 py-1 text-[10px] font-semibold transition ${detailView === "formatted" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => setDetailView("formatted")}>文本</button>
                    <button type="button" className={`px-2 py-1 text-[10px] font-semibold transition ${detailView === "json" ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-text-secondary)] hover:text-[var(--color-primary-dark)]"}`} onClick={() => setDetailView("json")}>JSON</button>
                  </div>
                  <button className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]" onClick={closeDrawer}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>

            {/* ===== Content (main focus) ===== */}
            <div className="relative flex-1 px-6 py-5 space-y-5">
              {completeMutation.isPending ? (
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
                    content={previewItem.parsed_content}
                    draft={editState}
                    visualModel={optionVisualModel}
                    onRuntimeIssue={(issue) => setRuntimeIssues((prev) => prev.includes(issue) ? prev : [...prev, issue])}
                  />

                  {/* ── Answer Card ── */}
                  <ReviewAnswerPreview item={previewItem} draft={editState} />

                  {/* ── OCR Raw Data ── */}
                  <ReviewSourceEvidence raw_data={previewItem.raw_data} parsed_content={previewItem.parsed_content} />

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
                            disabled={answerSuggestionApplied}
                            onClick={() => {
                              if (answerSuggestionApplied) return;
                              setEditState((prev) => prev ? { ...prev, answer: answerSuggestion } : prev);
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
                <ReviewJsonView item={previewItem} />
              ) : (
                /* ── Edit Mode ── */
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
                          ref={subjectEditBtnRef}
                          type="button"
                          className="flex h-11 w-full items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/80 px-3 text-sm text-[var(--color-text-primary)] outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20"
                          onClick={() => {
                            const next = !subjectEditDropdownOpen;
                            setSubjectEditDropdownOpen(next);
                            if (next && subjectEditBtnRef.current) {
                              const r = subjectEditBtnRef.current.getBoundingClientRect();
                              const maxRight = window.innerWidth - 16;
                              const w = Math.min(r.width, maxRight - 16);
                              setSubjectEditDropdownStyle({ top: r.bottom + 4, left: Math.min(r.left, maxRight - w), width: w });
                            }
                          }}
                          onBlur={() => setTimeout(() => setSubjectEditDropdownOpen(false), 150)}
                        >
                          <span className={`min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-left ${editState.subject_id ? "" : "text-[var(--color-text-hint)]"}`} title={editState.subject_id ? (subjectOptions.find((s) => s.id === editState.subject_id)?.name || "") : ""}>
                            {editState.subject_id
                              ? (subjectOptions.find((s) => s.id === editState.subject_id)?.name || `#${editState.subject_id}`)
                              : "选择科目"}
                          </span>
                          {subjectsQuery.isLoading ? (
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
                              onMouseDown={(e) => { e.preventDefault(); setEditState({ ...editState, subject_id: null }); setSubjectEditDropdownOpen(false); }}
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
                                onMouseDown={(e) => { e.preventDefault(); setEditState({ ...editState, subject_id: s.id }); setSubjectEditDropdownOpen(false); }}
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
                        onChange={handleQuestionTypeChange}
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
                    onStemChange={(stem) => setEditState({ ...editState, stem })}
                    onSegmentsChange={setEditedSegments}
                  />

                  {/* ── Visual Segment Editor (stem) ── */}
                  <ReviewVisualSegmentEditor
                    segments={editedSegments}
                    options={editState.options}
                    uploading={segmentUploading}
                    drag={segmentDrag}
                    inputRef={segmentReplaceInputRef}
                    onFileChange={handleSegmentFileChange}
                    onChange={setEditedSegments}
                    onReplace={(index) => {
                      segmentReplaceIdxRef.current = index;
                      segmentReplaceInputRef.current?.click();
                    }}
                  />

                  {/* Options edit */}
                  <ReviewOptionEditor
                    questionType={editState.question_type}
                    options={editState.options}
                    multiBlank={editState.multiBlank}
                    visualModel={optionVisualModel}
                    onOptionsChange={(options) => setEditState({ ...editState, options })}
                    onMultiBlankAction={onMultiBlankAction}
                    onRequestTextModeOverride={() => {
                      setRuntimeIssues((prev) => [...prev, "placeholder_missing → text mode override requires explicit confirmation"]);
                    }}
                  />

                  {/* Answer & Analysis edit */}
                  <ReviewAnswerEditor
                    questionType={editState.question_type}
                    options={editState.options}
                    answer={editState.answer}
                    analysis={editState.analysis}
                    onAnswerChange={(answer) => setEditState({ ...editState, answer })}
                    onAnalysisChange={(analysis) => setEditState({ ...editState, analysis })}
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
                            disabled={answerSuggestionApplied}
                            onClick={() => {
                              if (answerSuggestionApplied) return;
                              setEditState({ ...editState, answer: answerSuggestion });
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
              )}

              {/* ===== Sticky Bottom Footer ===== */}
              {!editing ? (
                <div className="sticky bottom-0 z-10 border-t border-[var(--color-border)] bg-[var(--color-bg)]/90 px-4 py-3 backdrop-blur-xl">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <Button variant="primary" className="h-8 px-3.5 text-xs" disabled={previewItem.status === "published" || isBlockedByVisualIssues} onClick={() => setConfirmState({ action: "approve", id: previewItem.id })}>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        通过
                      </Button>
                      <Button variant="danger" className="h-8 px-3.5 text-xs" disabled={previewItem.status === "published"} onClick={() => setConfirmState({ action: "reject", id: previewItem.id })}>
                        <XCircle className="h-3.5 w-3.5" />
                        驳回
                      </Button>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        disabled={completeMutation.isPending || previewItem.status !== "pending"}
                        onClick={() => completeMutation.mutate(previewItem.id)}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold tracking-wider transition-all ${
                          completeMutation.isPending
                            ? "bg-[var(--color-primary)]/10 text-[var(--color-primary-dark)] cursor-wait"
                            : "bg-[var(--color-primary)]/10 text-[var(--color-primary-dark)] hover:bg-[var(--color-primary)] hover:text-white disabled:opacity-40 disabled:pointer-events-none"
                        }`}
                      >
                        {completeMutation.isPending ? (
                          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--color-primary)] border-t-transparent" />
                        ) : (
                          <Sparkles className="h-3 w-3" />
                        )}
                        {completeMutation.isPending ? "审校中" : "AI 审校"}
                      </button>
                      <Button className="h-8 px-3 text-xs" variant="secondary" onClick={startEditing}>
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
                    <Button className="h-8 px-3 text-xs" variant="ghost" onClick={cancelEditing}>
                      <X className="h-3.5 w-3.5" />
                      取消
                    </Button>
                    <Button className="h-8 px-3 text-xs" variant="primary" disabled={!canSave || updateMutation.isPending || previewItem.status === "published"} onClick={() => updateMutation.mutate()}>
                      <Save className="h-3.5 w-3.5" />
                      {updateMutation.isPending ? "保存中..." : "保存"}
                    </Button>
                  </div>
                </div>
                );
              })()}
            </div>
          </aside>
        </div>
      ) : null}

      {showBatchComplete ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" role="presentation" onClick={() => { if (!executing) { setShowBatchComplete(false); } }}>
          <aside role="dialog" aria-modal="true" className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-[var(--shadow-floating)]" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="sticky top-0 z-10 border-b border-[var(--color-border)] bg-white/95 px-6 py-4 backdrop-blur-xl">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h4 className="font-display text-xl font-bold text-[var(--ink)]">AI 批量补全</h4>
                  <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                    已选 <span className="font-semibold text-[var(--ink)]">{selectedIds.size}</span> 题
                    {batchResult ? ` · 完成 ${batchResult.succeeded} / 失败 ${batchResult.failed} / 跳过 ${batchResult.skipped}` : ""}
                  </p>
                  {draftRestored && !batchResult ? (
                    <p className="mt-1 flex items-center gap-1 text-xs text-amber-600">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
                      已恢复上次编辑内容
                    </p>
                  ) : null}
                  {autoSaveHint ? (
                    <p className="mt-1 text-xs text-emerald-600">{autoSaveHint}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {!batchResult ? (
                    <Button variant="ghost" className="h-7 px-2 text-[11px] text-[var(--color-text-hint)]" onClick={() => { clearDraft(); setDraftRestored(false); setBatchFields(["answer", "analysis", "knowledge_points", "difficulty"]); setBatchStrategy("fill_empty"); setAutoSaveHint("草稿已清空"); }}>
                      清空草稿
                    </Button>
                  ) : null}
                  <button className="shrink-0 rounded-lg p-1.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition disabled:opacity-40" onClick={() => { if (!executing) setShowBatchComplete(false); }} disabled={executing}>
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              {executing ? (
                <div className="absolute bottom-0 left-0 right-0 z-20 h-0.5 overflow-hidden bg-[var(--color-primary)]/10">
                  <div className="h-full w-1/2 rounded-full bg-[var(--color-primary)]" style={{ animation: "loadingBar 1.2s cubic-bezier(0.4, 0, 0.2, 1) infinite" }} />
                </div>
              ) : null}
            </div>

            <div className="relative flex-1 px-6 py-5 space-y-6">
              {executing ? (
                <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                  <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                    <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                    <span className="text-sm text-[var(--color-text-secondary)]">正在 AI 补全，请勿关闭</span>
                  </div>
                </div>
              ) : null}
              {!batchResult ? (
                <>
                  {/* Strategy */}
                  <section className="space-y-3">
                    <p className="text-sm font-semibold text-[var(--ink)]">补全策略</p>
                    <div className="flex gap-3">
                      <label className={`flex flex-1 cursor-pointer items-center gap-3 rounded-xl border-2 p-4 transition ${batchStrategy === "fill_empty" ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20" : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)]/30"}`}>
                        <input type="radio" name="strategy" value="fill_empty" checked={batchStrategy === "fill_empty"} onChange={() => { setDraftRestored(false); setBatchStrategy("fill_empty"); }} className="sr-only" />
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${batchStrategy === "fill_empty" ? "border-[var(--color-primary)]" : "border-[var(--color-border)]"}`}>
                          {batchStrategy === "fill_empty" ? <span className="h-2.5 w-2.5 rounded-full bg-[var(--color-primary)]" /> : null}
                        </span>
                        <div>
                          <p className="text-sm font-semibold text-[var(--ink)]">仅补全空字段</p>
                          <p className="text-xs text-[var(--color-text-secondary)]">只填充当前为空的内容，已有数据保留</p>
                        </div>
                      </label>
                      <label className={`flex flex-1 cursor-pointer items-center gap-3 rounded-xl border-2 p-4 transition ${batchStrategy === "force_overwrite" ? "border-amber-500 bg-amber-50/40" : "border-[var(--color-border)] bg-white/60 hover:border-amber-400/30"}`}>
                        <input type="radio" name="strategy" value="force_overwrite" checked={batchStrategy === "force_overwrite"} onChange={() => { setDraftRestored(false); setBatchStrategy("force_overwrite"); }} className="sr-only" />
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${batchStrategy === "force_overwrite" ? "border-amber-500" : "border-[var(--color-border)]"}`}>
                          {batchStrategy === "force_overwrite" ? <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> : null}
                        </span>
                        <div>
                          <p className="text-sm font-semibold text-[var(--ink)]">强制重新生成</p>
                          <p className="text-xs text-[var(--color-text-secondary)]">重新生成并覆盖指定字段的内容</p>
                        </div>
                      </label>
                    </div>
                  </section>

                  {/* Field selection */}
                  <section className="space-y-3">
                    <p className="text-sm font-semibold text-[var(--ink)]">补全字段</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">选择需要 AI 补全的字段（至少选一项）</p>
                    <label className="flex cursor-pointer items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-white/60 px-3.5 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)]/30 hover:bg-white/90 select-none">
                      <span className="relative flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 border-[var(--color-border)] bg-white transition-all [&:has(input:checked)]:border-[var(--color-primary)] [&:has(input:checked)]:bg-[var(--color-primary)]">
                        <input
                          type="checkbox"
                          checked={ALL_BATCH_FIELDS.every(f => batchFields.includes(f))}
                          onChange={() => setBatchFields(batchFields.length === ALL_BATCH_FIELDS.length ? [] : [...ALL_BATCH_FIELDS])}
                          className="peer absolute inset-0 cursor-pointer opacity-0"
                        />
                        <Check className="h-3.5 w-3.5 text-white opacity-0 transition-opacity peer-checked:opacity-100" />
                      </span>
                      全选
                      <span className="ml-auto rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-primary-dark)]">已选 {batchFields.length}/{ALL_BATCH_FIELDS.length}</span>
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      {ALL_BATCH_FIELDS.map((value) => {
                        const labels: Record<string, string> = {
                          answer: "题目答案", analysis: "题目解析", knowledge_points: "知识点",
                          difficulty: "难度等级", subject_id: "科目", question_type: "题型",
                          stem: "题干修复", options: "选项格式化", tips: "解题技巧", tags: "题目标签",
                        };
                        return (
                        <label key={value} className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition ${
                          batchFields.includes(value)
                            ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/15"
                            : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)]/30"
                        }`}>
                          <span className={`relative flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition ${
                            batchFields.includes(value)
                              ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                              : "border-[var(--color-border)] bg-white"
                          }`}>
                            <input type="checkbox" checked={batchFields.includes(value)} onChange={() => toggleBatchField(value)} className="peer absolute inset-0 cursor-pointer opacity-0" />
                            <Check className={`h-3.5 w-3.5 text-white transition-opacity ${batchFields.includes(value) ? "opacity-100" : "opacity-0"}`} />
                          </span>
                          <span className="text-sm text-[var(--ink)]">{labels[value]}</span>
                        </label>
                      );
                    })}
                    </div>
                  </section>
                </>
              ) : (
                /* Results */
                <section className="space-y-3">
                  <div className="flex items-center gap-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">成功</span>
                      <span className="text-xl font-bold text-[var(--color-success)]">{batchResult.succeeded}</span>
                    </div>
                    <div className="h-8 w-px bg-[var(--color-border)]" />
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">失败</span>
                      <span className="text-xl font-bold text-[var(--color-danger)]">{batchResult.failed}</span>
                    </div>
                    <div className="h-8 w-px bg-[var(--color-border)]" />
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">跳过</span>
                      <span className="text-xl font-bold text-[var(--color-text-hint)]">{batchResult.skipped}</span>
                    </div>
                  </div>
                  {batchResult.items.filter((i) => i.status !== "success").length > 0 ? (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">失败/跳过明细</p>
                      {batchResult.items.filter((i) => i.status !== "success").map((item) => (
                        <div
                          key={item.import_id}
                          className={`rounded-xl border px-4 py-3 text-sm ${
                            item.status === "failed"
                              ? "border-[var(--color-danger)]/40 bg-[var(--color-danger-light)]/30"
                              : "border-[var(--color-border)] bg-white/60"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {item.status === "failed" ? (
                              <AlertTriangle className="h-4 w-4 shrink-0 text-[var(--color-danger)]" />
                            ) : null}
                            <span className="font-mono text-xs text-[var(--color-text-hint)]">#{item.import_id}</span>
                            <span className={`text-xs font-medium ${item.status === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-text-hint)]"}`}>
                              {item.status === "failed" ? "失败" : "跳过"}
                            </span>
                          </div>
                          {item.error ? (
                            <p className={`mt-1.5 whitespace-pre-wrap text-xs leading-relaxed ${
                              item.status === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-text-secondary)]"
                            }`}>
                              {item.error}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              )}
            </div>

            {/* Footer actions */}
            <div className="sticky bottom-0 border-t border-[var(--color-border)] bg-white/95 px-6 py-4 backdrop-blur-xl">
              <div className="flex items-center justify-end gap-2">
                {batchResult ? (
                  <Button variant="primary" onClick={() => { setShowBatchComplete(false); setBatchResult(null); }}>
                    完成
                  </Button>
                ) : (
                  <>
                    <Button variant="ghost" onClick={() => setShowBatchComplete(false)} disabled={executing}>
                      取消
                    </Button>
                    <Button variant="primary" disabled={executing || batchFields.length === 0} onClick={executeBatchComplete}>
                      {executing ? (
                        <>
                          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                          补全中...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4" />
                          执行补全
                        </>
                      )}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </aside>
        </div>
      ) : null}

      {showBatchAnswerFill ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-[rgba(16,24,40,0.28)]" role="presentation" onClick={() => { if (!batchAnswerExecuting) { setShowBatchAnswerFill(false); } }}>
          <aside role="dialog" aria-modal="true" className="scholar-panel flex h-full w-full max-w-xl flex-col overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="scholar-panel-header sticky top-0 z-10 px-6 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h4 className="font-display text-xl font-bold text-[var(--ink)]">快速补充答案</h4>
                  <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                    批次 <span className="font-mono text-xs font-semibold text-[var(--ink)]">{currentBatchId}</span>
                    {batchAnswerApplyResult ? (
                      <span className="ml-2">· 已更新 <span className="font-semibold text-emerald-600">{batchAnswerApplyResult.updated_count}</span> 题</span>
                    ) : batchAnswerPreview ? (
                      <span className="ml-2">· 预览 <span className="font-semibold text-[var(--ink)]">{batchAnswerPreview.summary.writable_count}</span> 题可写入</span>
                    ) : imageApplyResult ? (
                      <span className="ml-2">· 已更新答案 <span className="font-semibold text-emerald-600">{imageApplyResult.updated_answer_count}</span> 解析 <span className="font-semibold text-emerald-600">{imageApplyResult.updated_analysis_count}</span></span>
                    ) : imagePreviewResult ? (
                      <span className="ml-2">· 匹配 <span className="font-semibold text-[var(--ink)]">{imagePreviewResult.summary.matched_count}</span> 题</span>
                    ) : null}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {batchAnswerApplyResult ? (
                    <Button variant="ghost" className="h-7 px-2 text-[11px] text-[var(--color-text-hint)]" onClick={handleBatchAnswerReset}>
                      清空
                    </Button>
                  ) : null}
                  <button className="shrink-0 rounded-lg p-1.5 text-[var(--color-text-hint)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)] transition disabled:opacity-40" onClick={() => { if (!batchAnswerExecuting) setShowBatchAnswerFill(false); }} disabled={batchAnswerExecuting}>
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              {/* Tab switcher */}
              {!batchAnswerApplyResult && !imageApplyResult ? (
                <div className="mt-3 flex gap-0.5 rounded-xl border border-[var(--color-border-light)] bg-[var(--color-bg)]/70 p-0.5">
                  <button
                    className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-150 ${
                      batchAnswerFillTab === "text"
                        ? "bg-white text-[var(--ink)] shadow-sm border border-[var(--color-border-light)]"
                        : "text-[var(--color-text-secondary)] hover:text-[var(--ink)] border border-transparent"
                    }`}
                    onClick={() => setBatchAnswerFillTab("text")}
                  >
                    文字输入
                  </button>
                  <button
                    className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-150 ${
                      batchAnswerFillTab === "image"
                        ? "bg-white text-[var(--ink)] shadow-sm border border-[var(--color-border-light)]"
                        : "text-[var(--color-text-secondary)] hover:text-[var(--ink)] border border-transparent"
                    }`}
                    onClick={() => setBatchAnswerFillTab("image")}
                  >
                    图片导入
                  </button>
                </div>
              ) : null}
              {batchAnswerExecuting || imageExecuting ? (
                <div className="absolute bottom-0 left-0 right-0 z-20 h-0.5 overflow-hidden bg-[var(--color-primary)]/10">
                  <div className="h-full w-1/2 rounded-full bg-[var(--color-primary)]" style={{ animation: "loadingBar 1.2s cubic-bezier(0.4, 0, 0.2, 1) infinite" }} />
                </div>
              ) : null}
            </div>

            <div className="relative flex-1 px-6 py-5 space-y-6">
              {batchAnswerExecuting ? (
                <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                  <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                    <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                    <span className="text-sm text-[var(--color-text-secondary)]">{batchAnswerPreview ? "正在写入答案…" : "正在解析答案…"}</span>
                  </div>
                </div>
              ) : null}

              {/* Error */}
              {batchAnswerError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  <div className="flex items-start gap-2">
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                    <span>{batchAnswerError}</span>
                  </div>
                </div>
              ) : null}

              {/* Step 1: Input */}
              {!batchAnswerPreview && !batchAnswerApplyResult ? (
                <div className="space-y-4">
                  <div>
                    <p className="mb-1 text-sm font-semibold text-[var(--ink)]">输入答案串</p>
                    <p className="mb-3 text-xs text-[var(--color-text-secondary)]">
                      输入连续的答案字母（如 abcda），或使用逗号/空格/换行分隔。也支持 AB/AC 等多选题格式。
                    </p>
                    <textarea
                      className="w-full h-32 rounded-xl border border-[var(--color-border)] bg-white p-3 text-sm outline-none transition-colors focus:border-[var(--color-primary)] resize-none font-mono"
                      placeholder="示例：abcda&#10;或：A,B,C,D,A&#10;或：A&#10;B&#10;C&#10;D&#10;A&#10;或：AB, CD, A（多选题用分隔符）"
                      value={batchAnswerRawText}
                      onChange={(e) => setBatchAnswerRawText(e.target.value)}
                    />
                  </div>
                  <Button
                    className="h-9 w-full text-sm"
                    disabled={!batchAnswerRawText.trim() || batchAnswerExecuting}
                    onClick={handleBatchAnswerPreview}
                  >
                    <Eye className="mr-1.5 h-4 w-4" />
                    预览解析结果
                  </Button>
                </div>
              ) : null}

              {/* Step 2: Preview table */}
              {batchAnswerPreview && !batchAnswerApplyResult ? (
                <BatchAnswerPreview
                  preview={batchAnswerPreview}
                  executing={batchAnswerExecuting}
                  onApply={handleBatchAnswerApply}
                />
              ) : null}

              {/* Step 3: Apply result */}
              {batchAnswerApplyResult ? (
                <BatchAnswerResult result={batchAnswerApplyResult} onClose={() => setShowBatchAnswerFill(false)} />
              ) : null}

              {/* ── Image Tab Content ── */}
              {batchAnswerFillTab === "image" ? (
                <>
                  {imageExecuting ? (
                    <div className="absolute inset-0 z-10 rounded-xl bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                      <div className="flex flex-col items-center gap-2 rounded-xl bg-white/90 px-5 py-4 shadow-sm">
                        <span className="inline-block h-6 w-6 animate-spin rounded-full border-[3px] border-[var(--color-border)] border-t-[var(--color-primary)]" />
                        <span className="text-sm text-[var(--color-text-secondary)]">{imagePreviewResult ? "正在写入答案…" : "正在识别图片…"}</span>
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
                  {!imagePreviewResult && !imageApplyResult ? (
                    <div className="space-y-4">
                      <div className="rounded-xl border-2 border-dashed border-[var(--color-border)] p-6 text-center transition hover:border-[var(--color-primary)]/40">
                        <input
                          type="file"
                          accept="image/jpeg,image/png"
                          multiple
                          className="hidden"
                          id="image-upload-input"
                          onChange={handleImageFileChange}
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
                                  onClick={() => removeImageFile(idx)}
                                  className="shrink-0 rounded p-0.5 text-[var(--color-text-hint)] hover:bg-red-50 hover:text-red-600 transition"
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
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition ${
                              imageImportMode === "answer_only"
                                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
                                : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/30"
                            }`}
                            onClick={() => setImageImportMode("answer_only")}
                          >
                            仅答案
                          </button>
                          <button
                            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition ${
                              imageImportMode === "answer_analysis"
                                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/20 text-[var(--color-primary-dark)]"
                                : "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] hover:border-[var(--color-primary)]/30"
                            }`}
                            onClick={() => setImageImportMode("answer_analysis")}
                          >
                            答案+解析
                          </button>
                        </div>
                      </div>

                      <Button
                        className="h-9 w-full text-sm"
                        disabled={imageFiles.length === 0 || imageExecuting}
                        onClick={handleImagePreview}
                      >
                        <Eye className="mr-1.5 h-4 w-4" />
                        预览识别结果
                      </Button>
                    </div>
                  ) : null}

                  {/* Step 2: Preview results */}
                  {imagePreviewResult && !imageApplyResult ? (
                    <ImageAnswerPreview
                      preview={imagePreviewResult}
                      executing={imageExecuting}
                      onApply={handleImageApply}
                    />
                  ) : null}

                  {/* Step 3: Apply result */}
                  {imageApplyResult ? (
                    <ImageAnswerResult result={imageApplyResult} onClose={() => setShowBatchAnswerFill(false)} />
                  ) : null}
                </>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.action === "low-risk-batch-approve" ? "批量通过低风险题" : confirmState?.action?.includes("reject") ? "驳回导入题目" : "通过导入题目"}
        description={
          confirmState?.action === "low-risk-batch-approve"
              ? `将自动通过当前批次中所有低风险题（risk_level=low）并跳过高风险和需检查题。高风险和需检查题不会被通过。`
              : confirmState?.action === "batch-approve" && selectedIds.size > 0
                ? `将对已选的 ${selectedIds.size} 条导入题目执行批量通过操作。`
                : confirmState?.action === "batch-reject" && selectedIds.size > 0
                  ? `将对已选的 ${selectedIds.size} 条导入题目执行批量驳回操作。`
                  : "操作会更新 question_imports 暂存审核状态。"
        }
        confirmText={confirmState?.action === "low-risk-batch-approve" ? "批量通过低风险" : confirmState?.action?.includes("reject") ? "驳回" : "通过"}
        danger={Boolean(confirmState?.action.includes("reject"))}
        loading={actionMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => confirmState && actionMutation.mutate(confirmState)}
      >
        {confirmState?.action === "reject" || confirmState?.action === "batch-reject" ? (
          <Input placeholder="驳回原因" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} />
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
