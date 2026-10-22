import type { ImportQuestionItem } from "@/lib/api/types";

type BadgeStyle = { color?: string; fontWeight?: number };
type TableBadgeItem = Pick<ImportQuestionItem, "answer_status" | "risk_level">;
type ListBadgeItem = TableBadgeItem & Pick<ImportQuestionItem,
  "parsed_answer" | "risk_reasons" | "source_image_seq" | "source_question_no">;

export function getReviewTableBadges(item: TableBadgeItem) {
  const answerStatusLabel =
    item.answer_status === "missing" ? "缺失" :
    item.answer_status === "ai_filled" ? "AI" :
    item.answer_status === "imported" ? "导入" :
    item.answer_status === "manual_filled" ? "已填" :
    item.answer_status === "manual_verified" ? "已验" :
    item.answer_status === "abnormal" ? "异常" : "—";
  const answerStatusStyle: BadgeStyle =
    item.answer_status === "missing" ? { color: "#b03a3a", fontWeight: 700 } :
    item.answer_status === "ai_filled" ? { color: "#c46a3a", fontWeight: 600 } :
    item.answer_status === "abnormal" ? { color: "#b03a3a", fontWeight: 700 } :
    {};
  const riskLabel = item.risk_level === "high" ? "高" : item.risk_level === "medium" ? "中" : "低";
  const riskStyle: BadgeStyle =
    item.risk_level === "high" ? { color: "#b03a3a", fontWeight: 700 } :
    item.risk_level === "medium" ? { color: "#b87a30", fontWeight: 600 } :
    { color: "#3a7a5a" };
  return { answerStatusLabel, answerStatusStyle, riskLabel, riskStyle };
}

export function getReviewListBadges(item: ListBadgeItem) {
  const riskColor = item.risk_level === "high" ? "#b03a3a" : item.risk_level === "medium" ? "#b87a30" : item.risk_level === "low" ? "#3a7a5a" : "var(--color-border)";
  const hasAnswerMissing = (!item.parsed_answer || item.parsed_answer.trim() === "") && item.risk_level !== "low";
  const reasonCount = item.risk_reasons?.length ?? 0;
  const sourceLabel = item.source_image_seq != null
    ? `图${item.source_image_seq}${item.source_question_no ? ` · 原题${item.source_question_no}` : ""}`
    : (item.source_question_no ? `原题${item.source_question_no}` : null);
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
  return { riskColor, hasAnswerMissing, reasonCount, sourceLabel, answerStatusLabel, answerStatusColor };
}
