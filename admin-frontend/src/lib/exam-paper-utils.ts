/**
 * Pure helpers for exam paper list page, extracted from exams/page.tsx.
 */

import type { AdminExamPaperListItem } from "@/lib/api/types";

export type ExamStatus = AdminExamPaperListItem["status"];

interface StatusMeta {
  label: string;
  tone: "success" | "neutral" | "warning";
}

export function statusMeta(status: ExamStatus): StatusMeta {
  if (status === "published") return { label: "已发布", tone: "success" };
  if (status === "archived") return { label: "已归档", tone: "neutral" };
  return { label: "草稿", tone: "warning" };
}

export function paperKindLabel(paper: AdminExamPaperListItem): string {
  if (paper.paper_type === "past_exam_choice") return `${paper.year ?? "年份未设置"} 真题`;
  return paper.year ? `${paper.year} 模拟卷` : "模拟卷";
}

interface PaperSummary {
  total: number;
  draft: number;
  published: number;
  attempts: number;
}

export function computePaperSummary(papers: AdminExamPaperListItem[]): PaperSummary {
  return {
    total: papers.length,
    draft: papers.filter((p) => p.status === "draft").length,
    published: papers.filter((p) => p.status === "published").length,
    attempts: papers.reduce((total, p) => total + p.attempt_count, 0),
  };
}

export function filterPapers(
  papers: AdminExamPaperListItem[],
  statusFilter: string,
  keyword: string,
): AdminExamPaperListItem[] {
  const normalizedKeyword = keyword.trim().toLowerCase();
  return papers.filter((paper) => {
    if (statusFilter && paper.status !== statusFilter) return false;
    if (!normalizedKeyword) return true;
    return `${paper.title} ${paper.source ?? ""} ${paper.year ?? ""} ${paper.version}`
      .toLowerCase()
      .includes(normalizedKeyword);
  });
}

interface StatusSegment {
  value: string;
  label: string;
  count: number;
}

export function buildStatusSegments(
  papers: AdminExamPaperListItem[],
  summary: PaperSummary,
): StatusSegment[] {
  return [
    { value: "", label: "全部", count: summary.total },
    { value: "draft", label: "草稿", count: summary.draft },
    { value: "published", label: "已发布", count: summary.published },
    { value: "archived", label: "已归档", count: papers.filter((p) => p.status === "archived").length },
  ];
}

/**
 * Stable desktop list height: clamp between 260 and 720 based on paper count.
 * Each paper row contributes ~78px; the container has a 46px header offset.
 */
export function stableDesktopListHeight(paperCount: number): number {
  if (paperCount <= 0) return 260;
  return Math.max(260, Math.min(720, 46 + paperCount * 78));
}

/**
 * Stable mobile list height: clamp between 240 and 560 based on paper count.
 * Each paper row contributes ~96px on mobile.
 */
export function stableMobileListHeight(paperCount: number): number {
  if (paperCount <= 0) return 240;
  return Math.max(240, Math.min(560, paperCount * 96));
}
