import type { ImportQuestionItem } from "@/lib/api/types";
import { isMeaningfulText } from "./review-display-text";

export function getSourceQuestionNo(item: ImportQuestionItem): string {
  if (item.source_question_no) return String(item.source_question_no);
  if (item.source_question_label) {
    const match = String(item.source_question_label).match(/\d+/);
    if (match) return match[0];
  }
  const rawText =
    item.raw_text_preview ||
    (item.raw_data?.raw_text as string | undefined) ||
    (item.raw_data?.raw_question_text as string | undefined) ||
    (item.raw_data?.text as string | undefined) ||
    "";
  const match =
    rawText.match(/^\s*(\d+)\s*[.．、)）]/) ||
    rawText.match(/^\s*第\s*(\d+)\s*题/) ||
    rawText.match(/^\s*[（(]\s*(\d+)\s*[）)]/);
  return match ? match[1] : "";
}

export function getSourceLocator(item: ImportQuestionItem): string {
  if (item.source_locator) return String(item.source_locator);
  const raw = item.raw_data || {};
  const imageSeq = item.source_image_seq ?? (raw.source_image_seq as number | undefined);
  const imageName =
    item.source_image_name ||
    item.source_file ||
    (raw.source_image_name as string | undefined) ||
    (raw.source_file as string | undefined) ||
    (raw.file_name as string | undefined);
  const pageStart =
    item.source_page_start ??
    (raw.page_start as number | undefined) ??
    (raw.source_page as number | undefined) ??
    (raw.page as number | undefined);
  const pageEnd = item.source_page_end ?? (raw.page_end as number | undefined);
  const parts: string[] = [];
  if (imageSeq != null) parts.push(`图${imageSeq}`);
  if (imageName) parts.push(String(imageName));
  if (pageStart != null && pageEnd != null && pageEnd !== pageStart) {
    parts.push(`第${pageStart}-${pageEnd}页`);
  } else if (pageStart != null) {
    parts.push(`第${pageStart}页`);
  }
  if (parts.length > 0) return parts.join(" · ");
  return item.source_type && isMeaningfulText(item.source_type)
    ? String(item.source_type)
    : "";
}
