import type { ImportQuestionItem } from "@/lib/api/types";
import { canonicalizeQuestionType } from "@/lib/question-types";
import {
  extractMultiBlankSource,
  getSharedOptions,
  haveIdenticalOptionSets,
  normalizeBlankOptionGroups,
  parseBlankAnswer,
  type BlankAnswerMap,
  type BlankOption,
  type BlankOptionGroup,
} from "./components/multi-blank-choice-utils";

export type EditState = {
  subject_id: number | null;
  question_type: string;
  stem: string;
  options: Array<{ key: string; text: string; segments?: Array<Record<string, unknown>> }>;
  answer: string;
  analysis: string;
  multiBlank?: {
    groups: BlankOptionGroup[];
    answerMap: BlankAnswerMap;
    usesSharedOptions: boolean;
    sharedOptions: BlankOption[];
    dedupWarnings?: string[];
    dedupErrors?: string[];
    hasUnappliedDraft?: boolean;
  };
};

export function isMultiBlankChoice(questionType: string): boolean {
  const code = canonicalizeQuestionType(questionType);
  return code === "multi_blank_choice" || code === "multi_blank_multiple_choice";
}

export function textFromImport(item: ImportQuestionItem | null | undefined): string {
  if (!item) return "";
  const content = item.parsed_content;
  const raw = item.raw_data;
  const candidate = content?.stem ?? content?.text ?? content?.question ??
    raw?.stem ?? raw?.text ?? raw?.question;
  return typeof candidate === "string" ? candidate : "";
}

function richOption(key: string, value: Record<string, unknown>, fallback = "") {
  const text = String(value.text ?? value.content ?? value.value ?? value.stem ?? fallback);
  const segments = Array.isArray(value.segments) && value.segments.length > 0
    ? value.segments as Array<Record<string, unknown>>
    : undefined;
  return { key, text, segments };
}

function parseOptionArray(source: unknown[]): EditState["options"] {
  return source.map((entry, index) => {
    const fallbackKey = String.fromCharCode(65 + index);
    if (typeof entry === "string") return { key: fallbackKey, text: entry };
    if (entry && typeof entry === "object") {
      const option = entry as Record<string, unknown>;
      const key = String(option.key ?? option.label ?? option.name ?? fallbackKey);
      return richOption(key, option);
    }
    return { key: fallbackKey, text: "" };
  }).filter((option) => Boolean(option.key));
}

function parseOptionMap(source: Record<string, unknown>): EditState["options"] {
  return Object.entries(source).map(([key, value]) => {
    if (value && typeof value === "object" && "text" in value) {
      return richOption(key, value as Record<string, unknown>, String(value));
    }
    return { key, text: typeof value === "string" ? value : String(value ?? "") };
  }).filter((option) => Boolean(option.key));
}

export function parseOptionsToEditable(
  item: ImportQuestionItem | null | undefined,
): EditState["options"] {
  if (!item) return [];
  const raw = item.raw_data;
  const source = item.parsed_options ?? raw?.options ?? raw?.parsed_options ??
    raw?.option_text ?? raw?.optionText ?? null;
  if (!source || (Array.isArray(source) && source.length === 0)) {
    if (isMultiBlankChoice(item.question_type ?? "")) {
      const groups = normalizeBlankOptionGroups(
        item.parsed_content?.blank_option_groups ??
          (item.raw_data as Record<string, unknown> | undefined)?.blank_option_groups,
      );
      return groups.flatMap((group) => group.options);
    }
    return [];
  }
  if (Array.isArray(source)) return parseOptionArray(source);
  if (typeof source === "object") return parseOptionMap(source as Record<string, unknown>);
  return [];
}

export function editStateFromItem(item: ImportQuestionItem): EditState {
  const state: EditState = {
    subject_id: item.subject_id ?? null,
    question_type: item.question_type || "",
    stem: textFromImport(item),
    options: parseOptionsToEditable(item),
    answer: item.parsed_answer || "",
    analysis: item.parsed_analysis || "",
  };
  if (!isMultiBlankChoice(state.question_type)) return state;

  const extracted = extractMultiBlankSource(item as unknown as Record<string, unknown>);
  if (extracted.groups.length < 2) {
    state.multiBlank = {
      groups: [],
      answerMap: {},
      usesSharedOptions: false,
      sharedOptions: [],
      dedupErrors: extracted.errors.length > 0 ? extracted.errors : undefined,
    };
    return state;
  }

  const groupIds = extracted.groups.map((group) => group.id);
  const shared = haveIdenticalOptionSets(extracted.groups);
  state.multiBlank = {
    groups: extracted.groups,
    answerMap: parseBlankAnswer(extracted.answer, groupIds),
    usesSharedOptions: shared,
    sharedOptions: shared ? getSharedOptions(extracted.groups) : [],
    dedupWarnings: extracted.warnings.length > 0 ? extracted.warnings : undefined,
    dedupErrors: extracted.errors.length > 0 ? extracted.errors : undefined,
  };
  return state;
}
