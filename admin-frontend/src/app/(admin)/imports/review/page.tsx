"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, FileText, Sparkles, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatChinaClock } from "@/lib/time";
import { apiRequest, toQuery } from "@/lib/api/client";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { useOutsideClick } from "@/lib/use-outside-click";
import { reviewPageStyles } from "./review-page-styles";
import { executeSegmentReplace, resolveSegmentFileChange } from "./review-segment-replace";
import { buildQuestionTypeChange } from "./review-question-type-change";
import type { BatchAnswerPreviewResponse, BatchAnswerApplyResponse, BatchCompleteResponse, ImportBatchListItem, ImportQuestionItem, PaginatedResponse } from "@/lib/api/types";
import {
  reduceMultiBlankEditState,
  syncDerivedMultiBlankFields,
  type MultiBlankAction,
  type MultiBlankEditState,
} from "./components/multi-blank-choice-utils";
import { isMultiBlankChoice, type EditState } from "./review-edit-state";
import {
  buildReviewQueueParams,
  createDefaultReviewFilters,
} from "./review-query-state";
import { getLeafSubjectOptions } from "./review-subject-state";
import { getSourceQuestionNo } from "./review-source-location";
import {
  createReviewEditSession,
  createReviewPreviewState,
  createReviewServerEditState,
  hasUnsavedReviewDrawerChanges,
} from "./review-drawer-state";
import {
  clearBatchCompleteDraft,
  createDefaultBatchCompleteDraft,
  loadBatchCompleteDraft,
  saveBatchCompleteDraft,
  toggleBatchCompleteField,
  type BatchCompleteStrategy,
} from "./review-batch-complete-draft";
import {
  answersEquivalent,
  completeSuggestionFromItem,
  stringSuggestion,
} from "./review-completion-suggestion";
import { buildReviewConfirmDialogState } from "./review-confirm-dialog-state";
import type { ReviewActionState } from "./review-action-requests";
import {
  createReviewActionDialogState,
  reduceReviewActionDialogState,
} from "./review-action-dialog-state";
import { reduceReviewFilterSelection } from "./review-filter-selection";
import {
  isReviewFacetFilter,
  reduceReviewFilters,
  type ReviewFilterKey,
} from "./review-filter-interaction";
import { toggleAllSelection, toggleSingleSelection } from "@/lib/selection-ops";
import {
  buildBatchAnswerViewState,
  type BatchAnswerFillTab,
} from "./review-batch-answer-view-state";
import { buildBatchCompleteResultState } from "./review-batch-complete-result-state";
import {
  buildBatchCompleteFeedback,
  validateBatchCompleteRequest,
} from "./review-batch-complete-request";
import { useReviewActionMutation } from "./hooks/use-review-action-mutation";
import { useReviewQuestionDetail } from "./hooks/use-review-question-detail";
import { useReviewUpdateMutation } from "./hooks/use-review-update-mutation";
import { useReviewAnswerMutations } from "./hooks/use-review-answer-mutations";
import { useReviewCompleteMutation } from "./hooks/use-review-complete-mutation";
import { useReviewBatchAnswerMutations } from "./hooks/use-review-batch-answer-mutations";
import { useReviewBatchCompleteMutation } from "./hooks/use-review-batch-complete-mutation";
import { useReviewImageAnswerFlow } from "./hooks/use-review-image-answer-flow";
import { useReviewSegmentDrag } from "./hooks/use-review-segment-drag";
import { ReviewFilterToolbar } from "./components/review-filter-toolbar";
import { ReviewList } from "./components/review-list";
import { ReviewPagination } from "./components/review-pagination";
import { ReviewBatchCompleteDialog } from "./components/review-batch-complete-dialog";
import { ReviewBatchAnswerDialog } from "./components/review-batch-answer-dialog";
import { ReviewDetailDrawer } from "./components/review-detail-drawer";
import { extractOptionVisualModel, type OptionVisualModel } from "@/lib/option-visual-utils";
import { normalizeStructuredTableSegment } from "@/lib/structured-table";
import {
  isBlockedByVisualIssues as isBlockedByVisualIssuesHelper,
  buildVisualBlockReasons,
} from "@/lib/review-page-utils";

type ConfirmState = ReviewActionState | null;

export default function ImportReviewPage() {
  const searchParams = useSearchParams();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "import:write");
  const batchIdParam = searchParams.get("batch_id") || "";
  const [filters, setFilters] = useState(createDefaultReviewFilters);
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
  const [actionDialog, dispatchActionDialog] = useReducer(
    reduceReviewActionDialogState,
    undefined,
    createReviewActionDialogState,
  );
  const { selectedIds, confirmState, rejectReason, message } = actionDialog;
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [completedItem, setCompletedItem] = useState<ImportQuestionItem | null>(null);
  const [editState, setEditState] = useState<EditState | null>(null);
  const updateSelectedIds = (
    next: Set<number> | ((current: Set<number>) => Set<number>),
  ) => {
    if (typeof next === "function") {
      dispatchActionDialog({ type: "update-selected-ids", update: next });
    } else {
      dispatchActionDialog({ type: "selected-ids", selectedIds: next });
    }
  };
  const updateConfirmState = (next: ConfirmState) => {
    dispatchActionDialog(next
      ? { type: "open", action: next }
      : { type: "cancel" });
  };
  const updateRejectReason = (next: string) => {
    dispatchActionDialog({ type: "reject-reason", reason: next });
  };
  const updateMessage = (next: string | null) => {
    dispatchActionDialog({ type: "message", message: next });
  };
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => updateMessage(null), 5000);
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
  const syncServerEditState = useCallback((item: ImportQuestionItem) => {
    const serverState = createReviewServerEditState(item);
    setEditState(serverState.editState);
    editSnapshotRef.current = serverState.editSnapshot;
  }, []);

  const [viewMode, setViewMode] = useState<"list" | "table">("list");
  const [showBatchComplete, setShowBatchComplete] = useState(false);
  const [batchFields, setBatchFields] = useState<string[]>(() => createDefaultBatchCompleteDraft().fields);
  const [batchStrategy, setBatchStrategy] = useState<BatchCompleteStrategy>("fill_empty");
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
  const [batchAnswerFillTab, setBatchAnswerFillTab] = useState<BatchAnswerFillTab>("text");
  const currentBatchId = filters.batch_id || batchIdParam;
  const batchResultView = buildBatchCompleteResultState(batchResult);

  const syncedDetailRef = useRef<Set<number>>(new Set());
  const segmentReplaceInputRef = useRef<HTMLInputElement>(null);
  const segmentReplaceIdxRef = useRef(-1);
  const segmentDrag = useReviewSegmentDrag(editedSegments, setEditedSegments);

  // Close batch dropdown on outside click
  useOutsideClick(batchDropdownRef, batchDropdownOpen, () => setBatchDropdownOpen(false));

  // Close subject dropdown on outside click (portal bypasses drawer's onBlur chain)
  useOutsideClick(subjectBtnRef, subjectDropdownOpen, () => setSubjectDropdownOpen(false));

  // Close subject edit dropdown on outside click (portal bypasses drawer's onBlur chain)
  useOutsideClick(subjectEditBtnRef, subjectEditDropdownOpen, () => setSubjectEditDropdownOpen(false));

  const batchCompleteDraftStorage = () => localStorage;

  const saveDraft = (fields: string[], strategy: BatchCompleteStrategy) => {
    saveBatchCompleteDraft(batchCompleteDraftStorage, fields, strategy);
  };

  const clearDraft = () => {
    clearBatchCompleteDraft(batchCompleteDraftStorage);
  };

  const loadDraft = () => loadBatchCompleteDraft(batchCompleteDraftStorage);

  // restore draft on mount
  useEffect(() => {
    const draft = loadDraft();
    if (draft) {
      setBatchFields(draft.fields);
      setBatchStrategy(draft.strategy);
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

  const {
    detail,
    detailReady: previewDetailReady,
    beginSession: beginDetailSession,
    endSession: endDetailSession,
  } = useReviewQuestionDetail(previewId, apiRequest);

  const queuedPreviewItem = items.find((item) => item.id === previewId) ?? null;
  const previewItem = (previewDetailReady ? detail.data : null) ??
    (completedItem?.id === previewId ? completedItem : queuedPreviewItem);

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

  const isBlockedByVisualIssues = isBlockedByVisualIssuesHelper(
    optionVisualModel,
    unresolvedTableCount,
    runtimeIssues,
  );

  // When full detail loads for the first time after drawer open, sync editState
  useEffect(() => {
    if (previewDetailReady && detail.data && previewId === detail.data.id && !editing) {
      if (!syncedDetailRef.current.has(previewId)) {
        syncedDetailRef.current.add(previewId);
        syncServerEditState(detail.data);
      }
    }
  }, [detail.data, editing, previewDetailReady, previewId, syncServerEditState]);

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
      onSuccess: (feedback) => {
        updateMessage(feedback.message);
        if (feedback.closeDrawer) closeDrawer();
      },
      onReset: () => {
        updateSelectedIds(new Set());
        updateConfirmState(null);
        updateRejectReason("");
      },
      onError: (error) => {
        updateMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
      },
  });

  const visualBlockReasons = buildVisualBlockReasons(
    optionVisualModel,
    unresolvedTableCount,
    runtimeIssues,
  );

  const updateMutation = useReviewUpdateMutation({
    previewId,
    editState,
    previewItem,
    editedSegments,
    visualBlockReasons,
    request: apiRequest,
  }, {
    onSaved: (result) => {
      updateMessage(`导入题目 #${result.id} 已保存。`);
      syncServerEditState(result);
      setEditedSegments(null);
      setCompletedItem(result);
      syncedDetailRef.current.delete(result.id);
    },
    onAfterInvalidation: () => setEditing(false),
    onError: (error) => {
      updateMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    },
  });

  const completeMutation = useReviewCompleteMutation(apiRequest, {
    onCompleted: (result) => {
      const missingFields = result.missing.length > 0 ? `（补全字段：${result.missing.join("、")}）` : "";
      updateMessage(
        result.missing.length === 0
          ? "当前题目信息已完整，无需补全。"
          : `AI 补全完成${missingFields}，请复核后保存/通过。`,
      );
    },
    onDetailSynced: (result) => {
      if (previewId !== result.item.id) return;
      // Keep the active drawer in sync immediately.  The detail query has higher
      // precedence than completedItem, so leaving its old cache entry in place
      // makes freshly completed parsed_analysis look as if it was never saved.
      syncedDetailRef.current.add(result.item.id);
      setPreviewId(result.item.id);
      setCompletedItem(result.item);
      syncServerEditState(result.item);
    },
    onError: (error) => updateMessage(error instanceof Error ? error.message : "AI 补全失败，请稍后重试。"),
  });

  const { quickAnswer: quickAnswerMutation, verifyAnswer: verifyAnswerMutation } = useReviewAnswerMutations(
    apiRequest,
    {
      onQuickAnswerSaved: (result) => {
        const srcNo = getSourceQuestionNo(result);
        updateMessage(srcNo ? `原题${srcNo} 答案已保存` : `导入题目 #${result.id} 答案已保存`);
        setQuickAnswerDrafts((prev) => {
          const next = { ...prev };
          delete next[result.id];
          return next;
        });
      },
      onAnswerVerified: (result) => {
        const srcNo = getSourceQuestionNo(result);
        updateMessage(srcNo ? `原题${srcNo} 答案已确认为正确` : `导入题目 #${result.id} 答案已确认为正确`);
      },
      onError: (error, action) => {
        updateMessage(error instanceof Error
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
  const {
    imageFiles,
    imageImportMode,
    imagePreviewResult,
    imageApplyResult,
    imageError,
    imageExecuting,
    handleImagePreview,
    handleImageApply,
    handleImageFileChange,
    removeImageFile,
    setImageImportMode,
  } = useReviewImageAnswerFlow(apiRequest);
  const handleImageFileSelection = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      if (imageExecuting) return;
      handleImageFileChange(event);
    },
    [handleImageFileChange, imageExecuting],
  );
  const removeImageFileSafely = useCallback(
    (index: number) => {
      if (!imageExecuting) removeImageFile(index);
    },
    [imageExecuting, removeImageFile],
  );
  const selectImageImportMode = useCallback(
    (mode: "answer_only" | "answer_analysis") => {
      if (!imageExecuting) setImageImportMode(mode);
    },
    [imageExecuting, setImageImportMode],
  );
  const batchAnswerView = buildBatchAnswerViewState({
    tab: batchAnswerFillTab,
    textPreview: batchAnswerPreview,
    textResult: batchAnswerApplyResult,
    imagePreview: imagePreviewResult,
    imageResult: imageApplyResult,
  });

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

  const toggleBatchField = (field: string) => {
    setDraftRestored(false);
    setBatchFields((prev) => toggleBatchCompleteField(prev, field));
  };

  const batchCompleteMutation = useReviewBatchCompleteMutation(apiRequest, {
    onStarted: () => { setExecuting(true); setBatchResult(null); },
    onCompleted: (result) => {
      setBatchResult(result);
      clearDraft();
      updateMessage(buildBatchCompleteFeedback(result));
    },
    onDetailSynced: (refreshed) => {
      syncedDetailRef.current.add(refreshed.id);
      setCompletedItem(refreshed);
      syncServerEditState(refreshed);
    },
    onError: (error) => {
      updateMessage(error instanceof Error ? error.message : "批量补全失败，请稍后重试。");
    },
    onFinished: () => setExecuting(false),
  });
  const executeBatchComplete = () => {
    const validation = validateBatchCompleteRequest(
      Array.from(selectedIds), batchFields, batchStrategy,
    );
    if (!validation.ok) {
      updateMessage(validation.message);
      return;
    }
    batchCompleteMutation.mutate({
      importIds: validation.args.importIds,
      fields: validation.args.fields,
      strategy: validation.args.strategy,
      openPreviewId: previewId,
    });
  };

  const updateFilter = (key: ReviewFilterKey, value: string) => {
    setFilters((current) => {
      const nextFilters = reduceReviewFilters(current, key, value);
      updateSelectedIds((selectedIds) =>
        reduceReviewFilterSelection(
          { filters: nextFilters, selectedIds },
          isReviewFacetFilter(key) ? "facet" : "keyword",
        ).selectedIds,
      );
      return nextFilters;
    });
    resetFilterScopedReviewState();
  };

  const updateKeywordFilter = (keyword: string) => {
    setFilters((current) => {
      const nextFilters = { ...current, keyword };
      updateSelectedIds((selectedIds) =>
        reduceReviewFilterSelection({ filters: nextFilters, selectedIds }, "keyword").selectedIds,
      );
      return nextFilters;
    });
  };

  const resetFilters = () => {
    const nextFilters = createDefaultReviewFilters();
    setFilters(nextFilters);
    updateSelectedIds((selectedIds) =>
      reduceReviewFilterSelection({ filters: nextFilters, selectedIds }, "reset").selectedIds,
    );
    resetFilterScopedReviewState();
  };

  const toggleAll = () => {
    updateSelectedIds(() => toggleAllSelection(items.map((item) => item.id), allChecked));
  };

  const resetFilterScopedReviewState = () => {
    endDetailSession();
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
  };

  const toggleOne = (id: number) => {
    updateSelectedIds((current) => toggleSingleSelection(current, id));
  };

  const confirmDialogState = buildReviewConfirmDialogState(confirmState, selectedIds.size);

  const hasUnsavedDraft = useCallback(() => (
    hasUnsavedReviewDrawerChanges({
      editing,
      editState,
      editSnapshot: editSnapshotRef.current,
      editedSegments,
      segmentSnapshot: segmentSnapshotRef.current,
    })
  ), [editing, editState, editedSegments]);

  const openPreview = (item: ImportQuestionItem) => {
    if (segmentUploading >= 0 || completeMutation.isPending) return;
    if (previewId !== null) {
      if (
        hasUnsavedDraft() &&
        !window.confirm("有未保存的修改，确定切换到其他题目吗？")
      ) {
        return;
      }
    }
    const preview = createReviewPreviewState(item);
    syncedDetailRef.current.clear();
    beginDetailSession(item.id);
    setPreviewId(preview.previewId);
    setCompletedItem(null);
    setEditState(preview.editState);
    editSnapshotRef.current = preview.editSnapshot;
    segmentSnapshotRef.current = preview.segmentSnapshot;
    setEditing(preview.editing);
    setDetailView(preview.detailView);
  };

  const closeDrawer = useCallback(() => {
    if (segmentUploading >= 0 || completeMutation.isPending) return;
    if (hasUnsavedDraft()) {
      if (!window.confirm("有未保存的修改，确定关闭吗？")) return;
    }
    endDetailSession();
    setPreviewId(null);
    setCompletedItem(null);
    setEditState(null);
    setEditedSegments(null);
    setEditing(false);
    syncedDetailRef.current.clear();
  }, [
    completeMutation.isPending, endDetailSession, hasUnsavedDraft, segmentUploading,
    setEditState, setEditing, setEditedSegments,
  ]);

  useEffect(() => {
    if (previewId === null) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [previewId, closeDrawer]);

  const startEditing = () => {
    if (!previewId || !canWrite || !previewDetailReady) return;
    const segs = detail.data?.parsed_content?.segments as Array<Record<string, unknown>> | undefined;
    const session = createReviewEditSession(editState, segs);
    setEditedSegments(session.editedSegments);
    segmentSnapshotRef.current = session.segmentSnapshot;
    editSnapshotRef.current = session.editSnapshot;
    setEditing(session.editing);
  };

  const cancelEditing = () => {
    if (hasUnsavedDraft() && !window.confirm("有未保存的修改，确定取消编辑吗？")) return;
    if (previewItem) {
      syncServerEditState(previewItem);
    } else {
      setEditState(null);
    }
    setEditedSegments(null);
    setEditing(false);
  };

  /** 安全切换题型：保护多空选择题结构化数据；在单选/多选多空之间切换时保留分组 */
  const handleQuestionTypeChange = useCallback((newCode: string) => {
    if (!editState) return;
    const result = buildQuestionTypeChange({
      currentType: editState.question_type,
      newCode,
      hasMultiBlankGroups: !!editState.multiBlank?.groups && editState.multiBlank.groups.length > 0,
      confirmed: window.confirm("切换题型将清空多空选择分组数据，是否继续？"),
    });
    if (result.action === "noop") return;
    if (result.action === "clear_multi_blank") {
      setEditState({ ...editState, ...result.nextState });
    } else if (result.action === "init_multi_blank") {
      setEditState({ ...editState, ...result.nextState });
    } else {
      setEditState({ ...editState, ...result.nextState });
    }
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

  const handleSegmentReplace = useCallback(async (si: number, file: File) => {
    await executeSegmentReplace(si, file, {
      canWrite,
      previewId,
      setSegmentUploading,
      setEditedSegments,
      updateMessage,
      uploadSegmentImage: async (f: File) => {
        const formData = new FormData();
        formData.append("file", f);
        return apiRequest<{ url: string; filename: string }>("/imports/segment-image/upload", {
          method: "POST",
          body: formData,
        });
      },
    });
  }, [canWrite, previewId, apiRequest, setSegmentUploading, setEditedSegments, updateMessage]);

  const handleSegmentFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const { file, index } = resolveSegmentFileChange(e, segmentReplaceIdxRef.current);
    segmentReplaceIdxRef.current = -1;
    if (file && index >= 0) handleSegmentReplace(index, file);
  }, [handleSegmentReplace]);

  const canBatchOperate = items.length > 0 && (selectedIds.size > 0 || Boolean(filters.batch_id || batchIdParam));

  return (
    <div className="space-y-6">
      <style>{reviewPageStyles}</style>
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
              <button aria-label="关闭提示" className="rounded-lg px-3 py-1 text-[10px] font-medium text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]" onClick={() => updateMessage(null)}>关闭</button>
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
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!canWrite || !canBatchOperate} onClick={() => updateConfirmState({ action: "batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过
                </Button>
                <Button variant="secondary" className="h-8 px-3 text-xs" disabled={!canWrite || !(filters.batch_id || batchIdParam)} onClick={() => updateConfirmState({ action: "low-risk-batch-approve" })}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  批量通过低风险
                </Button>
                <Button variant="danger" className="h-8 px-3 text-xs" disabled={!canWrite || !canBatchOperate} onClick={() => updateConfirmState({ action: "batch-reject" })}>
                  <XCircle className="h-3.5 w-3.5" />
                  批量驳回
                </Button>
                <Button
                  variant="secondary"
                  className="h-8 px-3 text-xs"
                  disabled={!canWrite || selectedIds.size === 0}
                  onClick={() => { setShowBatchComplete(true); setBatchResult(null); }}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  AI 批量补全
                </Button>
                <Button
                  variant="secondary"
                  className="h-8 px-3 text-xs"
                  disabled={!canWrite || !currentBatchId}
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
          <ReviewFilterToolbar
            filters={filters}
            batchIdParam={batchIdParam}
            subjectOptions={subjectOptions}
            leafSubjectOptions={leafSubjectOptions}
            batches={batchesQuery.data?.items ?? []}
            batchesLoading={batchesQuery.isLoading}
            dropdownState={{
              risk: riskDropdownOpen,
              answerStatus: answerStatusDropdownOpen,
              subject: subjectDropdownOpen,
              batch: batchDropdownOpen,
              status: statusDropdownOpen,
            }}
            subjectButtonRef={subjectBtnRef}
            batchDropdownRef={batchDropdownRef}
            onKeywordChange={updateKeywordFilter}
            onFilterChange={updateFilter}
            onReset={resetFilters}
            onDropdownChange={(key, open) => {
              if (key === "risk") setRiskDropdownOpen(open);
              if (key === "answerStatus") setAnswerStatusDropdownOpen(open);
              if (key === "subject") setSubjectDropdownOpen(open);
              if (key === "batch") setBatchDropdownOpen(open);
              if (key === "status") setStatusDropdownOpen(open);
            }}
          />
        </CardHeader>
        <CardContent className="space-y-1.5 pt-0">
          <section className="space-y-1">
              <div className={`flex items-center gap-2 rounded-lg border border-[var(--color-border)]/40 bg-[var(--color-primary-light)]/10 px-3 py-1.5 ${selectedIds.size > 0 ? "" : "invisible"}`}>
                <span className="text-xs font-medium text-[var(--color-primary-dark)]">已选 {selectedIds.size} 题</span>
              </div>
              <ReviewList
                viewMode={viewMode}
                items={items}
                selectedIds={selectedIds}
                allChecked={allChecked}
                canWrite={canWrite}
                quickAnswerDrafts={quickAnswerDrafts}
                quickAnswerPending={quickAnswerMutation.isPending}
                verifyAnswerPending={verifyAnswerMutation.isPending}
                onToggleAll={toggleAll}
                onToggleOne={toggleOne}
                onOpenPreview={openPreview}
                onQuickAnswerDraftChange={(id, answer) => setQuickAnswerDrafts((prev) => ({ ...prev, [id]: answer }))}
                onQuickAnswerDraftReset={(id) => setQuickAnswerDrafts((prev) => {
                  const next = { ...prev };
                  delete next[id];
                  return next;
                })}
                onQuickAnswerSave={(id, answer) => quickAnswerMutation.mutate({ id, answer })}
                onVerifyAnswer={(id) => verifyAnswerMutation.mutate(id)}
                onReviewAction={(action, id) => updateConfirmState({ action, id })}
              />
              {!queue.isLoading && items.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-14 text-center">
                  <div className="empty-ink-drop mb-4" />
                  <p className="font-display text-lg font-semibold text-[var(--color-text-secondary)]">暂无待审核题目</p>
                  <p className="mt-1.5 max-w-xs text-xs text-[var(--color-text-hint)] leading-relaxed">所有导入题目已完成审核，或当前筛选条件没有匹配的记录</p>
                </div>
              ) : null}
              {queue.isError ? <p className="text-sm text-[var(--color-danger)]">待审核接口当前不可用。</p> : null}
            </section>

            <ReviewPagination
              page={page}
              total={queue.data?.total}
              currentPage={queue.data?.page}
              totalPages={queue.data?.total_pages}
              onPageChange={setPage}
            />
        </CardContent>
      </Card>

      <ReviewDetailDrawer
        open={previewId !== null && previewItem !== null && editState !== null}
        item={previewItem as ImportQuestionItem}
        editState={editState as EditState}
        canWrite={canWrite}
        detailView={detailView}
        editing={editing}
        subjectsLoading={subjectsQuery.isLoading}
        subjectOptions={subjectOptions}
        leafSubjectOptions={leafSubjectOptions}
        optionVisualModel={optionVisualModel}
        completeSuggestion={completeSuggestion}
        answerSuggestion={answerSuggestion}
        answerSuggestionApplied={answerSuggestionApplied}
        completePending={completeMutation.isPending}
        updatePending={updateMutation.isPending}
        previewDetailReady={previewDetailReady}
        segmentUploading={segmentUploading}
        editedSegments={editedSegments}
        segmentDrag={segmentDrag}
        segmentReplaceInputRef={segmentReplaceInputRef}
        subjectEditDropdownOpen={subjectEditDropdownOpen}
        subjectEditDropdownStyle={subjectEditDropdownStyle}
        subjectEditButtonRef={subjectEditBtnRef}
        isBlockedByVisualIssues={isBlockedByVisualIssues}
        onClose={closeDrawer}
        onDetailViewChange={setDetailView}
        onEditStateChange={setEditState}
        onRuntimeIssue={(issue) => setRuntimeIssues((prev) => prev.includes(issue) ? prev : [...prev, issue])}
        onApplyAnswerSuggestion={(answer) => setEditState((prev) => prev ? { ...prev, answer } : prev)}
        onQuestionTypeChange={handleQuestionTypeChange}
        onSubjectDropdownOpenChange={setSubjectEditDropdownOpen}
        onSubjectDropdownStyleChange={setSubjectEditDropdownStyle}
        onSegmentsChange={setEditedSegments}
        onSegmentFileChange={handleSegmentFileChange}
        onSegmentReplace={(index) => {
          segmentReplaceIdxRef.current = index;
          segmentReplaceInputRef.current?.click();
        }}
        onMultiBlankAction={onMultiBlankAction}
        onStartEditing={startEditing}
        onCancelEditing={cancelEditing}
        onSave={() => updateMutation.mutate()}
        onApprove={() => { if (previewItem) updateConfirmState({ action: "approve", id: previewItem.id }); }}
        onReject={() => { if (previewItem) updateConfirmState({ action: "reject", id: previewItem.id }); }}
        onComplete={() => {
          if (previewItem) completeMutation.mutate(previewItem.id);
        }}
      />
      <ReviewBatchCompleteDialog
        open={showBatchComplete}
        selectedCount={selectedIds.size}
        executing={executing}
        batchFields={batchFields}
        batchStrategy={batchStrategy}
        batchResult={batchResult}
        batchResultView={batchResultView}
        draftRestored={draftRestored}
        autoSaveHint={autoSaveHint}
        onClearDraft={() => {
          const draft = createDefaultBatchCompleteDraft();
          clearDraft();
          setDraftRestored(false);
          setBatchFields(draft.fields);
          setBatchStrategy(draft.strategy);
          setAutoSaveHint("草稿已清空");
        }}
        onStrategyChange={(strategy) => {
          setDraftRestored(false);
          setBatchStrategy(strategy);
        }}
        onFieldsChange={setBatchFields}
        onToggleField={toggleBatchField}
        onClose={() => setShowBatchComplete(false)}
        onExecute={executeBatchComplete}
        onFinish={() => setBatchResult(null)}
      />
      <ReviewBatchAnswerDialog
        open={showBatchAnswerFill}
        batchId={currentBatchId}
        view={batchAnswerView}
        tab={batchAnswerFillTab}
        rawText={batchAnswerRawText}
        textPreview={batchAnswerPreview}
        textResult={batchAnswerApplyResult}
        textExecuting={batchAnswerExecuting}
        textError={batchAnswerError}
        imageFiles={imageFiles}
        imageMode={imageImportMode}
        imagePreview={imagePreviewResult}
        imageResult={imageApplyResult}
        imageExecuting={imageExecuting}
        imageError={imageError}
        onTabChange={setBatchAnswerFillTab}
        onRawTextChange={setBatchAnswerRawText}
        onTextPreview={handleBatchAnswerPreview}
        onTextApply={handleBatchAnswerApply}
        onReset={handleBatchAnswerReset}
        onClose={() => setShowBatchAnswerFill(false)}
        onImageFileChange={handleImageFileSelection}
        onRemoveImageFile={removeImageFileSafely}
        onImageModeChange={selectImageImportMode}
        onImagePreview={() => handleImagePreview(currentBatchId)}
        onImageApply={() => handleImageApply(currentBatchId)}
      />
      <ConfirmDialog
        open={confirmState !== null}
        {...confirmDialogState}
        loading={actionMutation.isPending}
        onCancel={() => updateConfirmState(null)}
        onConfirm={() => {
          if (canWrite && confirmState) actionMutation.mutate(confirmState);
        }}
      >
        {confirmDialogState.showRejectReason ? (
          <Input placeholder="驳回原因" value={rejectReason} onChange={(event) => updateRejectReason(event.target.value)} />
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
