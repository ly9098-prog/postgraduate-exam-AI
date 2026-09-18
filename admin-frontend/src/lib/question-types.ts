/**
 * 题型字典 — 前端本地兜底配置
 *
 * ⚠️ 重要：后端是题型定义的**权威来源**。
 * 本文件仅作为后端 API 不可用时的离线/开发降级。
 * 生产环境下应优先使用 src/lib/api/question-types.ts 中的 useQuestionTypes() hook
 * 从 GET /api/admin/v1/metadata/question-types 获取数据。
 *
 * 别名规范化（中文/英文题型别名）已移至后端 app/features/question_type.py，
 * 前端不再维护独立的别名映射。
 */

import type { SelectOption } from "@/components/ui/custom-select";

// ── 规范题型 code（编译期完整性检查用） ──

export type QuestionTypeCode =
  | "single_choice"
  | "multiple_choice"
  | "true_false"
  | "fill_blank"
  | "multi_blank_choice"
  | "multi_blank_multiple_choice"
  | "subjective";

// ── 规范值数组（用于遍历） ──

export const QUESTION_TYPE_CODES: QuestionTypeCode[] = [
  "single_choice",
  "multiple_choice",
  "true_false",
  "fill_blank",
  "multi_blank_choice",
  "multi_blank_multiple_choice",
  "subjective",
];

// ── 规范 code → 中文 label（Record 保证所有 code 都有对应值） ──

export const QUESTION_TYPE_LABELS: Record<QuestionTypeCode, string> = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  multi_blank_choice: "多空（单选）选择题",
  multi_blank_multiple_choice: "多空（多选）选择题",
  subjective: "问答题",
};

// ── 导出函数 ──

/**
 * 将题型值标准化为标准 code（本地简化版本）。
 *
 * 只处理 6 个标准 code 的精确匹配（大小写不敏感）。
 * 别名规范化已移至后端 app/features/question_type.py。
 * 对于导入数据中可能出现的别名，后端会在 pipeline 中处理。
 *
 * 未知值返回 null（不静默回退）。
 */
export function canonicalizeQuestionType(
  input: string | null | undefined,
): QuestionTypeCode | null {
  if (!input) return null;
  const normalized = input.trim().toLowerCase().replace(/-/g, "_");
  if (normalized in QUESTION_TYPE_LABELS) {
    return normalized as QuestionTypeCode;
  }
  return null;
}

/**
 * 获取题型的中文显示名称。
 *
 * - 规范 code → 返回对应 label
 * - 未知值 → 返回 "历史未知题型(xxx)"
 *
 * 注意：此函数使用本地兜底配置。生产环境应优先使用后端元数据。
 */
export function getQuestionTypeLabel(
  input: string | null | undefined,
): string {
  if (!input) return "未识别";
  if (input in QUESTION_TYPE_LABELS) {
    return QUESTION_TYPE_LABELS[input as QuestionTypeCode];
  }
  return formatUnknownType(input);
}

// ── 题型简写映射（用于 /imports/review 表格视图） ──

export const QUESTION_TYPE_SHORT_LABELS: Record<QuestionTypeCode, string> = {
  single_choice: "单选",
  multiple_choice: "多选",
  true_false: "判断",
  fill_blank: "填空",
  multi_blank_choice: "多空单选",
  multi_blank_multiple_choice: "多空多选",
  subjective: "问答",
};

/**
 * 获取题型的简写名称（表格视图用）。
 *
 * 规范 code → 返回对应简写（如 "单选"、"多选"）。
 * 未知值 → 保持现有兜底展示（不返回空字符串）。
 */
export function getQuestionTypeShortLabel(
  input: string | null | undefined,
): string {
  if (!input) return "未识别";
  if (input in QUESTION_TYPE_SHORT_LABELS) {
    return QUESTION_TYPE_SHORT_LABELS[input as QuestionTypeCode];
  }
  return formatUnknownType(input);
}

/**
 * 格式化未知题型显示文本
 */
export function formatUnknownType(original: string): string {
  return `历史未知题型(${original})`;
}

/**
 * 判断值是否为标准题型 code（本地兜底版本）
 */
export function isValidQuestionType(
  input: string | null | undefined,
): boolean {
  return canonicalizeQuestionType(input) !== null;
}

// ── 下拉选项 ──

/**
 * 标准题型下拉选项（用于选择器/筛选器）
 */
export const QUESTION_TYPE_OPTIONS: SelectOption[] = QUESTION_TYPE_CODES.map(
  (code) => ({
    value: code,
    label: QUESTION_TYPE_LABELS[code],
  }),
);
