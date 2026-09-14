"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ClipboardCheck,
  History,
  ListOrdered,
  LoaderCircle,
  Plus,
  Sigma,
  Timer,
  Save,
  Search,
  Trash2,
  X,
  GripVertical,
} from "lucide-react";

import {
  EmptyState,
  FieldLabel,
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  MetricCard,
  MetricStrip,
  StatusBadge,
  ManagementSkeletonRows,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type {
  AdminExamPastExamCandidatesResponse,
  AdminExamPaperDetail,
  AdminExamPaperQuestionItem,
  AdminExamPaperType,
  AdminQuestion,
  PaginatedResponse,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { ImportToast, type ImportToastTone } from "../../imports/components/import-toast";

const typeOptions = [
  { label: "历年真题 · 选择题", value: "past_exam_choice" },
  { label: "模拟卷 · 选择题", value: "mock_choice" },
];

const CORE_SUBJECT_CODES = new Set([
  "data_structure",
  "computer_organization",
  "operating_system",
  "computer_network",
]);
const CORE_SUBJECT_CODE_QUERY = Array.from(CORE_SUBJECT_CODES).join(",");

const SUBJECT_ORDER = [
  "data_structure",
  "computer_organization",
  "operating_system",
  "computer_network",
];

const SUBJECT_JUMP_STYLE: Record<string, { dot: string; chip: string }> = {
  data_structure: { dot: "bg-[#4a6f8a]", chip: "border-[#bfd0db] bg-[#edf4f7] text-[#2d5068] hover:border-[#7f9fb2] hover:bg-[#e4eef3]" },
  computer_organization: { dot: "bg-[#b78654]", chip: "border-[#decdb8] bg-[#faf5ee] text-[#785a3d] hover:border-[#c3a27d] hover:bg-[#f5ecdf]" },
  operating_system: { dot: "bg-[#5b8c5b]", chip: "border-[#c6d9c6] bg-[#f0f6ef] text-[#456d47] hover:border-[#8fb18f] hover:bg-[#e7f1e6]" },
  computer_network: { dot: "bg-[#70808d]", chip: "border-[#cfd7dc] bg-[#f3f6f7] text-[#50606d] hover:border-[#9eafb9] hover:bg-[#eaf0f2]" },
};

type ExamToastState = {
  message: string;
  title?: string;
  tone: ImportToastTone;
};

type DraftItem = {
  question_id: number;
  score: string;
  subject_name: string;
  subject_code: string;
  content: Record<string, unknown>;
  year?: number | null;
  source?: string | null;
  question_version_id?: number;
  version_is_current?: boolean;
};

function stemFromContent(content: unknown): string {
  if (!content || typeof content !== "object" || Array.isArray(content)) return "";
  const record = content as Record<string, unknown>;
  for (const key of ["stem", "text", "question", "content"]) {
    if (typeof record[key] === "string" && String(record[key]).trim()) return String(record[key]).trim();
  }
  if (Array.isArray(record.segments)) {
    return record.segments
      .map((segment) => {
        if (!segment || typeof segment !== "object" || Array.isArray(segment)) return "";
        const item = segment as Record<string, unknown>;
        return typeof item.text === "string" ? item.text : "";
      })
      .filter(Boolean)
      .join(" ")
      .trim();
  }
  return "";
}

function toDraftItem(item: AdminExamPaperQuestionItem): DraftItem {
  return {
    question_id: item.question_id,
    score: String(item.score),
    subject_name: item.subject_name,
    subject_code: item.subject_code,
    content: item.content,
    year: item.year,
    source: item.source,
    question_version_id: item.question_version_id,
    version_is_current: item.version_is_current,
  };
}

function buildExamItemsPayload(items: DraftItem[]) {
  if (items.length < 1) {
    throw new Error("试卷至少需要 1 道选择题后才能保存组卷。");
  }
  if (items.length > 100) {
    throw new Error(`当前有 ${items.length} 道题，单份试卷最多保存 100 道。`);
  }

  const seen = new Set<number>();
  return items.map((item, index) => {
    const questionId = Number(item.question_id);
    if (!Number.isInteger(questionId) || questionId <= 0) {
      throw new Error(`第 ${index + 1} 题的 question_id 无效，请移除后重新添加。`);
    }
    if (seen.has(questionId)) {
      throw new Error(`第 ${index + 1} 题与前面的题目重复（Q#${questionId}），请删除重复项。`);
    }
    seen.add(questionId);

    const scoreText = String(item.score ?? "").trim();
    const score = Number(scoreText);
    if (!scoreText || !Number.isFinite(score) || score <= 0 || score > 100) {
      throw new Error(`第 ${index + 1} 题（Q#${questionId}）分值必须大于 0 且不超过 100。`);
    }
    return { question_id: questionId, score };
  });
}

function statusMeta(status: AdminExamPaperDetail["status"]) {
  if (status === "published") return { label: "已发布", tone: "success" as const, summary: "题序与题目版本已冻结" };
  if (status === "archived") return { label: "已归档", tone: "neutral" as const, summary: "不再出现在前台试卷列表" };
  return { label: "草稿", tone: "warning" as const, summary: "可继续编辑题目与基础信息" };
}

export default function ExamPaperDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const paperRef = params.id;
  const isLegacyNumericRef = /^\d+$/.test(paperRef);
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const [title, setTitle] = useState("");
  const [paperType, setPaperType] = useState<AdminExamPaperType>("past_exam_choice");
  const [year, setYear] = useState("");
  const [source, setSource] = useState("");
  const [durationMin, setDurationMin] = useState("");
  const [items, setItems] = useState<DraftItem[]>([]);
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [toast, setToast] = useState<ExamToastState | null>(null);
  const [confirmAction, setConfirmAction] = useState<"publish" | "archive" | null>(null);
  const [highlightedQuestionIndex, setHighlightedQuestionIndex] = useState<number | null>(null);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);
  const [jumpDrawerOpen, setJumpDrawerOpen] = useState(false);
  const [jumpNumber, setJumpNumber] = useState("");
  const [showBackToTop, setShowBackToTop] = useState(false);
  const [backToTopLeft, setBackToTopLeft] = useState<number | null>(null);
  const rightRailRef = useRef<HTMLDivElement | null>(null);
  const announcedPaperNoticeRef = useRef("");
  const jumpHighlightTimerRef = useRef<number | null>(null);

  const paperQuery = useQuery({
    queryKey: ["exam-paper", paperRef],
    queryFn: () =>
      apiRequest<AdminExamPaperDetail>(
        isLegacyNumericRef
          ? `/exams/papers/${encodeURIComponent(paperRef)}`
          : `/exams/papers/public/${encodeURIComponent(paperRef)}`,
      ),
    enabled: Boolean(paperRef),
  });
  const paper = paperQuery.data;
  const isDraft = paper?.status === "draft";
  const mutationPaperRef = paper?.public_id || paperRef;

  useEffect(() => {
    if (!paper || !isLegacyNumericRef) return;
    router.replace(`/exams/${paper.public_id}`);
  }, [isLegacyNumericRef, paper, router]);

  useEffect(() => {
    if (!paper) return;
    setTitle(paper.title);
    setPaperType(paper.paper_type);
    setYear(paper.year ? String(paper.year) : "");
    setSource(paper.source || "");
    setDurationMin(paper.duration_sec ? String(Math.round(paper.duration_sec / 60)) : "");
    setItems(paper.items.map(toDraftItem));
  }, [paper]);

  useEffect(() => {
    if (!paper) return;
    const staleCount = paper.items.filter((item) => item.version_is_current === false).length;
    const signature = `${paper.public_id}:${paper.validation_errors.join("|")}:${staleCount}`;
    if (announcedPaperNoticeRef.current === signature) return;
    announcedPaperNoticeRef.current = signature;

    if (paper.validation_errors.length > 0) {
      setToast({
        tone: "warning",
        title: `发布前还有 ${paper.validation_errors.length} 项需要处理`,
        message: paper.validation_errors.map((error) => `• ${error}`).join("\n"),
      });
      return;
    }
    if (staleCount > 0) {
      setToast({
        tone: "info",
        title: "题库中已有题目的新版本",
        message: `${staleCount} 道题仍引用已固定版本；历史试卷不受影响，草稿如需采用新版本请重新添加题目。`,
      });
    }
  }, [paper]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedKeyword(keyword.trim());
    }, 320);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  useEffect(() => () => {
    if (jumpHighlightTimerRef.current) window.clearTimeout(jumpHighlightTimerRef.current);
  }, []);

  useEffect(() => {
    if (!items.length) {
      setActiveQuestionIndex(0);
      return;
    }
    setActiveQuestionIndex((current) => Math.min(current, items.length - 1));
    const nodes = Array.from(document.querySelectorAll<HTMLElement>("[data-exam-question-index]"));
    if (!nodes.length || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => Math.abs(left.boundingClientRect.top - 180) - Math.abs(right.boundingClientRect.top - 180));
        const index = visible[0]?.target instanceof HTMLElement
          ? Number(visible[0].target.dataset.examQuestionIndex)
          : Number.NaN;
        if (Number.isInteger(index)) setActiveQuestionIndex(index);
      },
      { root: null, rootMargin: "-16% 0px -68% 0px", threshold: [0, 0.15, 0.5] },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [items.length]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT" || target?.isContentEditable;
      if (event.key === "Escape" && jumpDrawerOpen) {
        event.preventDefault();
        setJumpDrawerOpen(false);
        return;
      }
      if (!typing && (event.key === "j" || event.key === "J") && items.length) {
        event.preventDefault();
        setJumpDrawerOpen(true);
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [items.length, jumpDrawerOpen]);

  useEffect(() => {
    if (!jumpDrawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [jumpDrawerOpen]);

  useEffect(() => {
    // AdminShell scrolls its <main> element, not window. Listening to window.scrollY
    // keeps the value at 0 and prevents the back-to-top action from ever appearing.
    const scrollContainer = document.querySelector<HTMLElement>("main");
    if (!scrollContainer) return;

    let frame = 0;
    const updateBackToTopVisibility = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        setShowBackToTop(scrollContainer.scrollTop > 320);
        const rail = rightRailRef.current;
        if (rail) {
          const rect = rail.getBoundingClientRect();
          setBackToTopLeft(rect.left + rect.width / 2);
        } else {
          setBackToTopLeft(null);
        }
      });
    };

    updateBackToTopVisibility();
    scrollContainer.addEventListener("scroll", updateBackToTopVisibility, { passive: true });
    window.addEventListener("resize", updateBackToTopVisibility, { passive: true });
    return () => {
      scrollContainer.removeEventListener("scroll", updateBackToTopVisibility);
      window.removeEventListener("resize", updateBackToTopVisibility);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  const candidateQuery = useQuery({
    queryKey: ["exam-question-candidates", debouncedKeyword],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions?${toQuery({
          page: 1,
          page_size: 100,
          question_type: "single_choice",
          review_status: "approved",
          is_active: true,
          subject_codes: CORE_SUBJECT_CODE_QUERY,
          keyword: debouncedKeyword || undefined,
        })}`,
      ),
    enabled: Boolean(isDraft && canWrite),
  });

  const selectedIds = useMemo(() => new Set(items.map((item) => item.question_id)), [items]);
  // 408 科目范围已经由后端 subject_codes 严格限定。这里不再依赖列表返回的
  // subject_code 二次过滤，否则历史响应中 subject_code 为空时会把已命中的题全部误删。
  const candidatePageItems = candidateQuery.data?.items || [];
  const candidates = useMemo(
    () => candidatePageItems.filter((question) => !selectedIds.has(question.id)),
    [candidatePageItems, selectedIds],
  );
  const matchedSelectedCount = useMemo(
    () => candidatePageItems.filter((question) => selectedIds.has(question.id)).length,
    [candidatePageItems, selectedIds],
  );
  const candidateTotal = candidateQuery.data?.total ?? 0;
  const normalizedKeyword = keyword.trim();
  const searchIsSettling = normalizedKeyword !== debouncedKeyword;
  const searchIsBusy = searchIsSettling || candidateQuery.isFetching;
  const searchSummary = normalizedKeyword
    ? `匹配 ${candidateTotal} 道 · 已在卷中 ${matchedSelectedCount} 道 · 可添加 ${candidates.length} 道`
    : `当前可添加 ${candidates.length} 道`;
  const questionGroups = useMemo(() => {
    const grouped = new Map<string, { subject_code: string; subject_name: string; entries: Array<{ index: number; item: DraftItem }> }>();
    items.forEach((item, index) => {
      const key = item.subject_code || item.subject_name || "unknown";
      const existing = grouped.get(key);
      if (existing) {
        existing.entries.push({ index, item });
      } else {
        grouped.set(key, { subject_code: item.subject_code || "unknown", subject_name: item.subject_name || "未归类", entries: [{ index, item }] });
      }
    });
    return Array.from(grouped.values()).sort((left, right) => {
      const leftOrder = SUBJECT_ORDER.indexOf(left.subject_code);
      const rightOrder = SUBJECT_ORDER.indexOf(right.subject_code);
      const leftRank = leftOrder === -1 ? Number.MAX_SAFE_INTEGER : leftOrder;
      const rightRank = rightOrder === -1 ? Number.MAX_SAFE_INTEGER : rightOrder;
      return leftRank - rightRank || left.subject_name.localeCompare(right.subject_name, "zh-CN");
    });
  }, [items]);
  const activeItem = items[activeQuestionIndex];
  const activeSubjectName = activeItem?.subject_name || "未定位";
  function openJumpDrawer() {
    setJumpNumber("");
    setJumpDrawerOpen(true);
  }

  function clearCandidateSearch() {
    setKeyword("");
    setDebouncedKeyword("");
  }

  const metaMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: title.trim(),
          paper_type: paperType,
          year: year ? Number(year) : null,
          source: source.trim() || null,
          duration_sec: durationMin ? Number(durationMin) * 60 : null,
        }),
      }),
    onSuccess: async () => {
      setToast({ tone: "success", title: "试卷信息已保存", message: "基础信息已同步。" });
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
    onError: (error) => {
      setToast({ tone: "error", title: "保存信息失败", message: error instanceof Error ? error.message : "请稍后重试。" });
    },
  });

  const itemsMutation = useMutation({
    mutationFn: () => {
      const payloadItems = buildExamItemsPayload(items);
      return apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}/items`, {
        method: "PUT",
        body: JSON.stringify({ items: payloadItems }),
        exposeErrorDetail: true,
      });
    },
    onSuccess: async () => {
      setToast({ tone: "success", title: "组卷已保存", message: `已固定 ${items.length} 道题的题序、分值与当前题目版本。` });
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
    onError: (error) => {
      setToast({ tone: "error", title: "保存组卷失败", message: error instanceof Error ? error.message : "请检查题目与分值后重试。" });
    },
  });

  const stateMutation = useMutation({
    mutationFn: (action: "publish" | "archive") =>
      apiRequest<AdminExamPaperDetail>(`/exams/papers/public/${encodeURIComponent(mutationPaperRef)}/${action}`, { method: "POST" }),
    onSuccess: async (_, action) => {
      setConfirmAction(null);
      setToast({
        tone: "success",
        title: action === "publish" ? "试卷已发布" : "试卷已归档",
        message: action === "publish" ? "题目版本与题序已冻结。" : "该试卷已从前台可用列表移除。",
      });
      await queryClient.invalidateQueries({ queryKey: ["exam-paper", paperRef] });
      await queryClient.invalidateQueries({ queryKey: ["exam-papers"] });
    },
    onError: (error, action) => {
      setConfirmAction(null);
      setToast({
        tone: "error",
        title: action === "publish" ? "发布失败" : "归档失败",
        message: error instanceof Error ? error.message : "请刷新后重试。",
      });
    },
  });

  const quickPastExamMutation = useMutation({
    mutationFn: async () => {
      const normalizedYear = year.replace(/\D/g, "");
      if (normalizedYear.length !== 4) {
        throw new Error("请先在右侧试卷信息中填写 4 位年份，例如 2014。");
      }
      const targetYear = Number(normalizedYear);
      if (!Number.isInteger(targetYear) || targetYear < 2000 || targetYear > 2100) {
        throw new Error("试卷年份需在 2000–2100 之间。");
      }
      return apiRequest<AdminExamPastExamCandidatesResponse>(
        `/exams/past-exam-candidates${toQuery({ year: targetYear })}`,
      );
    },
    onSuccess: (result) => {
      const existing = new Set(items.map((item) => item.question_id));
      const addable = result.items.filter((item) => !existing.has(item.question_id));
      if (addable.length) {
        setItems((current) => [
          ...current,
          ...addable.map((item) => ({
            question_id: item.question_id,
            score: "2",
            subject_name: item.subject_name,
            subject_code: item.subject_code,
            content: item.content,
            year: item.year,
            source: item.source,
            version_is_current: true,
          })),
        ]);
      }
      const skipped = result.total - addable.length;
      setToast({
        tone: result.total ? "success" : "info",
        title: result.total ? "真题匹配完成" : "未找到可用真题",
        message: result.total
          ? `已匹配 ${result.total} 道 ${result.year} 真题，新增 ${addable.length} 道${skipped ? `，跳过已添加 ${skipped} 道` : ""}。`
          : `未找到与试卷年份 ${result.year} 匹配的可用单选题；已检查【${result.year}统考真题】与【${result.year} 统考真题】题干前缀。`,
      });
    },
    onError: (error) => {
      setToast({ tone: "error", title: "真题匹配失败", message: error instanceof Error ? error.message : "请稍后重试。" });
    },
  });

  function addCandidate(question: AdminQuestion) {
    setItems((current) => [
      ...current,
      {
        question_id: question.id,
        score: "2",
        subject_name: question.subject_name || "未归类",
        subject_code: question.subject_code || "",
        content: question.content,
        year: question.year,
        source: question.source,
        version_is_current: true,
      },
    ]);
  }

  function moveItem(index: number, delta: -1 | 1) {
    setItems((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function jumpToQuestion(index: number, closeDrawer = false) {
    document.getElementById(`exam-question-${index + 1}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setActiveQuestionIndex(index);
    setHighlightedQuestionIndex(index);
    if (closeDrawer) setJumpDrawerOpen(false);
    if (jumpHighlightTimerRef.current) window.clearTimeout(jumpHighlightTimerRef.current);
    jumpHighlightTimerRef.current = window.setTimeout(() => setHighlightedQuestionIndex(null), 1400);
  }

  function submitJumpNumber() {
    const target = Number(jumpNumber);
    if (!Number.isInteger(target) || target < 1 || target > items.length) return;
    jumpToQuestion(target - 1, true);
  }

  function scrollBackToTop() {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const scrollContainer = document.querySelector<HTMLElement>("main");
    if (scrollContainer) {
      scrollContainer.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
      return;
    }
    window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
  }

  if (paperQuery.isLoading) {
    return (
      <ManagementPage className="space-y-6">
        <ManagementPageHeader icon={<ClipboardCheck className="h-5 w-5" />} title="试卷工作台" description="正在载入固定题序、版本状态与发布校验。" meta={<span>读取试卷数据</span>} />
        <ManagementPanel variant="focus" title="正在加载" description="题目较多时可能需要几秒钟。" contentClassName="p-0">
          <ManagementSkeletonRows rows={6} />
        </ManagementPanel>
      </ManagementPage>
    );
  }
  if (!paper) {
    return (
      <ManagementPage className="space-y-6">
        <ManagementPageHeader icon={<ClipboardCheck className="h-5 w-5" />} title="试卷不可用" description="试卷不存在，或当前账号没有读取权限。" actions={<Button variant="secondary" onClick={() => router.push("/exams")}><ArrowLeft className="h-4 w-4" />返回列表</Button>} />
        <ManagementNotice tone="danger" title="无法打开试卷">请返回列表确认试卷是否仍存在，或检查当前账号权限。</ManagementNotice>
      </ManagementPage>
    );
  }

  const status = statusMeta(paper.status);
  const draftScore = items.reduce((total, item) => total + (Number(item.score) || 0), 0);
  const hasStaleVersion = items.some((item) => item.version_is_current === false);
  const metaDirty = Boolean(isDraft && (
    title.trim() !== paper.title
    || paperType !== paper.paper_type
    || (year ? Number(year) : null) !== (paper.year ?? null)
    || (source.trim() || null) !== (paper.source || null)
    || (durationMin ? Number(durationMin) * 60 : null) !== (paper.duration_sec ?? null)
  ));
  const itemsDirty = Boolean(isDraft && (
    items.length !== paper.items.length
    || items.some((item, index) => {
      const saved = paper.items[index];
      return !saved || saved.question_id !== item.question_id || Number(saved.score) !== Number(item.score);
    })
  ));

  return (
    <ManagementPage className="space-y-6">
      <ManagementPageHeader
        icon={<ClipboardCheck className="h-5 w-5" />}
        title={paper.title}
        description={isDraft && (metaDirty || itemsDirty) ? `${status.summary} · 当前有未保存修改` : status.summary}
        meta={
          <>
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span>版本 v{paper.version}</span>
            {paper.source ? <span>{paper.source}</span> : null}
          </>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => router.push("/exams")}>
              <ArrowLeft className="h-4 w-4" />
              返回列表
            </Button>
            {paper.status === "draft" && canWrite ? (
              <Button
                onClick={() => setConfirmAction("publish")}
                disabled={paper.validation_errors.length > 0 || stateMutation.isPending}
                title={paper.validation_errors.length ? paper.validation_errors.join("；") : undefined}
              >
                <CheckCircle2 className="h-4 w-4" />
                发布
              </Button>
            ) : null}
            {paper.status !== "archived" && canWrite ? (
              <Button variant="secondary" onClick={() => setConfirmAction("archive")} disabled={stateMutation.isPending}>
                归档
              </Button>
            ) : null}
          </>
        }
      />

      <ImportToast
        message={toast?.message ?? null}
        title={toast?.title}
        tone={toast?.tone ?? "info"}
        onDismiss={() => setToast(null)}
      />

      <MetricStrip className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<ListOrdered className="h-4 w-4" />} label="当前题目" value={items.length} hint={isDraft ? "保存组卷后写入固定题序" : "已按发布版本冻结"} />
        <MetricCard icon={<Sigma className="h-4 w-4" />} label="选择题总分" value={`${draftScore} 分`} hint={isDraft ? `已保存 ${paper.total_choice_score} 分` : "发布时固定"} tone="accent" />
        <MetricCard icon={<History className="h-4 w-4" />} label="历史作答" value={paper.attempt_count} hint="已产生的考试记录" />
        <MetricCard icon={<Timer className="h-4 w-4" />} label="建议时长" value={paper.duration_sec ? `${Math.round(paper.duration_sec / 60)} 分` : "不限时"} hint={hasStaleVersion ? "题库存在新版本，已固定版本不受影响" : "题目版本状态正常"} tone={hasStaleVersion ? "warning" : "default"} />
      </MetricStrip>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(340px,0.72fr)] xl:items-start">
        <ManagementPanel
          variant="focus"
          title="固定题序"
          description="草稿阶段可调整题序与分值。保存组卷时会固定当前 QuestionVersion，发布后不再直接替换。"
          actions={(
            <>
              {isDraft && canWrite ? (
                <StatusBadge tone={itemsDirty ? "warning" : "success"}>{itemsDirty ? "题序未保存" : "题序已同步"}</StatusBadge>
              ) : (
                <StatusBadge tone="neutral">只读题序</StatusBadge>
              )}
              {items.length ? (
                <Button
                  variant="secondary"
                  className="min-w-[172px] justify-between gap-3 transition-transform active:scale-[0.98] motion-reduce:transform-none"
                  onClick={openJumpDrawer}
                  title="打开题号导航（快捷键 J）"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <ListOrdered className="h-4 w-4 shrink-0" />
                    <span className="truncate">题号 {activeQuestionIndex + 1}/{items.length}</span>
                  </span>
                  <span className="max-w-[86px] truncate text-[11px] font-medium text-[var(--color-text-secondary)]">{activeSubjectName}</span>
                </Button>
              ) : null}
              {isDraft && canWrite && paperType === "past_exam_choice" ? (
                <Button
                  variant="secondary"
                  className="transition-transform active:scale-[0.98] motion-reduce:transform-none"
                  onClick={() => quickPastExamMutation.mutate()}
                  disabled={quickPastExamMutation.isPending || year.replace(/\D/g, "").length !== 4}
                  title={year.replace(/\D/g, "").length === 4 ? `按试卷年份 ${year} 快速匹配真题` : "请先填写 4 位试卷年份"}
                >
                  <Plus className="h-4 w-4" />
                  {quickPastExamMutation.isPending ? "匹配中" : "快速添加题目"}
                </Button>
              ) : null}
              {isDraft && canWrite ? (
                <Button className="transition-transform active:scale-[0.98] motion-reduce:transform-none" onClick={() => itemsMutation.mutate()} disabled={!items.length || !itemsDirty || itemsMutation.isPending || items.some((item) => Number(item.score) <= 0)}>
                  <Save className="h-4 w-4" />
                  保存组卷
                </Button>
              ) : null}
            </>
          )}
          contentClassName="p-0"
        >
          <div className="divide-y divide-[var(--color-border-light)]">
            {items.map((item, index) => (
              <div
                key={`${item.question_id}-${index}`}
                id={`exam-question-${index + 1}`}
                data-exam-question-index={index}
                className={`group relative flex scroll-mt-28 gap-3 px-4 py-4 transition-[background-color,box-shadow] duration-300 before:absolute before:bottom-[-1px] before:left-[35px] before:top-12 before:w-px before:bg-[var(--mgmt-line)] last:before:hidden sm:px-5 sm:before:left-[39px] ${highlightedQuestionIndex === index ? "bg-[rgba(74,111,138,0.085)] shadow-[inset_3px_0_0_var(--color-primary)]" : "hover:bg-[rgba(74,111,138,0.032)]"}`}
              >
                <div className="relative z-[1] grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-[rgba(74,111,138,0.16)] bg-[var(--mgmt-steel)] text-xs font-bold tabular-nums text-[var(--color-primary-dark)] shadow-[0_0_0_4px_var(--mgmt-paper)] transition-[transform,background-color] duration-200 group-hover:-translate-y-px group-hover:bg-white motion-reduce:transform-none">
                  {index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--color-text-tertiary)]">
                    <span className="font-semibold text-[var(--color-text-secondary)]">{item.subject_name}</span>
                    <span>Q#{item.question_id}</span>
                    {item.year ? <span>{item.year}</span> : null}
                    {item.version_is_current === false ? <StatusBadge tone="warning">题库已有新版本</StatusBadge> : null}
                  </div>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-[var(--ink)]">{stemFromContent(item.content) || "题干包含结构化内容或图片"}</p>
                  {item.source ? <p className="mt-1 truncate text-[11px] text-[var(--color-text-tertiary)]">来源：{item.source}</p> : null}
                </div>
                <div className="flex shrink-0 items-start gap-2.5">
                  {isDraft && canWrite ? <GripVertical className="mt-8 hidden h-4 w-4 text-[var(--color-text-hint)] opacity-50 transition-opacity group-hover:opacity-100 lg:block" aria-hidden="true" /> : null}
                  <label className="w-20">
                    <FieldLabel>分值</FieldLabel>
                    <Input
                      className="text-center tabular-nums"
                      value={item.score}
                      disabled={!isDraft || !canWrite}
                      onChange={(event) => setItems((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, score: event.target.value.replace(/[^\d.]/g, "") } : entry))}
                    />
                  </label>
                  {isDraft && canWrite ? (
                    <div className="flex flex-col gap-2 pt-[22px]">
                      <Button
                        className="h-11 w-11 rounded-xl border border-[var(--color-border-light)] bg-white/86 px-0 shadow-[0_2px_8px_rgba(31,49,61,0.035)] transition-[background-color,border-color,transform] hover:-translate-y-px hover:border-[rgba(74,111,138,0.34)] active:translate-y-0 motion-reduce:transform-none"
                        size="sm"
                        variant="ghost"
                        onClick={() => moveItem(index, -1)}
                        disabled={index === 0}
                        aria-label="上移题目"
                        title="上移题目"
                      >
                        <ArrowUp className="h-[18px] w-[18px]" />
                      </Button>
                      <Button
                        className="h-11 w-11 rounded-xl border border-[var(--color-border-light)] bg-white/86 px-0 shadow-[0_2px_8px_rgba(31,49,61,0.035)] transition-[background-color,border-color,transform] hover:translate-y-px hover:border-[rgba(74,111,138,0.34)] active:translate-y-0 motion-reduce:transform-none"
                        size="sm"
                        variant="ghost"
                        onClick={() => moveItem(index, 1)}
                        disabled={index === items.length - 1}
                        aria-label="下移题目"
                        title="下移题目"
                      >
                        <ArrowDown className="h-[18px] w-[18px]" />
                      </Button>
                      <Button
                        className="h-11 w-11 rounded-xl border border-red-100 bg-white/86 px-0 text-red-600 shadow-[0_2px_8px_rgba(31,49,61,0.035)] transition-[background-color,border-color,transform,color] hover:scale-[1.03] hover:border-red-200 hover:bg-red-50 hover:text-red-700 active:scale-100 motion-reduce:transform-none"
                        size="sm"
                        variant="ghost"
                        onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                        aria-label="移除题目"
                        title="移除题目"
                      >
                        <Trash2 className="h-[18px] w-[18px]" />
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
          {!items.length ? <EmptyState>还没有题目。草稿阶段可从下方题库中添加单选题。</EmptyState> : null}
        </ManagementPanel>

        <div ref={rightRailRef} className="space-y-5 xl:sticky xl:top-5 xl:self-start">
          <ManagementPanel
            variant="quiet"
            title="试卷信息"
            description={isDraft ? "基础信息可在草稿阶段修改。" : "当前试卷已锁定为只读。"}
            actions={<StatusBadge tone={metaDirty ? "warning" : isDraft ? "success" : "neutral"}>{metaDirty ? "信息未保存" : isDraft ? "信息已同步" : "只读"}</StatusBadge>}
          >
          <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2">
            <label className="sm:col-span-2">
              <FieldLabel>名称</FieldLabel>
              <Input className="h-10" value={title} disabled={!isDraft || !canWrite} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              <FieldLabel>类型</FieldLabel>
              <CustomSelect className="h-10" value={paperType} disabled={!isDraft || !canWrite} options={typeOptions} onChange={(value) => setPaperType(value as AdminExamPaperType)} clearable={false} />
            </label>
            <label>
              <FieldLabel>年份</FieldLabel>
              <Input className="h-10 tabular-nums" value={year} disabled={!isDraft || !canWrite} onChange={(event) => setYear(event.target.value.replace(/\D/g, "").slice(0, 4))} />
            </label>
            <label>
              <FieldLabel>建议时长（分钟）</FieldLabel>
              <Input className="h-10 tabular-nums" value={durationMin} disabled={!isDraft || !canWrite} onChange={(event) => setDurationMin(event.target.value.replace(/\D/g, ""))} />
            </label>
            <label>
              <FieldLabel>来源</FieldLabel>
              <Input className="h-10" value={source} disabled={!isDraft || !canWrite} onChange={(event) => setSource(event.target.value)} placeholder="全国硕士研究生招生考试" />
            </label>
            {isDraft && canWrite ? (
              <div className="flex justify-end border-t border-[var(--color-border-light)] pt-4 sm:col-span-2">
                <Button className="w-full transition-transform active:scale-[0.99] motion-reduce:transform-none sm:w-auto" onClick={() => metaMutation.mutate()} disabled={!title.trim() || !metaDirty || metaMutation.isPending}>
                  <Save className="h-4 w-4" />
                  保存信息
                </Button>
              </div>
            ) : null}
            </div>
          </ManagementPanel>


        </div>
      </div>

      {jumpDrawerOpen
        ? createPortal(
            <div className="fixed inset-0 z-[2147483647] [--mgmt-paper:#fffefa] [--mgmt-steel:#edf3f6] [--mgmt-steel-strong:#e4edf2] [--mgmt-line:#dde5ea] [--mgmt-muted:#71818d]" role="dialog" aria-modal="true" aria-label="题号导航">
          <button
            type="button"
            className="absolute inset-0 bg-[rgba(22,34,43,0.30)] backdrop-blur-[2px]"
            onClick={() => setJumpDrawerOpen(false)}
            aria-label="关闭题号导航"
          />
          <aside className="absolute inset-y-0 right-0 flex h-[100dvh] w-full max-w-[430px] flex-col overflow-hidden border-l border-[var(--color-border-light)] bg-[#fffefa] shadow-[-24px_0_64px_rgba(31,49,61,0.18)] sm:w-[410px]">
            <header className="shrink-0 border-b border-[var(--color-border-light)] bg-[#fffefa] px-5 pb-4 pt-[max(1.25rem,env(safe-area-inset-top))]">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <div className="grid h-9 w-9 place-items-center rounded-xl border border-[rgba(74,111,138,0.14)] bg-[var(--mgmt-steel)] text-[var(--color-primary-dark)]">
                      <ListOrdered className="h-4 w-4" />
                    </div>
                    <div>
                      <h2 className="text-base font-bold text-[var(--ink)]">题号导航</h2>
                      <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">当前第 {activeQuestionIndex + 1} / {items.length} 题 · {activeSubjectName}</p>
                    </div>
                  </div>
                </div>
                <Button variant="ghost" className="h-9 w-9 px-0" onClick={() => setJumpDrawerOpen(false)} aria-label="关闭题号导航" title="关闭（Esc）">
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="mt-4 flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Input
                    className="h-10 pr-16 tabular-nums"
                    inputMode="numeric"
                    value={jumpNumber}
                    onChange={(event) => setJumpNumber(event.target.value.replace(/\D/g, "").slice(0, 3))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") submitJumpNumber();
                    }}
                    placeholder={`输入 1-${items.length} 直接跳转`}
                    autoFocus
                  />
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-medium text-[var(--color-text-tertiary)]">Enter</span>
                </div>
                <Button
                  className="h-10 px-4"
                  onClick={submitJumpNumber}
                  disabled={!jumpNumber || Number(jumpNumber) < 1 || Number(jumpNumber) > items.length}
                >
                  跳转
                </Button>
              </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5 [scrollbar-gutter:stable]" style={{ WebkitOverflowScrolling: "touch", scrollbarWidth: "thin" }}>
              <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-[var(--color-border-light)] bg-white/70 px-3.5 py-2.5">
                <div>
                  <p className="text-xs font-semibold text-[var(--ink)]">按学科浏览题号</p>
                  <p className="mt-0.5 text-[11px] text-[var(--color-text-tertiary)]">四科纵向分组，点击题号后自动定位</p>
                </div>
                <span className="shrink-0 rounded-full bg-[var(--mgmt-steel)] px-2.5 py-1 text-[11px] font-semibold tabular-nums text-[var(--color-primary-dark)]">
                  {questionGroups.length} 科 · {items.length} 题
                </span>
              </div>
              <nav className="space-y-5" aria-label="试卷题号跳转">
                {questionGroups.map((group) => {
                  const visual = SUBJECT_JUMP_STYLE[group.subject_code] ?? { dot: "bg-slate-400", chip: "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100" };
                  return (
                    <section
                      key={`drawer-${group.subject_code}-${group.subject_name}`}
                      className="rounded-2xl border border-[var(--color-border-light)] bg-white/65 p-3.5 shadow-[0_1px_0_rgba(255,255,255,0.82)]"
                    >
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span className={`h-2.5 w-2.5 rounded-full ${visual.dot}`} aria-hidden="true" />
                          <span className="text-sm font-bold text-[var(--ink)]">{group.subject_name}</span>
                        </div>
                        <span className="text-[11px] tabular-nums text-[var(--color-text-tertiary)]">{group.entries.length} 题</span>
                      </div>
                      <div className="grid grid-cols-6 gap-2">
                        {group.entries.map(({ index, item }) => {
                          const active = activeQuestionIndex === index;
                          return (
                            <button
                              key={`drawer-${item.question_id}-${index}`}
                              type="button"
                              onClick={() => jumpToQuestion(index, true)}
                              className={`relative grid h-11 place-items-center rounded-xl border text-sm font-bold tabular-nums transition-[background-color,border-color,transform,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(74,111,138,0.28)] active:scale-[0.96] motion-reduce:transform-none ${active ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white shadow-[0_6px_16px_rgba(45,80,104,0.18)]" : visual.chip}`}
                              aria-current={active ? "true" : undefined}
                              aria-label={`跳转到第 ${index + 1} 题，${group.subject_name}`}
                              title={`第 ${index + 1} 题 · Q#${item.question_id}`}
                            >
                              {index + 1}
                              {active ? <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-emerald-400" aria-hidden="true" /> : null}
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </nav>
            </div>

            <footer className="shrink-0 border-t border-[var(--color-border-light)] bg-[#fffefa] px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
              <div className="flex items-center justify-between gap-3 text-[11px] text-[var(--color-text-tertiary)]">
                <span>点击题号后自动定位并关闭</span>
                <span className="font-medium">J 打开 · Esc 关闭</span>
              </div>
            </footer>
          </aside>
            </div>,
            document.body,
          )
        : null}

      {isDraft && canWrite ? (
        <ManagementPanel
          variant="quiet"
          title="从题库添加单选题"
          description="仅展示已审核、已启用且属于 408 核心科目的单选题。搜索支持多个关键词模糊匹配。"
          icon={<Plus className="h-4 w-4" />}
          actions={
            <div className="w-full sm:w-[360px]">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
                <Input
                  className="h-11 pl-9 pr-20"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape" && keyword) clearCandidateSearch();
                  }}
                  placeholder="模糊搜索，如：二叉树 中序"
                  autoComplete="off"
                  aria-label="模糊搜索题库题干"
                />
                <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
                  {searchIsBusy ? <LoaderCircle className="h-4 w-4 animate-spin text-[var(--color-text-tertiary)]" aria-label="搜索中" /> : null}
                  {keyword ? (
                    <button
                      type="button"
                      className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-tertiary)] transition-colors hover:bg-[rgba(74,111,138,0.08)] hover:text-[var(--color-text-primary)]"
                      onClick={clearCandidateSearch}
                      aria-label="清空搜索"
                      title="清空搜索（Esc）"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          }
          contentClassName="p-0"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border-light)] bg-[rgba(74,111,138,0.025)] px-4 py-2.5 text-[11px] text-[var(--color-text-tertiary)] sm:px-5">
            <span className="flex items-center gap-2">
              {searchIsBusy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
              <span>{searchIsBusy ? "输入已接收，正在防抖匹配…" : searchSummary}</span>
            </span>
            <span className="hidden sm:inline">年份可直接搜 2014；多关键词用空格分隔；Esc 清空</span>
          </div>

          {candidateQuery.isError ? (
            <div className="flex flex-col items-center justify-center gap-3 px-5 py-10 text-center">
              <p className="text-sm text-[var(--color-text-secondary)]">题库加载失败，请检查网络后重试。</p>
              <Button variant="secondary" onClick={() => candidateQuery.refetch()}>重新加载</Button>
            </div>
          ) : null}

          {!candidateQuery.isError ? (
            <div className="grid md:grid-cols-2">
              {candidates.map((question) => (
                <div key={question.id} className="group flex items-start gap-3 border-b border-[var(--color-border-light)] px-4 py-4 transition-colors duration-200 hover:bg-[rgba(74,111,138,0.035)] md:odd:border-r md:px-5">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-text-tertiary)]">
                      <span className="font-semibold text-[var(--color-text-secondary)]">{question.subject_name}</span>
                      <span>Q#{question.id}</span>
                      {question.year ? <span>{question.year}</span> : null}
                      {question.source ? <span className="max-w-40 truncate" title={question.source}>{question.source}</span> : null}
                    </div>
                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-[var(--ink)]">{stemFromContent(question.content) || "结构化题干"}</p>
                  </div>
                  <Button
                    className="h-10 shrink-0 gap-1.5 rounded-xl px-3 transition-[transform,box-shadow] duration-200 group-hover:-translate-y-px group-hover:shadow-[0_6px_14px_rgba(31,49,61,0.08)] active:translate-y-0 motion-reduce:transform-none"
                    variant="secondary"
                    onClick={() => addCandidate(question)}
                    aria-label={`添加题目 ${question.id}`}
                    title="添加到当前试卷"
                  >
                    <Plus className="h-4 w-4" />
                    <span>添加</span>
                  </Button>
                </div>
              ))}
            </div>
          ) : null}
          {!candidateQuery.isLoading && !candidateQuery.isError && !searchIsBusy && candidates.length === 0 ? (
            <EmptyState>
              {normalizedKeyword && candidateTotal > 0
                ? `已匹配到 ${candidateTotal} 道“${normalizedKeyword}”相关题目；当前返回的题目都已经加入这份试卷。`
                : normalizedKeyword
                  ? `没有找到与“${normalizedKeyword}”匹配的可用单选题。可减少关键词，或用空格分隔多个关键词。`
                  : "没有更多符合条件的单选题。"}
            </EmptyState>
          ) : null}
          {candidateQuery.isLoading ? <ManagementSkeletonRows rows={4} /> : null}
        </ManagementPanel>
      ) : null}

      {showBackToTop && typeof document !== "undefined"
        ? createPortal(
            <button
              type="button"
              onClick={scrollBackToTop}
              style={backToTopLeft != null ? { left: `${backToTopLeft}px` } : undefined}
              className="fixed bottom-[max(1.5rem,env(safe-area-inset-bottom))] left-1/2 z-[2147483000] flex h-12 -translate-x-1/2 items-center gap-2 rounded-full border border-[rgba(74,111,138,0.20)] bg-[#fffefa] px-3.5 text-sm font-semibold text-[#2d5068] shadow-[0_12px_34px_rgba(31,49,61,0.18)] transition-[transform,box-shadow,background-color] hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_16px_38px_rgba(31,49,61,0.22)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(74,111,138,0.30)] active:translate-y-0 motion-reduce:transform-none sm:px-4"
              aria-label="返回页面顶部"
              title="返回顶部"
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-[#edf3f6]" aria-hidden="true">
                <ArrowUp className="h-4 w-4" />
              </span>
              <span className="hidden sm:inline">返回顶部</span>
            </button>,
            document.body,
          )
        : null}

      <ConfirmDialog
        open={Boolean(confirmAction)}
        title={confirmAction === "publish" ? "确认发布这份选择题卷？" : "确认归档这份试卷？"}
        description={confirmAction === "publish" ? "发布后将冻结题目版本和题序，不能直接修改；如需调整应新建版本。" : "归档后不会再出现在小程序试卷列表，但历史考试结果仍可查看。"}
        confirmText={confirmAction === "publish" ? "确认发布" : "确认归档"}
        danger={confirmAction === "archive"}
        loading={stateMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => confirmAction && stateMutation.mutate(confirmAction)}
      />
    </ManagementPage>
  );
}
