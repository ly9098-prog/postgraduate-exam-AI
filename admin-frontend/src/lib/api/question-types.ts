/**
 * 题型元数据 — 从后端 GET /api/admin/v1/metadata/question-types 获取
 *
 * 后端是题型定义的权威来源，前端不再独立维护别名映射。
 * 本模块负责：
 * - 通过 React Query 获取后端元数据
 * - 接口不可用时降级到本地兜底配置
 * - 标准 code → label / capabilities 的查找
 * - 未知 code 的展示
 */

import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";

// ── 类型定义 ──

export interface QuestionTypeCapabilities {
  has_options: boolean;
  answer_mode: string;
  allows_multi_blank: boolean;
  allows_multiple_answers: boolean;
}

export interface QuestionTypeMetaItem {
  code: string;
  label: string;
  sort_order: number;
  capabilities: QuestionTypeCapabilities;
}

interface QuestionTypeMetadataResponse {
  items: QuestionTypeMetaItem[];
}

// ── 本地兜底配置（仅用于接口不可用时的降级） ──
// WARNING: 后端是权威来源。此配置只应在开发/离线时使用。
// 当后端枚举与本配置不一致时，应以后端为准。

const FALLBACK_TYPES: QuestionTypeMetaItem[] = [
  { code: "single_choice", label: "单选题", sort_order: 10, capabilities: { has_options: true, answer_mode: "single_letter", allows_multi_blank: false, allows_multiple_answers: false } },
  { code: "multiple_choice", label: "多选题", sort_order: 20, capabilities: { has_options: true, answer_mode: "multiple_letters", allows_multi_blank: false, allows_multiple_answers: true } },
  { code: "true_false", label: "判断题", sort_order: 30, capabilities: { has_options: false, answer_mode: "true_false", allows_multi_blank: false, allows_multiple_answers: false } },
  { code: "fill_blank", label: "填空题", sort_order: 40, capabilities: { has_options: false, answer_mode: "text", allows_multi_blank: false, allows_multiple_answers: false } },
  { code: "multi_blank_choice", label: "多空（单选）选择题", sort_order: 50, capabilities: { has_options: true, answer_mode: "multi_blank", allows_multi_blank: true, allows_multiple_answers: false } },
  { code: "multi_blank_multiple_choice", label: "多空（多选）选择题", sort_order: 55, capabilities: { has_options: true, answer_mode: "multi_blank_multiple", allows_multi_blank: true, allows_multiple_answers: true } },
  { code: "subjective", label: "问答题", sort_order: 60, capabilities: { has_options: false, answer_mode: "free_text", allows_multi_blank: false, allows_multiple_answers: false } },
];

// 兜底标准 code 集合
const FALLBACK_CODES = new Set(FALLBACK_TYPES.map((t) => t.code));

// code → label（兜底）
const FALLBACK_LABEL_MAP: Record<string, string> = Object.fromEntries(
  FALLBACK_TYPES.map((t) => [t.code, t.label]),
);

// ── React Query Hook ──

/**
 * 获取题型元数据，优先从后端 API 获取。
 *
 * - staleTime: 10 分钟（题型列表几乎不变）
 * - gcTime: 30 分钟
 * - 接口错误时静默降级到本地兜底，不抛异常
 */
export function useQuestionTypes() {
  return useQuery<QuestionTypeMetaItem[]>({
    queryKey: ["question-types-metadata"],
    queryFn: async () => {
      const data = await apiRequest<QuestionTypeMetadataResponse>("/metadata/question-types");
      if (!data?.items?.length) {
        if (process.env.NODE_ENV === "development") {
          console.warn("[question-types] 后端返回空列表，使用本地兜底配置");
        }
        return FALLBACK_TYPES;
      }
      return data.items;
    },
    staleTime: 10 * 60 * 1000, // 10 分钟
    gcTime: 30 * 60 * 1000, // 30 分钟
    retry: 1,
    // 接口不可用时使用兜底
    placeholderData: FALLBACK_TYPES,
  });
}

// ── 工具函数（不依赖 React） ──

/**
 * 从列表或兜底中获取题型 label。
 */
export function getTypeLabel(
  code: string | null | undefined,
  types?: QuestionTypeMetaItem[],
): string {
  if (!code) return "未知";
  if (types) {
    const found = types.find((t) => t.code === code);
    if (found) return found.label;
  }
  return FALLBACK_LABEL_MAP[code] ?? `历史未知题型(${code})`;
}

/**
 * 判断 code 是否为标准题型。
 */
export function isCanonicalType(
  code: string | null | undefined,
  types?: QuestionTypeMetaItem[],
): boolean {
  if (!code) return false;
  if (types) return types.some((t) => t.code === code);
  return FALLBACK_CODES.has(code);
}

/**
 * 将元数据列表转为 SelectOption 数组。
 */
export function toSelectOptions(
  types: QuestionTypeMetaItem[],
): Array<{ value: string; label: string }> {
  return types.map((t) => ({ value: t.code, label: t.label }));
}
