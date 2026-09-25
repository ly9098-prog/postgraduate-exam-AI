"use client";

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  Check,
  ChevronDown,
  Download,
  FileQuestion,
  Filter,
  Loader2,
  AlertCircle,
  Search,
  BookOpen,
  BarChart3,
  Tag,
  Layers,
  Clock,
  Pencil,
  Trash2,
  Save,
  X,
  RotateCcw,
  SlidersHorizontal,
  Star,
  ArrowLeft,
  ArrowLeftRight,
  Plus,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MathFormula } from "@/components/ui/math-formula";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { StructuredTableEditor } from "@/components/structured-table-editor";
import { MultiBlankQuestionOptions, QuestionOptions } from "@/components/question-options";
import { QuestionImageField } from "@/components/questions/question-image-field";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import { QuestionAnalysisEditor } from "@/components/questions/question-analysis-editor";
import { QuestionKnowledgePointsDisplay, QuestionKnowledgePointsEditor } from "@/components/questions/question-knowledge-points-editor";
import { QuickAddOptions } from "@/components/questions/quick-add-options";
import {
  QuestionVersionPicker,
  type QuestionVersionSelection,
} from "@/components/questions/question-version-picker";
import { useAuthStore } from "@/lib/auth/auth-store";
import {
  addBlankOptionToAllGroups,
  addBlankOptionToGroup,
  extractBlankSlotIds,
  normalizeBlankOptionGroups,
  normalizeQuestionOptions,
  resolveBlankOptionGroupsValue,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
  updateBlankOptionGroupText,
} from "@/lib/question-options";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest, apiRequestBlob, toQuery } from "@/lib/api/client";
import { resolveAssetUrl } from "@/lib/asset-url";
import { CustomSelect } from "@/components/ui/custom-select";
import { QUESTION_TYPE_OPTIONS, getQuestionTypeLabel, canonicalizeQuestionType, formatUnknownType } from "@/lib/question-types";
import { isTableSegment, normalizeStructuredTableSegment } from "@/lib/structured-table";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  AdminQuestionImportSummary,
  PaginatedResponse,
  QuestionEditRequest,
  QuestionOptionsValue,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";

const activeOptions = [
  { label: "全部状态", value: "" },
  { label: "启用", value: "true" },
  { label: "停用", value: "false" },
];

const difficultyOptions = [
  { label: "全部难度", value: "" },
  { label: "简单", value: "1" },
  { label: "较易", value: "2" },
  { label: "中等", value: "3" },
  { label: "较难", value: "4" },
  { label: "困难", value: "5" },
];

const pageSizeOptions = [
  { label: "20 条/页", value: "20" },
  { label: "50 条/页", value: "50" },
  { label: "100 条/页", value: "100" },
];

type QuestionListFilters = {
  subject_id: string;
  is_active: string;
  question_type: string;
  keyword: string;
  year: string;
  difficulty: string;
  import_batch_id: string;
  knowledge_point_id: string;
};

const DEFAULT_QUESTION_FILTERS: QuestionListFilters = {
  subject_id: "",
  is_active: "true",
  question_type: "",
  keyword: "",
  year: "",
  difficulty: "",
  import_batch_id: "",
  knowledge_point_id: "",
};

function positiveInt(value: string | null, fallback: number | null = null): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeQuestionPageSize(value: string | null): number {
  const parsed = positiveInt(value, 20) ?? 20;
  return [20, 50, 100].includes(parsed) ? parsed : 20;
}

function buildQuestionListHref(
  filters: QuestionListFilters,
  page: number,
  pageSize: number,
  selectedQuestionId: number | null,
): string {
  const params = new URLSearchParams();
  if (filters.subject_id) params.set("subject_id", filters.subject_id);
  if (filters.is_active !== DEFAULT_QUESTION_FILTERS.is_active) {
    params.set("is_active", filters.is_active);
  }
  if (filters.question_type) params.set("question_type", filters.question_type);
  if (filters.keyword) params.set("keyword", filters.keyword);
  if (filters.year) params.set("year", filters.year);
  if (filters.difficulty) params.set("difficulty", filters.difficulty);
  if (filters.import_batch_id) params.set("import_batch_id", filters.import_batch_id);
  if (filters.knowledge_point_id) params.set("knowledge_point_id", filters.knowledge_point_id);
  if (page > 1) params.set("page", String(page));
  if (pageSize !== 20) params.set("page_size", String(pageSize));
  if (selectedQuestionId) params.set("selected_id", String(selectedQuestionId));
  const query = params.toString();
  return query ? `/questions?${query}` : "/questions";
}

const KEYWORD_DEBOUNCE_MS = 300;
const IMPORT_BATCH_DEBOUNCE_MS = 450;
const BATCH_DELETE_CHUNK_SIZE = 50;
const VERSION_HISTORY_PAGE_SIZE = 100;

type ConfirmState =
  | { action: "batch-delete" }
  | { action: "delete"; id: number }
  | null;

type UnsavedIntent = "cancel-edit" | "close-drawer" | null;

type BatchDeleteResult = {
  success_ids?: number[];
  successIds?: number[];
  failed_items?: Array<{ id: number; error: string }>;
  failedItems?: Array<{ id: number; error: string }>;
};

function contentRecord(content: unknown): Record<string, unknown> {
  return content && typeof content === "object" && !Array.isArray(content)
    ? (content as Record<string, unknown>)
    : {};
}

function contentSegments(content: unknown): Array<Record<string, unknown>> {
  const record = contentRecord(content);
  if (!Array.isArray(record.segments)) return [];
  return record.segments.filter(
    (segment): segment is Record<string, unknown> =>
      Boolean(segment) && typeof segment === "object" && !Array.isArray(segment),
  );
}

/** Only literal "image" segments are editable here; formula/table/code image
 * segments (math_image/table_image/code_image) are generated content the
 * backend upsert/remove helpers do not touch. */
function segmentType(segment: Record<string, unknown> | null | undefined): string {
  return segment && typeof segment === "object" && !Array.isArray(segment)
    ? String(segment.type ?? "").trim().toLowerCase()
    : "";
}

function isPlainImageSegment(segment: Record<string, unknown>): boolean {
  return segmentType(segment) === "image";
}

function isCodeSegment(segment: Record<string, unknown>): boolean {
  return segmentType(segment) === "code";
}

function imageUrlFromUnknown(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  for (const key of ["url", "src", "image_url", "imageUrl"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "";
}

function comparableAssetUrl(value: unknown): string {
  const raw = imageUrlFromUnknown(value);
  if (!raw) return "";
  const resolved = resolveAssetUrl(raw) || raw;
  return resolved.replace(/\/+$/, "");
}

function contentRenderedImageKeys(content: unknown): Set<string> {
  const keys = new Set<string>();
  contentSegments(content).forEach((segment) => {
    const type = segmentType(segment);
    if (!["image", "math_image", "table_image", "code_image"].includes(type)) return;
    const key = comparableAssetUrl(segment.url);
    if (key) keys.add(key);
  });
  return keys;
}

function fallbackQuestionImageUrls(
  content: unknown,
  imageUrlField: unknown,
): string[] {
  if (!Array.isArray(imageUrlField)) return [];
  const renderedKeys = contentRenderedImageKeys(content);
  const fallbackUrls = new Map<string, string>();
  imageUrlField.forEach((value: unknown) => {
    const raw = imageUrlFromUnknown(value);
    const key = comparableAssetUrl(raw);
    if (!raw || !key || renderedKeys.has(key)) return;
    fallbackUrls.set(key, raw);
  });
  return Array.from(fallbackUrls.values());
}

function codeSegmentText(segment: Record<string, unknown>): string {
  return String(segment.code ?? segment.text ?? "");
}

function comparableText(value: unknown): string {
  return String(value ?? "").replace(/\r\n?/g, "\n").trim();
}

function visibleCodeSegmentText(segment: Record<string, unknown>): string {
  const code = comparableText(codeSegmentText(segment));
  const caption = comparableText(segment.caption);
  return caption && code ? `${caption}\n${code}` : (caption || code);
}

function canonicalStemAfterSegmentUpdate(
  content: Record<string, unknown>,
  nextSegments: Array<Record<string, unknown>>,
): string {
  const currentStem = textFromContent(content);
  const normalizedStem = comparableText(currentStem);
  if (!normalizedStem) return currentStem;

  const currentSegments = contentSegments(content);
  const matchedIndex = currentSegments.findIndex(
    (segment) => isCodeSegment(segment) && (
      normalizedStem === comparableText(codeSegmentText(segment)) ||
      normalizedStem === comparableText(visibleCodeSegmentText(segment))
    ),
  );
  if (matchedIndex < 0) return currentStem;

  const matchedSegment = currentSegments[matchedIndex];
  // Prefer object identity for insert/delete operations because unchanged
  // segments are carried into the next array by reference. For an in-place
  // editor change, the segment object itself is replaced but the array length
  // and index stay stable, so the index is the safe fallback.
  let nextSegment = nextSegments.find((segment) => segment === matchedSegment);
  if (!nextSegment && nextSegments.length === currentSegments.length) {
    const sameIndexSegment = nextSegments[matchedIndex];
    if (sameIndexSegment && isCodeSegment(sameIndexSegment)) {
      nextSegment = sameIndexSegment;
    }
  }

  // Legacy code-only records sometimes duplicated the code into content.stem.
  // Keep that fallback synchronized when the structured code segment changes.
  // If that exact code segment is deleted, clear the duplicated fallback too;
  // otherwise the deleted code would continue to render from stale stem text.
  return nextSegment && isCodeSegment(nextSegment)
    ? visibleCodeSegmentText(nextSegment)
    : "";
}

/** text/newline segments carry the stem text. The edit form edits the stem as a
 * single textarea (content.stem/text); the text segments must be rebuilt to
 * match, or segments-based renderers (admin detail, miniprogram SEGMENTS mode)
 * keep showing the pre-edit snapshot. */
function isStemTextSegment(
  segment: Record<string, unknown> | null | undefined,
): boolean {
  if (!segment || segment.option_key) return false;
  const type = segmentType(segment);
  return type === "text" || type === "newline";
}

function stemTextToSegments(text: string): Array<Record<string, unknown>> {
  const lines = String(text ?? "").split("\n");
  const segments: Array<Record<string, unknown>> = [];
  lines.forEach((line, index) => {
    if (line) segments.push({ type: "text", text: line });
    if (index < lines.length - 1) segments.push({ type: "newline" });
  });
  return segments;
}

function isMathWrapBoundary(left: string, right: string): boolean {
  const leftChar = left.match(/\S(?=\s*$)/)?.[0] ?? "";
  const rightChar = right.match(/^\s*(\S)/)?.[1] ?? "";
  // MathFormula/KaTeX treats whitespace inside an expression as layout
  // whitespace, but textarea renders the same OCR newline as a hard break.
  // Only collapse boundaries that clearly continue an expression so ordinary
  // prose/paragraph line breaks remain editable and persistable.
  const mathContinuationLeft = /[=<>≤≥≠≈→←±×÷+\-*/^_,:([{\\]/;
  const mathContinuationRight = /[=<>≤≥≠≈→←±×÷+\-*/^_,:)\]}]/;
  return mathContinuationLeft.test(leftChar) || mathContinuationRight.test(rightChar);
}

function normalizeStemForEditing(value: string): string {
  const text = String(value ?? "").replace(/\r\n?/g, "\n");
  if (!text.includes("\n") || looksLikeProgrammingCode(text)) return text;

  const lines = text.split("\n");
  let result = lines[0] ?? "";
  for (let index = 1; index < lines.length; index += 1) {
    const right = lines[index] ?? "";
    // Empty adjacent lines are semantic paragraph breaks, never OCR row wraps.
    if (!result || result.endsWith("\n") || !right.trim()) {
      result += `\n${right}`;
      continue;
    }
    if (isMathWrapBoundary(result, right)) {
      result = `${result.replace(/[ \t]+$/, "")}${right.replace(/^[ \t]+/, "")}`;
    } else {
      result += `\n${right}`;
    }
  }
  return result;
}

function updateStemInContent(
  content: unknown,
  newStem: string,
): Record<string, unknown> {
  const record = contentRecord(content);
  const next: Record<string, unknown> = { ...record, stem: newStem, text: newStem };
  if (Array.isArray(record.segments)) {
    const segments = record.segments as Array<Record<string, unknown>>;
    const firstStemIndex = segments.findIndex(isStemTextSegment);
    const insertAt = firstStemIndex < 0
      ? 0
      : segments.slice(0, firstStemIndex).filter((segment) => !isStemTextSegment(segment)).length;
    const nonText = segments.filter((segment) => !isStemTextSegment(segment));
    next.segments = [
      ...nonText.slice(0, insertAt),
      ...stemTextToSegments(newStem),
      ...nonText.slice(insertAt),
    ];
  }
  return next;
}

function textFromContent(
  content: Record<string, unknown> | string | null | undefined,
) {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate = [content.stem, content.text, content.question, content.title]
    .find((value) => typeof value === "string" && value.length > 0);
  if (typeof candidate === "string") return candidate;

  // Segment-only records are valid. Derive only their literal stem text here;
  // code/table/image segments are rendered by their dedicated editors/renderers.
  // Falling back to JSON.stringify(content) made raw JSON appear as the stem
  // and could duplicate code-only questions in the detail view.
  if (Array.isArray(content.segments)) {
    return content.segments
      .map((rawSegment) => {
        if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return "";
        const segment = rawSegment as Record<string, unknown>;
        if (segment.option_key) return "";
        const type = segmentType(segment);
        if (type === "text") return String(segment.text ?? "");
        if (type === "newline") return "\n";
        return "";
      })
      .join("");
  }
  return "";
}

/**
 * The detail renderer treats structured text/newline segments as the visible
 * stem. Some imported records keep an older OCR snapshot in content.stem,
 * including layout-only line breaks, so using content.stem in the textarea can
 * show breaks that are not present in the detail drawer. Prefer the same
 * structured stem text for editing whenever it exists.
 */
function textForStemEditor(
  content: Record<string, unknown> | string | null | undefined,
): string {
  if (!content || typeof content === "string" || !Array.isArray(content.segments)) {
    return textFromContent(content);
  }

  const canonicalText = textFromContent(content);
  const visibleStemSegments = contentSegments(content).filter(
    (segment) => !segment.option_key,
  );
  const hasOnlyTextStemSegments =
    visibleStemSegments.length > 0 && visibleStemSegments.every(isStemTextSegment);

  // Keep the editor aligned with QuestionContentRenderer: text-only programming
  // questions intentionally render the canonical stem because OCR segment order
  // can be region-order rather than reading-order.
  if (
    canonicalText &&
    hasOnlyTextStemSegments &&
    looksLikeProgrammingCode(canonicalText)
  ) {
    return canonicalText;
  }

  let hasStemTextSegment = false;
  const segmentText = content.segments
    .map((rawSegment) => {
      if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return "";
      const segment = rawSegment as Record<string, unknown>;
      if (!isStemTextSegment(segment)) return "";
      const type = segmentType(segment);
      hasStemTextSegment = true;
      return type === "newline" ? "\n" : String(segment.text ?? "");
    })
    .join("");

  return hasStemTextSegment ? segmentText : canonicalText;
}

function nonStemContentSegments(content: unknown): Array<Record<string, unknown>> {
  return contentSegments(content).filter((segment) => !isStemTextSegment(segment));
}

/** Build a minimal PATCH payload from what is actually editable/visible.
 * This avoids persisting legacy normalization side effects (for example an
 * OCR-only content.stem differing from the structured text) when the user only
 * changes an unrelated field. */
function buildQuestionEditPatch(
  form: QuestionEditRequest,
  question: AdminQuestion,
  currentStemText?: string,
): QuestionEditRequest {
  const patch: QuestionEditRequest = {};

  if ((form.answer ?? "") !== (question.answer ?? "")) patch.answer = form.answer ?? "";
  if ((form.analysis ?? "") !== (question.analysis ?? "")) patch.analysis = form.analysis ?? "";
  if ((form.difficulty ?? null) !== (question.difficulty ?? null) && form.difficulty !== undefined) {
    patch.difficulty = form.difficulty;
  }
  if ((form.question_type ?? "") !== (question.question_type ?? "")) {
    patch.question_type = form.question_type ?? "";
  }
  if ((form.subject_id ?? null) !== (question.subject_id ?? null)) {
    patch.subject_id = form.subject_id ?? null;
  }

  const baselineStem = normalizeStemForEditing(textForStemEditor(question.content));
  const editorStem = currentStemText ?? textForStemEditor(form.content);
  const stemChanged = editorStem !== baselineStem;
  const structuredContentChanged =
    JSON.stringify(nonStemContentSegments(form.content)) !==
    JSON.stringify(nonStemContentSegments(question.content));
  const blankOptionGroupsChanged =
    JSON.stringify(resolveBlankOptionGroupsValue(form.content) ?? null) !==
    JSON.stringify(resolveBlankOptionGroupsValue(question.content) ?? null);
  if (stemChanged || structuredContentChanged || blankOptionGroupsChanged) {
    patch.content = stemChanged
      ? updateStemInContent(form.content, editorStem)
      : contentRecord(form.content);
  }

  if (
    comparableOptionState(form.options) !==
    comparableOptionState(resolveQuestionOptions(question) ?? undefined)
  ) {
    patch.options = form.options ?? null;
  }
  if (
    JSON.stringify(form.knowledge_points ?? null) !==
    JSON.stringify(question.knowledge_points ?? null)
  ) {
    patch.knowledge_points = form.knowledge_points ?? [];
  }

  return patch;
}

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  return JSON.stringify(value, null, 2);
}

function renderVersionValue(label: string, value: unknown, emphasized = false) {
  if (label === "题干") {
    const content = value as Record<string, unknown> | string | null | undefined;
    return (
      <div className={`min-w-0 text-slate-600 [overflow-wrap:anywhere] ${emphasized ? "text-sm leading-7" : "text-xs leading-6"}`}>
        <QuestionContentRenderer
          content={content}
          fallbackText={textFromContent(content)}
          preserveCodeText
        />
      </div>
    );
  }

  if (label === "选项") {
    const blankGroups = normalizeBlankOptionGroups(value);
    if (blankGroups.length > 0) {
      return <MultiBlankQuestionOptions groups={blankGroups} />;
    }

    const options = normalizeQuestionOptions(value as QuestionOptionsValue | undefined);
    if (options.length === 0) return <span className="text-xs text-slate-400">—</span>;
    return (
      <div className="space-y-1.5">
        {options.map((option) => (
          <div key={option.key} className="flex items-start gap-2 text-xs leading-5 text-slate-600">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-slate-100 font-semibold text-slate-500">
              {option.key}
            </span>
            <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
              <MathFormula text={option.text || "—"} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (label === "答案") {
    return (
      <div className="min-w-0 text-xs leading-6 text-slate-600 [overflow-wrap:anywhere]">
        <MathFormula text={value == null || value === "" ? "—" : String(value)} />
      </div>
    );
  }

  if (label === "解析") {
    return (
      <div className="min-w-0 text-xs [&_*]:max-w-full">
        <QuestionAnalysis
          value={typeof value === "string" ? value : value ? JSON.stringify(value) : ""}
          compact
        />
      </div>
    );
  }

  if (label === "知识点") {
    return <QuestionKnowledgePointsDisplay value={Array.isArray(value) ? value : []} />;
  }

  if (label === "难度") {
    const difficulty = Number(value);
    return Number.isFinite(difficulty) ? <DifficultyBadge difficulty={difficulty} /> : <span className="text-xs text-slate-400">—</span>;
  }

  const text = renderJson(value);
  return <div className="whitespace-pre-wrap break-words text-xs leading-6 text-slate-600">{text}</div>;
}

function renderDiff(
  label: string,
  leftValue: unknown,
  rightValue: unknown,
  leftTitle: string,
  rightTitle: string,
) {
  const left = renderJson(leftValue);
  const right = renderJson(rightValue);
  const changed = left !== right;
  return (
    <section key={label} className={`rounded-xl border border-slate-200 bg-white ${label === "解析" ? "p-3" : "p-4"}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <span className={`rounded-md px-2 py-1 text-[10px] font-medium ${changed ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
          {changed ? "有变更" : "无变更"}
        </span>
      </div>
      {changed ? (
        <div className="grid gap-3 md:grid-cols-2">
          <div className={`min-w-0 rounded-lg bg-amber-50/70 ${label === "解析" ? "p-2.5" : "p-3"}`}>
            <p className="mb-2 text-[10px] font-semibold tracking-wide text-amber-700">{leftTitle}</p>
            {renderVersionValue(label, leftValue)}
          </div>
          <div className={`min-w-0 rounded-lg bg-emerald-50/60 ${label === "解析" ? "p-2.5" : "p-3"}`}>
            <p className="mb-2 text-[10px] font-semibold tracking-wide text-emerald-700">{rightTitle}</p>
            {renderVersionValue(label, rightValue)}
          </div>
        </div>
      ) : (
        <div className="rounded-lg bg-slate-50 p-3">{renderVersionValue(label, leftValue, label === "题干")}</div>
      )}
    </section>
  );
}

function isMultiChoice(questionType: string): boolean {
  return canonicalizeQuestionType(questionType) === "multiple_choice";
}

function isMultiBlankChoice(questionType: string): boolean {
  const code = canonicalizeQuestionType(questionType);
  return code === "multi_blank_choice" || code === "multi_blank_multiple_choice";
}

/** 多空（多选）选择题：每空可选多个选项 */
function isMultiBlankMultipleChoice(questionType: string): boolean {
  return canonicalizeQuestionType(questionType) === "multi_blank_multiple_choice";
}

function blankOptionGroupsStorageField(
  content: unknown,
): "blank_option_groups" | "blank_groups" {
  const record = contentRecord(content);
  if (record.blank_option_groups != null) return "blank_option_groups";
  if (record.blank_groups != null) return "blank_groups";
  return "blank_option_groups";
}

function normalizedChoiceAnswerKeys(answer: string | null | undefined): string[] {
  const seen = new Set<string>();
  return String(answer ?? "")
    .split(/[,，\s]+/)
    .map((key) => key.trim().toUpperCase())
    .filter((key) => {
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function parseMultiBlankChoiceAnswer(
  answer: string | null | undefined,
): Array<{ blankId: string; optionKey: string }> {
  return String(answer ?? "")
    .split(/[;；]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const separatorIndex = entry.search(/[:：]/);
      if (separatorIndex < 0) return null;

      const blankId = entry.slice(0, separatorIndex).trim();
      const optionKey = entry.slice(separatorIndex + 1).trim();
      if (!blankId || !optionKey) return null;

      return { blankId, optionKey };
    })
    .filter((item): item is { blankId: string; optionKey: string } => item !== null);
}

function updateMultiBlankChoiceAnswer(
  answer: string | null | undefined,
  blankIds: string[],
  targetBlankId: string,
  optionKey: string,
  toggleMulti = false,
): string {
  const parsed = parseMultiBlankChoiceAnswer(answer);
  const values = new Map(parsed.map((item) => [item.blankId, item.optionKey]));
  const nextOptionKey = optionKey.trim().toUpperCase();

  if (toggleMulti) {
    // Multi-select blank: toggle one letter within the slot's letter set.
    const current = (values.get(targetBlankId) ?? "")
      .split(",")
      .map((l) => l.trim().toUpperCase())
      .filter(Boolean);
    const next = current.includes(nextOptionKey)
      ? current.filter((l) => l !== nextOptionKey)
      : [...current, nextOptionKey].sort();
    if (next.length > 0) values.set(targetBlankId, next.join(","));
    else values.delete(targetBlankId);
  } else if (nextOptionKey) values.set(targetBlankId, nextOptionKey);
  else values.delete(targetBlankId);

  const orderedIds: string[] = [];
  const seen = new Set<string>();
  for (const id of [...blankIds, ...parsed.map((item) => item.blankId)]) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    orderedIds.push(id);
  }

  return orderedIds
    .map((blankId) => {
      const value = values.get(blankId)?.trim();
      return value ? `${blankId}:${value}` : "";
    })
    .filter(Boolean)
    .join(";");
}

function QuestionAnswerDisplay({
  questionType,
  answer,
}: {
  questionType: string;
  answer: string | null | undefined;
}) {
  if (isMultiBlankChoice(questionType)) {
    const items = parseMultiBlankChoiceAnswer(answer);
    if (items.length > 0) {
      return (
        <div className="space-y-1">
          {items.map((item, index) => (
            <div
              key={`${item.blankId}-${index}`}
              className="grid grid-cols-[auto_1fr] items-center gap-x-3 leading-6"
            >
              <span>{item.blankId}</span>
              <span>
                <MathFormula text={item.optionKey} />
              </span>
            </div>
          ))}
        </div>
      );
    }
  }

  return <MathFormula text={answer || "—"} />;
}

function comparableOptionState(options: QuestionOptionsValue | undefined): string {
  return JSON.stringify(
    normalizeQuestionOptions(options).map((option) => ({
      key: option.key,
      text: option.text ?? "",
      imageUrl: option.imageUrl ?? "",
    })),
  );
}

function optionsToKeyValueList(
  options: QuestionOptionsValue | undefined,
): Array<{ key: string; text: string }> {
  return normalizeQuestionOptions(options).map((option) => ({
    key: option.key,
    text: option.text ?? "",
  }));
}

function optionStorageKey(
  options: QuestionOptionsValue | undefined,
  key: string,
): string {
  if (!options || typeof options !== "object" || Array.isArray(options)) return key;
  const normalizedKey = key.trim().toUpperCase();
  return (
    Object.keys(options).find(
      (candidate) => candidate.trim().toUpperCase() === normalizedKey,
    ) ?? key
  );
}

function optionImageUrl(
  options: QuestionOptionsValue | undefined,
  key: string,
): string | null {
  if (!options || typeof options !== "object" || Array.isArray(options)) return null;
  const storageKey = optionStorageKey(options, key);
  const value = (options as Record<string, unknown>)[storageKey];
  if (!value || typeof value !== "object") return null;
  const norm = normalizeQuestionOptions({ [storageKey]: value });
  return norm[0]?.imageUrl ?? null;
}

type QuestionWithImport = AdminQuestion & {
  import_record?: AdminQuestionImportSummary | null;
};

function renderSecondaryQuestionInfo(question: QuestionWithImport) {
  const importRecord = question.import_record;
  return (
    <details className="rounded-2xl border border-[var(--color-border)] bg-white/55 p-4 text-sm">
      <summary className="cursor-pointer list-none">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-semibold text-[var(--ink)]">辅助信息</p>
            <p className="mt-1 text-xs text-[var(--color-text-hint)]">
              科目、年份、启用状态与导入关联信息
            </p>
          </div>
        </div>
      </summary>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {[
          ["科目", question.subject_name || question.subject_code || "—"],
          ["年份", question.year || "—"],
          ["启用状态", question.is_active ? "启用" : "停用"],
          ["题目 ID", `#${question.id}`],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-2"
          >
            <p className="text-[11px] text-[var(--color-text-hint)]">
              {label}
            </p>
            <p className="mt-1 break-words text-sm font-medium text-[var(--color-text-secondary)]">
              {value}
            </p>
          </div>
        ))}
      </div>

      {importRecord ? (
        <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] p-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                题目 hash
              </p>
              <p className="mt-1 break-all font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.question_hash || "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                正式题关联
              </p>
              <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.duplicate_of_question_id
                  ? `#${importRecord.duplicate_of_question_id}`
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--color-text-hint)]">
                导入项关联
              </p>
              <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                {importRecord.duplicate_of_import_id
                  ? `#${importRecord.duplicate_of_import_id}`
                  : "—"}
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </details>
  );
}

/** Difficulty pill */
function DifficultyBadge({
  difficulty,
}: {
  difficulty: number | string | null | undefined;
}) {
  const d = Number(difficulty) || 0;
  const colors = [
    "bg-emerald-50 text-emerald-700 border-emerald-200",
    "bg-green-50 text-green-700 border-green-200",
    "bg-amber-50 text-amber-700 border-amber-200",
    "bg-orange-50 text-orange-700 border-orange-200",
    "bg-red-50 text-red-700 border-red-200",
  ];
  const idx = Math.min(Math.max(Math.round(d) - 1, 0), colors.length - 1);
  const label = ["简单", "较易", "中等", "较难", "困难"];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${colors[idx]}`}
    >
      <BarChart3 className="h-3 w-3" />
      {label[idx] ?? d}
    </span>
  );
}

/** Type badge */
function TypeBadge({ type: t }: { type: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-white/80 px-1.5 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)]">
      <Layers className="h-3 w-3" />
      {getQuestionTypeLabel(t)}
    </span>
  );
}

function CustomCheckbox({
  checked,
  onChange,
  className = "",
}: {
  checked: boolean;
  onChange: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onChange}
      className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors ${
        checked
          ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
          : "border-[var(--color-border)] bg-white hover:border-[var(--color-text-hint)]"
      } ${className}`}
    >
      {checked && <Check className="h-3 w-3 text-white" strokeWidth={3} />}
    </button>
  );
}

export default function QuestionsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const permissions = useAuthStore((state) => state.permissions);
  const [filters, setFilters] = useState<QuestionListFilters>(() => ({
    ...DEFAULT_QUESTION_FILTERS,
    subject_id: searchParams.get("subject_id") ?? "",
    is_active: searchParams.has("is_active")
      ? (searchParams.get("is_active") ?? "")
      : DEFAULT_QUESTION_FILTERS.is_active,
    question_type: searchParams.get("question_type") ?? "",
    keyword: searchParams.get("keyword") ?? "",
    year: searchParams.get("year") ?? "",
    difficulty: searchParams.get("difficulty") ?? "",
    import_batch_id: searchParams.get("import_batch_id") ?? "",
    knowledge_point_id: searchParams.get("knowledge_point_id") ?? "",
  }));
  const [keywordInput, setKeywordInput] = useState(filters.keyword);
  const [searchDebouncing, setSearchDebouncing] = useState(false);
  const [importBatchInput, setImportBatchInput] = useState(filters.import_batch_id);
  const [subjectOptions, setSubjectOptions] = useState<
    Array<{ id: number; code: string; name: string }>
  >([]);
  useEffect(() => {
    type SubjectNode = {
      id: number;
      code: string;
      name: string;
      path: string;
      level: number;
      children?: SubjectNode[];
    };
    const flattenSubjects = (items: SubjectNode[]): SubjectNode[] =>
      items.flatMap((item) => [item, ...flattenSubjects(item.children ?? [])]);

    apiRequest<{ items: SubjectNode[] }>("/subjects")
      .then((response) =>
        setSubjectOptions(
          flattenSubjects(response.items ?? []).filter((subject) => subject.level > 1),
        ),
      )
      .catch(() => {});
  }, []);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(() => positiveInt(searchParams.get("page"), 1) ?? 1);
  const [pageSize, setPageSize] = useState(() => normalizeQuestionPageSize(searchParams.get("page_size")));
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(() =>
    positiveInt(searchParams.get("selected_id")),
  );
  const [isDetailDrawerOpen, setIsDetailDrawerOpen] = useState(false);
  const [baseVersion, setBaseVersion] = useState<QuestionVersionSelection>("current");
  const [compareVersion, setCompareVersion] = useState<QuestionVersionSelection | null>(null);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [unsavedIntent, setUnsavedIntent] = useState<UnsavedIntent>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [isCommonFilterMenuOpen, setIsCommonFilterMenuOpen] = useState(false);
  const [isMoreFilterOpen, setIsMoreFilterOpen] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<"csv" | "docx" | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<QuestionEditRequest>({});
  const [editStemText, setEditStemText] = useState("");

  useEffect(() => {
    setVersionHistoryOpen(false);
    setBaseVersion("current");
    setCompareVersion(null);
  }, [selectedQuestionId]);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);
  const commonFilterMenuRef = useRef<HTMLDivElement | null>(null);
  const moreFilterRef = useRef<HTMLDivElement | null>(null);
  const detailScrollRef = useRef<HTMLDivElement | null>(null);
  const draftSavePromiseRef = useRef<Promise<boolean> | null>(null);

  const canWrite = hasPermission(permissions, "question:write");
  const canDelete = hasPermission(permissions, "question:delete");

  // Keep the list context in the address bar so leaving for a detail/editor page
  // and returning restores the exact filter/page/selection instead of resetting.
  useEffect(() => {
    const nextHref = buildQuestionListHref(filters, page, pageSize, selectedQuestionId);
    const currentHref = `${window.location.pathname}${window.location.search}`;
    if (currentHref !== nextHref) {
      window.history.replaceState(window.history.state, "", nextHref);
    }
  }, [filters, page, pageSize, selectedQuestionId]);

  const queryParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
      is_active: filters.is_active,
      question_type: filters.question_type,
      keyword: filters.keyword,
      year: filters.year,
      difficulty: filters.difficulty ? Number(filters.difficulty) : undefined,
      import_batch_id: filters.import_batch_id || undefined,
      knowledge_point_id: filters.knowledge_point_id ? Number(filters.knowledge_point_id) : undefined,
    }),
    [page, pageSize, filters],
  );

  const questions = useQuery({
    queryKey: ["questions", queryParams],
    queryFn: () =>
      apiRequest<PaginatedResponse<AdminQuestion>>(
        `/questions${toQuery(queryParams)}`,
      ),
    placeholderData: (previousData) => previousData,
    retry: false,
  });

  const detail = useQuery({
    queryKey: ["questions", selectedQuestionId, "detail"],
    queryFn: () =>
      apiRequest<AdminQuestionDetail>(`/questions/${selectedQuestionId}`),
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const versions = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions"],
    queryFn: async () => {
      const firstPage = await apiRequest<PaginatedResponse<QuestionVersion>>(
        `/questions/${selectedQuestionId}/versions${toQuery({
          page: 1,
          page_size: VERSION_HISTORY_PAGE_SIZE,
        })}`,
      );
      if (firstPage.total_pages <= 1) return firstPage;

      // 通常只有几十个版本；超过 100 个时在后台并行补齐后续页，
      // 选择器仍呈现为一条连续的时间轴，不把“页”的概念暴露给用户。
      const remainingPages = await Promise.all(
        Array.from({ length: firstPage.total_pages - 1 }, (_, index) =>
          apiRequest<PaginatedResponse<QuestionVersion>>(
            `/questions/${selectedQuestionId}/versions${toQuery({
              page: index + 2,
              page_size: VERSION_HISTORY_PAGE_SIZE,
            })}`,
          ),
        ),
      );
      return {
        ...firstPage,
        items: [
          ...firstPage.items,
          ...remainingPages.flatMap((response) => response.items),
        ],
      };
    },
    enabled: selectedQuestionId !== null,
    retry: false,
  });

  const baseVersionDetail = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions", baseVersion],
    queryFn: () =>
      apiRequest<QuestionVersionDetail>(
        `/questions/${selectedQuestionId}/versions/${baseVersion}`,
      ),
    enabled: selectedQuestionId !== null && typeof baseVersion === "number",
    // 切换版本时保留上一份已完成的数据，避免对比区域先塌缩成 loading 再重新撑开。
    placeholderData: (previousData) =>
      previousData?.question_id === selectedQuestionId ? previousData : undefined,
    retry: false,
  });

  const compareVersionDetail = useQuery({
    queryKey: ["questions", selectedQuestionId, "versions", compareVersion],
    queryFn: () =>
      apiRequest<QuestionVersionDetail>(
        `/questions/${selectedQuestionId}/versions/${compareVersion}`,
      ),
    enabled: selectedQuestionId !== null && typeof compareVersion === "number",
    placeholderData: (previousData) =>
      previousData?.question_id === selectedQuestionId ? previousData : undefined,
    retry: false,
  });

  useEffect(() => {
    if (!versionHistoryOpen || compareVersion !== null) return;
    const latestHistoricalVersion = versions.data?.items?.[0]?.version;
    if (latestHistoricalVersion !== undefined) {
      setCompareVersion(latestHistoricalVersion);
    }
  }, [compareVersion, versionHistoryOpen, versions.data?.items]);

  const deleteMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "batch-delete") {
        const ids = Array.from(selectedIds);
        const aggregate: BatchDeleteResult = { success_ids: [], failed_items: [] };

        // 后端单次批量删除最多接收 50 条；前端分块执行，避免 50/100 条每页时直接 422。
        for (let start = 0; start < ids.length; start += BATCH_DELETE_CHUNK_SIZE) {
          const chunk = ids.slice(start, start + BATCH_DELETE_CHUNK_SIZE);
          try {
            const result = await apiRequest<BatchDeleteResult>(
              "/questions/batch-delete",
              {
                method: "POST",
                body: JSON.stringify({ ids: chunk }),
              },
            );
            aggregate.success_ids?.push(
              ...(result.success_ids ?? result.successIds ?? []),
            );
            aggregate.failed_items?.push(
              ...(result.failed_items ?? result.failedItems ?? []),
            );
          } catch (error) {
            const errorText =
              error instanceof Error ? error.message : "批量删除请求失败";
            aggregate.failed_items?.push(
              ...chunk.map((id) => ({ id, error: errorText })),
            );
          }
        }
        return aggregate;
      }
      return apiRequest<{ status: string }>(`/questions/${state.id}`, {
        method: "DELETE",
      });
    },
    onSuccess: (result, variables: Exclude<ConfirmState, null>) => {
      if (variables.action === "delete") {
        setMessage(`题目 #${variables.id} 已删除。`);
        setSelectedQuestionId(null);
        setIsDetailDrawerOpen(false);
      } else {
        const r = result as BatchDeleteResult;
        const successIds = r.success_ids ?? r.successIds ?? [];
        const failedItems = r.failed_items ?? r.failedItems ?? [];
        const failurePreview = failedItems
          .slice(0, 5)
          .map((item) => `#${item.id} ${item.error}`)
          .join("；");
        const failures = failedItems.length
          ? `失败 ${failedItems.length} 条：${failurePreview}${failedItems.length > 5 ? "；…" : ""}`
          : "无失败项";
        setMessage(`批量删除完成，成功 ${successIds.length} 条，${failures}。`);
        if (selectedQuestionId !== null && successIds.includes(selectedQuestionId)) {
          setSelectedQuestionId(null);
          setIsDetailDrawerOpen(false);
        }
      }
      setSelectedIds(new Set());
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "删除失败，请稍后重试。",
      );
    },
  });

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!selectedQuestionId) throw new Error("未选中题目");
      const baseline = detail.data;
      if (!baseline) throw new Error("题目详情尚未加载完成");
      const patch = buildQuestionEditPatch(editForm, baseline, editStemText);
      if (Object.keys(patch).length === 0) throw new Error("没有需要保存的修改");
      return apiRequest<AdminQuestion>(`/questions/${selectedQuestionId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
    },
    onSuccess: () => {
      setMessage("题目已更新。");
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
      queryClient.invalidateQueries({
        queryKey: ["questions", selectedQuestionId],
      });
    },
    onError: (error) => {
      setMessage(
        error instanceof Error ? error.message : "更新失败，请稍后重试。",
      );
    },
  });

  const items = useMemo(
    () => questions.data?.items ?? [],
    [questions.data?.items],
  );
  const hasActiveFilters = Boolean(
    filters.subject_id ||
      filters.question_type ||
      filters.year ||
      filters.is_active !== "true" ||
      filters.keyword ||
      filters.difficulty ||
      filters.import_batch_id ||
      filters.knowledge_point_id,
  );
  const allChecked =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const selectedQuestion = detail.data;
  const baseVersionData =
    baseVersion === "current" ? selectedQuestion : baseVersionDetail.data;
  const compareVersionData =
    compareVersion === "current" ? selectedQuestion : compareVersionDetail.data;
  // placeholderData 会在新版本到达前保留上一份详情，因此标签也跟随“当前实际展示的数据”
  // 而不是提前切到新版本号，避免短暂出现“新标签 + 旧内容”的错觉。
  const baseVersionLabel =
    baseVersion === "current"
      ? "当前版本"
      : baseVersionDetail.data?.version
        ? `v${baseVersionDetail.data.version}`
        : `v${baseVersion}`;
  const compareVersionLabel =
    compareVersion === "current"
      ? "当前版本"
      : compareVersion === null
        ? "请选择版本"
        : compareVersionDetail.data?.version
          ? `v${compareVersionDetail.data.version}`
          : `v${compareVersion}`;
  const versionComparisonLoading =
    (typeof baseVersion === "number" && baseVersionDetail.isFetching) ||
    (typeof compareVersion === "number" && compareVersionDetail.isFetching);
  const pendingVersionLabel =
    typeof baseVersion === "number" && baseVersionDetail.isFetching
      ? `v${baseVersion}`
      : typeof compareVersion === "number" && compareVersionDetail.isFetching
        ? `v${compareVersion}`
        : null;
  const editingSegments = useMemo(
    () => contentSegments(editForm.content),
    [editForm.content],
  );
  const editingFallbackStemImageUrls = useMemo(
    () =>
      fallbackQuestionImageUrls(
        selectedQuestion?.content,
        selectedQuestion?.image_url,
      ),
    [selectedQuestion?.content, selectedQuestion?.image_url],
  );
  const unresolvedEditingTableCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      const table = normalizeStructuredTableSegment(segment);
      return count + (table?.requires_review ? 1 : 0);
    }, 0),
    [editingSegments],
  );
  const emptyEditingCodeCount = useMemo(
    () => editingSegments.reduce((count, segment) => {
      if (!isCodeSegment(segment)) return count;
      return count + (comparableText(codeSegmentText(segment)) ? 0 : 1);
    }, 0),
    [editingSegments],
  );

  const replaceEditingSegments = useCallback(
    (segments: Array<Record<string, unknown>>) => {
      setEditForm((current) => {
        const currentContent = contentRecord(current.content);
        const stem = canonicalStemAfterSegmentUpdate(currentContent, segments);
        return {
          ...current,
          content: {
            ...currentContent,
            stem,
            text: stem,
            render_mode: "segments",
            segments,
          },
        };
      });
    },
    [],
  );

  const addEditingCodeSegment = useCallback(() => {
    setEditForm((current) => {
      const currentContent = contentRecord(current.content);
      const segments = contentSegments(current.content);
      // Keep manually added code adjacent to the stem. If code blocks already
      // exist, append after the last one; otherwise insert before image/table
      // regions so a newly added code sample does not unexpectedly render below
      // a stem illustration that was imported earlier.
      let insertAt = segments.reduce(
        (lastCodeIndex, segment, index) => isCodeSegment(segment) ? index + 1 : lastCodeIndex,
        -1,
      );
      if (insertAt < 0) {
        insertAt = segments.findIndex((segment) => !isStemTextSegment(segment));
        if (insertAt < 0) insertAt = segments.length;
      }
      const nextSegments = [...segments];
      nextSegments.splice(insertAt, 0, {
        type: "code",
        code: "",
        language: "",
      });
      const stem = canonicalStemAfterSegmentUpdate(currentContent, nextSegments);
      return {
        ...current,
        content: {
          ...currentContent,
          stem,
          text: stem,
          render_mode: "segments",
          segments: nextSegments,
        },
      };
    });
  }, []);

  const dirty = useMemo(() => {
    if (!selectedQuestion) return false;
    return Object.keys(buildQuestionEditPatch(editForm, selectedQuestion, editStemText)).length > 0;
  }, [editForm, editStemText, selectedQuestion]);

  const mergeQuestionIntoDetailCache = useCallback(
    (question: AdminQuestion) => {
      if (selectedQuestionId === null) return;
      queryClient.setQueryData<AdminQuestionDetail>(
        ["questions", selectedQuestionId, "detail"],
        (current) =>
          current
            ? { ...current, ...question, import_record: current.import_record ?? null }
            : (question as AdminQuestionDetail),
      );
    },
    [queryClient, selectedQuestionId],
  );

  // Called after an immediate-write image/option mutation: adopt the fresh
  // content/options so the next "保存" does not overwrite the just-written change.
  const handleQuestionMutated = useCallback(
    (question: AdminQuestion) => {
      setEditForm((current) => ({
        ...current,
        content: contentRecord(question.content),
        options: question.options ?? undefined,
      }));
      // Keep detail-only fields (notably import_record) while adopting the
      // mutation response. Replacing the detail cache with a list-item response
      // temporarily erased that metadata until the refetch completed.
      mergeQuestionIntoDetailCache(question);
      queryClient.invalidateQueries({ queryKey: ["questions", selectedQuestionId] });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    [mergeQuestionIntoDetailCache, queryClient, selectedQuestionId],
  );

  const prepareImmediateQuestionMutation = useCallback(async (): Promise<boolean> => {
    if (!dirty) return true;
    if (selectedQuestionId === null) {
      setMessage("未选中题目，无法保存当前修改。");
      return false;
    }
    if (unresolvedEditingTableCount > 0) {
      setMessage("请先完成结构化表格核验，再继续图片或选项操作。");
      return false;
    }
    if (emptyEditingCodeCount > 0) {
      setMessage("请先填写或删除空代码块，再继续图片或选项操作。");
      return false;
    }
    if (draftSavePromiseRef.current) return draftSavePromiseRef.current;

    const task = (async () => {
      try {
        if (!selectedQuestion) {
          setMessage("题目详情尚未加载完成，无法保存当前修改。");
          return false;
        }
        const patch = buildQuestionEditPatch(editForm, selectedQuestion, editStemText);
        if (Object.keys(patch).length === 0) return true;
        const question = await apiRequest<AdminQuestion>(
          `/questions/${selectedQuestionId}`,
          {
            method: "PATCH",
            body: JSON.stringify(patch),
          },
        );
        mergeQuestionIntoDetailCache(question);
        setEditForm({
          subject_id: question.subject_id ?? null,
          question_type: question.question_type || "",
          difficulty: question.difficulty,
          answer: question.answer || "",
          analysis: question.analysis || "",
          options: question.options ?? undefined,
          content: contentRecord(question.content),
          knowledge_points: question.knowledge_points ?? undefined,
        });
        setEditStemText(normalizeStemForEditing(textForStemEditor(question.content)));
        queryClient.invalidateQueries({ queryKey: ["questions"] });
        queryClient.invalidateQueries({ queryKey: ["questions", selectedQuestionId] });
        setMessage("已先保存当前修改，将继续执行该操作。");
        return true;
      } catch (error) {
        setMessage(
          error instanceof Error
            ? `当前修改保存失败：${error.message}`
            : "当前修改保存失败，请稍后重试。",
        );
        return false;
      }
    })();

    draftSavePromiseRef.current = task;
    try {
      return await task;
    } finally {
      draftSavePromiseRef.current = null;
    }
  }, [
    dirty,
    editForm,
    editStemText,
    emptyEditingCodeCount,
    mergeQuestionIntoDetailCache,
    queryClient,
    selectedQuestion,
    selectedQuestionId,
    unresolvedEditingTableCount,
  ]);

  const updateFilter = (key: keyof typeof filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
    // 与公式库保持一致：筛选刷新时保留详情上下文，等新列表返回后再自动校正选中项。
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
  };

  // 搜索框防抖：停止输入 KEYWORD_DEBOUNCE_MS 后才提交 filters.keyword 并请求
  const keywordTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importBatchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (keywordTimer.current) clearTimeout(keywordTimer.current);
      if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    };
  }, []);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    const next = value.trim();
    if (next === filters.keyword) {
      setSearchDebouncing(false);
      return;
    }
    setSearchDebouncing(true);
    if (next === "") {
      keywordTimer.current = setTimeout(() => {
        updateFilter("keyword", "");
        setSearchDebouncing(false);
      }, 100);
      return;
    }
    keywordTimer.current = setTimeout(() => {
      updateFilter("keyword", next);
      setSearchDebouncing(false);
    }, KEYWORD_DEBOUNCE_MS);
  };

  const handleImportBatchChange = (value: string) => {
    setImportBatchInput(value);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    if (value.trim() === "") {
      updateFilter("import_batch_id", "");
      return;
    }
    importBatchTimer.current = setTimeout(() => {
      updateFilter("import_batch_id", value.trim());
    }, IMPORT_BATCH_DEBOUNCE_MS);
  };

  const handleResetFilters = () => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    setKeywordInput("");
    setSearchDebouncing(false);
    setImportBatchInput("");
    setFilters({ ...DEFAULT_QUESTION_FILTERS });
    setPage(1);
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
  };

  const handlePageSizeChange = (value: string) => {
    setPageSize(Number(value) || 20);
    setPage(1);
  };

  const applyFilterPreset = (
    patch: Partial<typeof filters>,
  ) => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    const next: QuestionListFilters = {
      ...DEFAULT_QUESTION_FILTERS,
      ...patch,
    };
    setFilters(next);
    setKeywordInput(next.keyword);
    setSearchDebouncing(false);
    setImportBatchInput(next.import_batch_id);
    setPage(1);
    setSelectedIds(new Set());
    setIsDetailDrawerOpen(false);
    setIsCommonFilterMenuOpen(false);
  };

  const handleSaveCurrentFilters = () => {
    try {
      window.localStorage.setItem(
        "admin-question-saved-filter",
        JSON.stringify(filters),
      );
      setMessage("当前筛选条件已保存到本机。 ");
    } catch {
      setMessage("筛选保存失败，请检查浏览器存储权限。 ");
    }
  };

  const handleApplySavedFilters = () => {
    try {
      const raw = window.localStorage.getItem("admin-question-saved-filter");
      if (!raw) {
        setMessage("暂无已保存的筛选条件。 ");
        setIsCommonFilterMenuOpen(false);
        return;
      }
      const parsed = JSON.parse(raw) as Partial<typeof filters>;
      applyFilterPreset({
        ...parsed,
        // Older saved presets used an empty is_active value to mean “all”.
        // Treat that legacy value as active-only so soft-deleted questions stay hidden.
        is_active: parsed.is_active === "false" ? "false" : "true",
      });
    } catch {
      setMessage("已保存的筛选条件无法读取。 ");
      setIsCommonFilterMenuOpen(false);
    }
  };

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), 3800);
    return () => window.clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    const totalPages = questions.data?.total_pages;
    if (typeof totalPages !== "number") return;
    const safeLastPage = Math.max(1, totalPages);
    if (page > safeLastPage) setPage(safeLastPage);
  }, [page, questions.data?.total_pages]);

  useEffect(() => {
    if (!(isCommonFilterMenuOpen || isMoreFilterOpen || isExportMenuOpen)) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setIsCommonFilterMenuOpen(false);
      setIsMoreFilterOpen(false);
      setIsExportMenuOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isCommonFilterMenuOpen, isMoreFilterOpen, isExportMenuOpen]);

  useEffect(() => {
    if (!isCommonFilterMenuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        commonFilterMenuRef.current &&
        !commonFilterMenuRef.current.contains(event.target as Node)
      ) {
        setIsCommonFilterMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isCommonFilterMenuOpen]);

  useEffect(() => {
    if (!isMoreFilterOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        moreFilterRef.current &&
        !moreFilterRef.current.contains(event.target as Node)
      ) {
        setIsMoreFilterOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isMoreFilterOpen]);

  useEffect(() => {
    if (!isExportMenuOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (
        exportMenuRef.current &&
        !exportMenuRef.current.contains(event.target as Node)
      ) {
        setIsExportMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isExportMenuOpen]);

  const handleExport = async (format: "csv" | "docx") => {
    try {
      setExportingFormat(format);
      setIsExportMenuOpen(false);
      const response = await apiRequestBlob("/questions/export", {
        method: "POST",
        timeoutMs: 120_000,
        body: JSON.stringify({
          format,
          ids: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
          subject_id: filters.subject_id ? Number(filters.subject_id) : undefined,
          is_active:
            filters.is_active === ""
              ? undefined
              : filters.is_active === "true",
          question_type: filters.question_type || undefined,
          keyword: filters.keyword || undefined,
          year: filters.year ? Number(filters.year) : undefined,
          difficulty: filters.difficulty
            ? Number(filters.difficulty)
            : undefined,
          import_batch_id: filters.import_batch_id || undefined,
          knowledge_point_id: filters.knowledge_point_id ? Number(filters.knowledge_point_id) : undefined,
        }),
      });
      const url = URL.createObjectURL(response.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download =
        response.filename ?? `questions-export.${format === "docx" ? "docx" : "csv"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(
        format === "csv" ? "CSV 导出已开始。" : "Word 导出已开始。",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "导出失败，请稍后重试。",
      );
    } finally {
      setExportingFormat(null);
    }
  };

  const toggleAll = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allChecked) {
        items.forEach((item) => next.delete(item.id));
      } else {
        items.forEach((item) => next.add(item.id));
      }
      return next;
    });
  };

  const toggleOne = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectQuestion = useCallback((id: number) => {
    setSelectedQuestionId(id);
    setEditing(false);
    setEditForm({});
  }, []);

  const openDetail = useCallback(
    (id: number) => {
      selectQuestion(id);
      setIsDetailDrawerOpen(true);
    },
    [selectQuestion],
  );

  const prefetchDetail = useCallback(
    (id: number) => {
      void queryClient.prefetchQuery({
        queryKey: ["questions", id, "detail"],
        queryFn: () => apiRequest<AdminQuestionDetail>(`/questions/${id}`),
        staleTime: 30_000,
      });
    },
    [queryClient],
  );

  useEffect(() => {
    if (!items.length) {
      if (!questions.isFetching) setSelectedQuestionId(null);
      return;
    }
    if (selectedQuestionId === null || !items.some((item) => item.id === selectedQuestionId)) {
      setSelectedQuestionId(items[0].id);
      setEditing(false);
      setEditForm({});
    }
  }, [items, questions.isFetching, selectedQuestionId]);

  useEffect(() => {
    if (selectedQuestionId === null) return;
    const frame = window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedQuestionId]);

  const startEditing = () => {
    if (!selectedQuestion) return;
    // Pre-fill form from current question data
    const content = selectedQuestion.content;
    // Legacy questions can still store content as a plain string. Spreading a
    // cloned string into an object produces numeric character keys ("0",
    // "1", ...), which are then persisted on save. Normalize that legacy
    // shape before constructing the edit form so opening the editor can never
    // corrupt otherwise valid content.
    const clonedRaw = JSON.parse(JSON.stringify(content ?? {})) as unknown;
    const clonedContent = contentRecord(clonedRaw);
    // Keep the persisted content snapshot untouched. The textarea has its own
    // display/edit state so OCR layout-only newlines can be hidden without
    // making the form dirty or rewriting content on unrelated edits.
    const editableContent = typeof clonedRaw === "string"
      ? { stem: clonedRaw, text: clonedRaw }
      : clonedContent;
    setEditStemText(normalizeStemForEditing(textForStemEditor(editableContent)));
    const rawOpts = resolveQuestionOptions(selectedQuestion);
    let editOpts: Record<string, unknown> | undefined;
    if (rawOpts && typeof rawOpts === "object" && !Array.isArray(rawOpts)) {
      editOpts = rawOpts as Record<string, unknown>;
    } else if (rawOpts) {
      // Convert array/string to Record for editing compatibility
      const norm = normalizeQuestionOptions(rawOpts);
      editOpts = Object.fromEntries(
        norm.map((o) => [
          o.key,
          o.imageUrl ? { text: o.text ?? "", url: o.imageUrl } : (o.text ?? ""),
        ]),
      );
    }
    setEditForm({
      subject_id: selectedQuestion.subject_id ?? null,
      question_type: selectedQuestion.question_type || "",
      difficulty: selectedQuestion.difficulty,
      answer: selectedQuestion.answer || "",
      analysis: selectedQuestion.analysis || "",
      options: editOpts,
      content: editableContent,
      knowledge_points: selectedQuestion.knowledge_points ?? undefined,
    });
    setEditing(true);
    window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
  };

  const finishCancelEditing = useCallback(() => {
    setEditing(false);
    setEditForm({});
    setEditStemText("");
    setUnsavedIntent(null);
  }, []);

  const finishCloseDetailDrawer = useCallback(() => {
    setEditing(false);
    setEditForm({});
    setEditStemText("");
    setUnsavedIntent(null);
    setIsDetailDrawerOpen(false);
  }, []);

  const cancelEditing = () => {
    if (dirty) {
      setUnsavedIntent("cancel-edit");
      return;
    }
    finishCancelEditing();
  };

  const closeDetailDrawer = () => {
    if (editing && dirty) {
      setUnsavedIntent("close-drawer");
      return;
    }
    finishCloseDetailDrawer();
  };

  useEffect(() => {
    if (!isDetailDrawerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isDetailDrawerOpen]);

  useEffect(() => {
    if (!(editing && dirty)) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty, editing]);

  useEffect(() => {
    if (!isDetailDrawerOpen) return;
    const handleDrawerEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // CustomSelect portals handle Escape themselves. Do not let the same key
      // press also exit edit mode or close the drawer.
      if (document.querySelector('[role="combobox"][aria-expanded="true"]')) return;
      if (document.querySelector('[data-confirm-dialog="true"]')) return;
      if (confirmState !== null || unsavedIntent !== null) return;

      event.preventDefault();
      if (editing) {
        if (dirty) setUnsavedIntent("cancel-edit");
        else finishCancelEditing();
      } else {
        finishCloseDetailDrawer();
      }
    };
    document.addEventListener("keydown", handleDrawerEscape);
    return () => document.removeEventListener("keydown", handleDrawerEscape);
  }, [
    confirmState,
    dirty,
    editing,
    finishCancelEditing,
    finishCloseDetailDrawer,
    isDetailDrawerOpen,
    unsavedIntent,
  ]);

  const confirmDescription =
    confirmState?.action === "batch-delete"
      ? "删除后这些题目将从题库永久移除，此操作不可撤销。"
      : "删除后该题目将从题库永久移除，此操作不可撤销。";

  return (
    <div className="space-y-4 pb-10">
      <Card className="overflow-visible border border-[var(--color-border)] bg-white/90 shadow-[var(--shadow-card)]">
        <CardHeader className="space-y-4 pb-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                正式题库
              </h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                点击题目查看题干、选项、答案与解析；详情面板用于编辑、版本对比或删除。
              </p>
            </div>

          </div>

          <div className="space-y-3">
            <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.055)]">
              <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
                <label className="flex h-11 w-full min-w-0 items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white px-4 shadow-sm transition-all duration-200 hover:border-[var(--color-primary-light)] focus-within:border-[var(--color-primary)] focus-within:shadow-[0_0_0_3px_var(--color-primary-light)] xl:w-[38%] xl:min-w-[440px] xl:max-w-[600px]">
                  <Search className="h-4 w-4 shrink-0 text-[var(--color-text-hint)]" />
                  <input
                    type="text"
                    className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-hint)] focus:outline-none"
                    placeholder="搜索题干 / 科目 / 题目编号"
                    value={keywordInput}
                    onChange={(event) => handleKeywordChange(event.target.value)}
                  />
                  <div className="flex shrink-0 items-center gap-1">
                    {(searchDebouncing || (questions.isFetching && Boolean(filters.keyword))) ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text-hint)]" />
                    ) : null}
                    {keywordInput ? (
                      <button
                        type="button"
                        onClick={() => handleKeywordChange("")}
                        className="grid h-7 w-7 place-items-center rounded-lg text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                        aria-label="清空搜索"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                </label>

                <span
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-semibold text-[var(--ink)] shadow-sm"
                  aria-label="筛选条件"
                >
                  <Filter className="h-4 w-4 text-[var(--color-primary)]" />
                  筛选
                </span>

                <Button
                  variant="ghost"
                  onClick={handleResetFilters}
                  disabled={!hasActiveFilters}
                  className="h-11 shrink-0 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] shadow-sm hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)] disabled:opacity-45"
                >
                  <RotateCcw className="h-4 w-4" />
                  重置
                </Button>

                <div className="hidden h-7 w-px shrink-0 bg-[var(--color-border)] xl:block" />

                <div ref={commonFilterMenuRef} className="relative shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      setIsCommonFilterMenuOpen((open) => !open);
                      setIsMoreFilterOpen(false);
                      setIsExportMenuOpen(false);
                    }}
                    aria-expanded={isCommonFilterMenuOpen}
                    aria-haspopup="menu"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    常用筛选
                    <ChevronDown
                      className={`h-4 w-4 text-[var(--color-text-hint)] transition ${isCommonFilterMenuOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                  {isCommonFilterMenuOpen ? (
                    <div className="absolute left-0 top-full z-30 mt-2 min-w-[176px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({})}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        全部有效题目
                      </button>
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({ is_active: "true" })}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        仅看已启用
                      </button>
                      <button
                        type="button"
                        onClick={() => applyFilterPreset({ difficulty: "5" })}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        困难题目
                      </button>
                      <div className="my-1 border-t border-[var(--color-border)]" />
                      <button
                        type="button"
                        onClick={handleApplySavedFilters}
                        className="flex w-full rounded-xl px-3 py-2 text-left text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                      >
                        已保存筛选
                      </button>
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={handleSaveCurrentFilters}
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                >
                  <Star className="h-4 w-4 text-[var(--color-text-secondary)]" />
                  保存筛选
                </button>
              </div>
            </div>

            {filters.knowledge_point_id ? (
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-2 text-sm text-blue-800">
                <span className="font-semibold">覆盖率跳转筛选</span>
                <span>知识点 #{filters.knowledge_point_id}</span>
                <button type="button" className="rounded-lg px-2 py-1 text-xs font-semibold hover:bg-blue-100" onClick={() => updateFilter("knowledge_point_id", "")}>清除</button>
              </div>
            ) : null}

            <div className="rounded-[1.35rem] border border-[var(--color-border)] bg-white/90 px-5 py-3 shadow-[0_8px_24px_rgba(40,60,90,0.05)]">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.16fr_1fr_1fr_0.92fr_1fr_auto] xl:items-center">
                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    科目
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                      value={filters.subject_id}
                      onChange={(v) => updateFilter("subject_id", v)}
                      options={[
                        { label: "全部科目", value: "" },
                        ...subjectOptions.map((subject) => ({
                          label: subject.name,
                          value: String(subject.id),
                        })),
                      ]}
                    />
                  </div>
                </div>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    题型
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                      placeholder="全部题型"
                      value={filters.question_type}
                      onChange={(v) => updateFilter("question_type", v)}
                      options={QUESTION_TYPE_OPTIONS}
                    />
                  </div>
                </div>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    状态
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                      value={filters.is_active}
                      onChange={(v) => updateFilter("is_active", v)}
                      options={activeOptions}
                    />
                  </div>
                </div>

                <label className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-3 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    年份
                  </span>
                  <input
                    inputMode="numeric"
                    className="h-9 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm text-[var(--color-text-primary)] outline-none shadow-none placeholder:text-[var(--color-text-hint)] focus:border-0 focus:outline-none focus:ring-0"
                    placeholder="选择年份"
                    value={filters.year}
                    maxLength={4}
                    onChange={(event) =>
                      updateFilter(
                        "year",
                        event.target.value.replace(/\D/g, "").slice(0, 4),
                      )
                    }
                  />
                </label>

                <div className="flex h-11 min-w-0 items-center rounded-2xl border border-[var(--color-border)] bg-white px-3 shadow-sm">
                  <span className="mr-2 shrink-0 text-xs font-semibold text-[var(--color-text-secondary)]">
                    难度
                  </span>
                  <div className="min-w-0 flex-1">
                    <CustomSelect
                      className="h-9 rounded-xl !border-0 !bg-transparent pl-0 pr-1 shadow-none !ring-0 hover:!border-transparent"
                      value={filters.difficulty}
                      onChange={(v) => updateFilter("difficulty", v)}
                      options={difficultyOptions}
                    />
                  </div>
                </div>

                <div ref={moreFilterRef} className="relative justify-self-start xl:justify-self-end">
                  <button
                    type="button"
                    onClick={() => {
                      setIsMoreFilterOpen((open) => !open);
                      setIsCommonFilterMenuOpen(false);
                      setIsExportMenuOpen(false);
                    }}
                    aria-expanded={isMoreFilterOpen}
                    aria-haspopup="dialog"
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--ink)] shadow-sm transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
                  >
                    <SlidersHorizontal className="h-4 w-4 text-[var(--color-text-secondary)]" />
                    更多条件
                  </button>
                  {isMoreFilterOpen ? (
                    <div className="absolute right-0 top-full z-30 mt-2 w-[320px] animate-drop-in rounded-2xl border border-[var(--color-border)] bg-white p-4 shadow-[var(--shadow-floating)]">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        导入批次 ID
                      </p>
                      <Input
                        className="mt-2 h-10 rounded-xl border-[var(--color-border)] bg-white px-3"
                        placeholder="输入批次 ID 片段"
                        value={importBatchInput}
                        onChange={(event) =>
                          handleImportBatchChange(event.target.value)
                        }
                      />
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {message ? (
            <div className="fixed right-6 top-24 z-[60] animate-fade-in">
              <div
                role="status"
                aria-live="polite"
                className="flex max-w-sm items-center gap-3 rounded-full border border-[var(--color-success)]/30 bg-white/92 py-2 pl-5 pr-2 text-sm font-medium text-[var(--ink)] shadow-[var(--shadow-floating)] backdrop-blur-xl"
              >
                <span>{message}</span>
                <button
                  type="button"
                  onClick={() => setMessage(null)}
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[var(--color-text-hint)] transition hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]"
                  aria-label="关闭提示"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : null}

          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <section className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.25rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="inline-flex h-9 items-center gap-1.5 rounded-full bg-[var(--color-primary-light)] px-3 text-xs font-semibold text-[var(--color-primary-dark)]">
                <Layers className="h-3.5 w-3.5" />
                题目总览
              </span>
              <span className="inline-flex h-9 items-center rounded-full bg-[var(--porcelain)] px-3 text-xs font-semibold text-[var(--ink)]">
                当前页 {items.length} 题
              </span>
              {questions.isFetching && !questions.isLoading ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full px-2 text-xs font-medium text-[var(--color-text-hint)]">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  更新中
                </span>
              ) : null}
              {questions.data ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
                  共 {questions.data.total} 题
                </span>
              ) : null}
              {hasActiveFilters ? (
                <span className="inline-flex h-9 items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm font-medium text-[var(--color-text-secondary)]">
                  已启用筛选
                </span>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {selectedIds.size > 0 ? (
                <span className="inline-flex h-9 items-center rounded-full bg-[var(--color-primary-light)] px-4 text-sm font-semibold text-[var(--color-primary-dark)]">
                  已选 {selectedIds.size} 项
                </span>
              ) : null}
              <button
                type="button"
                role="checkbox"
                aria-checked={allChecked}
                onClick={toggleAll}
                className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white px-4 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary-light)] hover:bg-[var(--porcelain)]"
              >
                <span
                  aria-hidden="true"
                  className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors ${
                    allChecked
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                      : "border-[var(--color-border)] bg-white"
                  }`}
                >
                  {allChecked ? (
                    <Check className="h-3 w-3 text-white" strokeWidth={3} />
                  ) : null}
                </span>
                <span className="font-medium">选择当前页</span>
              </button>
              <div ref={exportMenuRef} className="relative">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setIsExportMenuOpen((value) => !value);
                    setIsCommonFilterMenuOpen(false);
                    setIsMoreFilterOpen(false);
                  }}
                  aria-expanded={isExportMenuOpen}
                  aria-haspopup="menu"
                  disabled={!!exportingFormat}
                  className="h-9 rounded-full px-3"
                >
                  <Download className="h-4 w-4" />
                  {exportingFormat
                    ? exportingFormat === "csv"
                      ? "导出 CSV 中..."
                      : "导出 Word 中..."
                    : "导出"}
                  <ChevronDown
                    className={`h-4 w-4 transition ${isExportMenuOpen ? "rotate-180" : ""}`}
                  />
                </Button>
                {isExportMenuOpen ? (
                  <div className="absolute right-0 top-full z-20 mt-2 min-w-[160px] animate-drop-in overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white p-1.5 shadow-[var(--shadow-floating)]">
                    <button
                      type="button"
                      onClick={() => void handleExport("csv")}
                      className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                    >
                      导出 CSV
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleExport("docx")}
                      className="flex w-full items-center rounded-xl px-3 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--porcelain)]"
                    >
                      导出 Word
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
              </div>

              <div className={`space-y-2.5 transition-opacity duration-200 ${questions.isFetching && !questions.isLoading ? "opacity-70" : "opacity-100"}`}>
              {questions.isLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }, (_, index) => (
                    <div
                      key={index}
                      className="h-28 animate-pulse rounded-[1.2rem] border border-[var(--color-border)] bg-white/60"
                    />
                  ))}
                </div>
              ) : null}

              <div
                key={`${filters.subject_id}-${filters.question_type}-${filters.is_active}-${filters.year}-${filters.difficulty}-${filters.keyword}-${filters.import_batch_id}-${filters.knowledge_point_id}-${page}-${pageSize}`}
                className="stagger-enter space-y-2.5"
              >
              {items.map((question) => {
                const stemText =
                  textForStemEditor(question.content) || `题目 #${question.id}`;
                const isSelected = selectedQuestionId === question.id;
                return (
                  <article
                    key={question.id}
                    onMouseEnter={() => prefetchDetail(question.id)}
                    className={`group rounded-[1.2rem] border transition-all duration-200 ${
                      isSelected
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]/30 shadow-sm ring-2 ring-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] bg-white/85 shadow-sm hover:border-[var(--color-primary)]/45 hover:bg-white hover:shadow-[var(--shadow-card)]"
                    }`}
                  >
                    <div className="flex items-start gap-3 px-4 py-3">
                      <CustomCheckbox
                        checked={selectedIds.has(question.id)}
                        onChange={() => toggleOne(question.id)}
                        className="mt-1"
                      />

                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => selectQuestion(question.id)}
                          className="w-full text-left"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="inline-flex items-center rounded-full bg-[var(--color-primary-light)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-primary-dark)]">
                              #{String(question.id).padStart(4, "0")}
                            </span>
                            <TypeBadge type={question.question_type} />
                            <DifficultyBadge difficulty={question.difficulty} />
                            <span
                              className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                                question.is_active
                                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                                  : "border-slate-200 bg-slate-50 text-slate-500"
                              }`}
                            >
                              {question.is_active ? "已启用" : "已停用"}
                            </span>
                          </div>

                          <div className="mt-2 line-clamp-2 text-sm font-medium leading-6 text-[var(--ink)]">
                            {looksLikeProgrammingCode(stemText) ? stemText : <MathFormula text={stemText} />}
                          </div>

                          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--color-text-hint)]">
                            {question.subject_name || question.subject_code ? (
                              <span className="inline-flex items-center gap-1">
                                <BookOpen className="h-3 w-3" />
                                {question.subject_name || question.subject_code}
                              </span>
                            ) : null}
                            {question.year ? (
                              <span className="inline-flex items-center gap-1">
                                <Tag className="h-3 w-3" />
                                {question.year} 年
                              </span>
                            ) : null}
                            {question.updated_at ? (
                              <span className="inline-flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                更新于 {question.updated_at.slice(0, 16).replace("T", " ")}
                              </span>
                            ) : null}
                          </div>
                        </button>
                      </div>

                      <Button
                        variant="ghost"
                        onClick={() => openDetail(question.id)}
                        className="mt-1 h-9 rounded-full px-3 text-xs text-[var(--color-text-secondary)] transition-all duration-200 group-hover:bg-[var(--porcelain)] group-hover:text-[var(--ink)]"
                      >
                        详情
                      </Button>
                    </div>
                  </article>
                );
              })}
              </div>

              {!questions.isLoading && !questions.isError && items.length === 0 ? (
                <div className="flex flex-col items-center gap-3 rounded-[1.6rem] border border-dashed border-[var(--color-border)] bg-white/60 py-16 text-center animate-fade-in">
                  <FileQuestion className="h-12 w-12 text-[var(--color-text-hint)]" />
                  <p className="text-sm font-semibold text-[var(--color-text-secondary)]">
                    暂无匹配题目
                  </p>
                  <p className="text-xs text-[var(--color-text-hint)]">
                    尝试调整搜索关键词或筛选条件
                  </p>
                  {hasActiveFilters ? (
                    <Button variant="secondary" size="sm" onClick={handleResetFilters}>
                      清除筛选
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {questions.isError ? (
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-red-200 bg-red-50/45 py-12 text-center animate-fade-in">
                  <AlertCircle className="h-9 w-9 text-red-400" />
                  <div>
                    <p className="text-sm font-semibold text-red-700">题目加载失败</p>
                    <p className="mt-1 text-xs text-red-500">请检查查询条件或后端服务后重试</p>
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => questions.refetch()}>
                    重新加载
                  </Button>
                </div>
              ) : null}
              </div>

              {questions.data && questions.data.total_pages > 1 ? (
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-[1.2rem] border border-[var(--color-border)] bg-white px-3 py-2.5 shadow-sm">
              <div className="flex flex-wrap items-center gap-3 text-sm text-[var(--color-text-secondary)]">
                <span>
                  共 <span className="font-semibold text-[var(--ink)]">{questions.data.total}</span> 条
                </span>
                <span>
                  第 <span className="font-semibold text-[var(--ink)]">{questions.data.page}</span> / {questions.data.total_pages} 页
                </span>
                <CustomSelect
                  className="h-10 min-w-[116px] rounded-full border-[var(--color-border)] bg-white px-3"
                  value={String(pageSize)}
                  onChange={handlePageSizeChange}
                  options={pageSizeOptions}
                  clearable={false}
                />
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  disabled={page <= 1 || questions.isFetching}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  上一页
                </button>
                {Array.from(
                  { length: Math.min(questions.data.total_pages, 5) },
                  (_, i) => {
                    const startPage = Math.max(
                      1,
                      Math.min(page - 2, questions.data.total_pages - 4),
                    );
                    const p = startPage + i;
                    if (p > questions.data.total_pages) return null;
                    const isActive = p === page;
                    return (
                      <button
                        key={p}
                        disabled={isActive || questions.isFetching}
                        onClick={() => setPage(p)}
                        className={
                          isActive
                            ? "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-sm font-bold text-white shadow-sm"
                            : "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white text-sm font-medium text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                        }
                      >
                        {p}
                      </button>
                    );
                  },
                )}
                <button
                  disabled={page >= (questions.data?.total_pages ?? 1) || questions.isFetching}
                  onClick={() => setPage((p) => p + 1)}
                  className="inline-flex h-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-white px-3 text-xs font-semibold text-[var(--color-text-secondary)] shadow-sm transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] disabled:pointer-events-none disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>
              ) : null}
            </section>

            <aside className="hidden xl:block xl:min-h-0 xl:self-stretch">
              <div className="xl:sticky xl:top-0 xl:h-dvh xl:min-h-0 xl:overflow-hidden">
              <div className="flex h-full min-h-0 flex-col overflow-hidden border-l border-slate-200 bg-white p-5">
                {selectedQuestionId === null ? (
                  <div className="flex min-h-0 flex-1 flex-col items-center justify-center text-center animate-fade-in">
                    <div className="flex h-16 w-16 items-center justify-center rounded-3xl border border-[var(--color-border)] bg-[var(--porcelain)] text-[var(--color-text-hint)] shadow-sm">
                      <FileQuestion className="h-8 w-8" />
                    </div>
                    <p className="mt-5 text-2xl font-bold text-[var(--ink)]">
                      选择一道题目
                    </p>
                    <p className="mt-2 max-w-xs text-sm leading-6 text-[var(--color-text-secondary)]">
                      在左侧列表中选择题目，查看详情、编辑内容或进行版本对比。
                    </p>
                  </div>
                ) : selectedQuestion ? (
                  <div
                    ref={detailScrollRef}
                    key={selectedQuestion.id}
                    className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1 animate-fade-in [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                  >
                    <div className="sticky top-0 z-10 -mx-1 flex items-start justify-between gap-4 border-b border-slate-200 bg-white/96 px-1 pb-4 pt-0.5 backdrop-blur supports-[backdrop-filter]:bg-white/88">
                      <div className="min-w-0">
                        <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">
                          Question
                        </p>
                        <h3 className="mt-2 text-2xl font-bold text-[var(--ink)]">
                          题目 #{selectedQuestion.id}
                        </h3>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <TypeBadge type={selectedQuestion.question_type} />
                          <DifficultyBadge difficulty={selectedQuestion.difficulty} />
                        </div>
                      </div>
                      <Button
                        variant="secondary"
                        onClick={() => setIsDetailDrawerOpen(true)}
                        className="shrink-0 rounded-lg border-slate-200 bg-white shadow-none transition hover:bg-slate-50"
                      >
                        <FileQuestion className="h-4 w-4" />
                        完整详情
                      </Button>
                    </div>

                    <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-4">
                      <p className="mb-3 flex items-center justify-between gap-3 font-semibold text-[var(--ink)]">
                        <span>题干</span>
                        <span className="font-mono text-[11px] font-normal text-[var(--color-text-hint)]">
                          #{selectedQuestion.id}
                        </span>
                      </p>
                      <div className="whitespace-pre-wrap text-base leading-8 text-[var(--ink)]">
                        <QuestionContentRenderer
                          content={selectedQuestion.content}
                          fallbackText={textFromContent(selectedQuestion.content)}
                          preserveCodeText
                        />
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-[var(--ink)]">选项</p>
                      <div className="mt-3">
                        {isMultiBlankChoice(selectedQuestion.question_type) ? (
                          <MultiBlankQuestionOptions
                            groups={resolveQuestionBlankOptionGroups(selectedQuestion)}
                          />
                        ) : (
                          <QuestionOptions
                            options={normalizeQuestionOptions(resolveQuestionOptions(selectedQuestion))}
                          />
                        )}
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-slate-950">答案</p>
                      <div className="mt-2 inline-flex min-h-9 items-center rounded-md bg-slate-50 px-2.5 py-1.5 text-sm font-semibold leading-6 text-slate-800">
                        <QuestionAnswerDisplay
                          questionType={selectedQuestion.question_type}
                          answer={selectedQuestion.answer}
                        />
                      </div>
                    </section>

                    <section className="rounded-xl border border-slate-200 bg-white p-4">
                      <p className="font-semibold text-slate-950">解析</p>
                      <div className="mt-3">
                        <QuestionAnalysis value={selectedQuestion.analysis} compact />
                      </div>
                    </section>

                    {renderSecondaryQuestionInfo(selectedQuestion)}

                    <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
                      {canWrite ? (
                        <Button
                          variant="secondary"
                          onClick={() => {
                            startEditing();
                            setIsDetailDrawerOpen(true);
                          }}
                        >
                          <Pencil className="h-4 w-4" />
                          编辑
                        </Button>
                      ) : null}
                      {canDelete ? (
                        <Button
                          variant="danger"
                          onClick={() =>
                            setConfirmState({
                              action: "delete",
                              id: selectedQuestion.id,
                            })
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                          删除
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ) : detail.isError && selectedQuestionId !== null ? (
                  <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center animate-fade-in">
                    <AlertCircle className="h-9 w-9 text-red-400" />
                    <p className="text-sm font-semibold text-red-700">详情加载失败</p>
                    <Button variant="secondary" size="sm" onClick={() => detail.refetch()}>重新加载</Button>
                  </div>
                ) : (
                  <div className="min-h-0 flex-1 space-y-3 animate-fade-in">
                    <div className="h-16 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/75" />
                    <div className="h-28 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
                    <div className="h-44 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/50" />
                  </div>
                )}
              </div>
              </div>
            </aside>
          </div>
        </CardContent>
      </Card>

      {selectedIds.size > 0 ? (
        <div className="fixed bottom-8 left-1/2 z-30 -translate-x-1/2 animate-drop-in">
          <div className="flex items-center gap-3 rounded-full border border-[var(--color-border)] bg-white/94 py-2 pl-4 pr-2 shadow-[var(--shadow-floating)] backdrop-blur-xl">
            <span className="text-sm text-[var(--color-text-secondary)]">
              已选 <strong className="text-[var(--ink)]">{selectedIds.size}</strong> 项
            </span>
            <span className="h-5 w-px bg-[var(--color-border)]" />
            {canDelete ? (
              <Button
                variant="danger"
                size="sm"
                disabled={deleteMutation.isPending}
                onClick={() => setConfirmState({ action: "batch-delete" })}
              >
                <Trash2 className="h-3.5 w-3.5" />
                批量删除
              </Button>
            ) : null}
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="grid h-8 w-8 place-items-center rounded-full text-[var(--color-text-hint)] transition-colors hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary)]"
              aria-label="清除选择"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}

      {/* Detail drawer */}
      {isDetailDrawerOpen && selectedQuestionId !== null ? (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-slate-950/25 backdrop-blur-[1px] animate-fade-in"
          onClick={closeDetailDrawer}
        >
          <aside
            role="dialog"
            aria-modal="true"
            aria-label={editing ? "编辑题目" : "题目详情"}
            className="question-detail-drawer h-full w-full max-w-[880px] overflow-y-auto overscroll-contain border-l border-slate-200/80 bg-white shadow-[-18px_0_52px_rgba(15,23,42,0.12)] animate-drop-in"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="sticky top-0 z-20 flex min-h-16 items-center justify-between gap-4 border-b border-slate-200/80 bg-white/95 px-7 py-3 backdrop-blur-xl">
              <div className="flex min-w-0 items-center gap-3">
                {editing ? (
                  <button
                    type="button"
                    onClick={cancelEditing}
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
                    aria-label="返回题目详情"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </button>
                ) : null}
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5">
                    <h3 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-slate-950">
                      {editing ? "编辑题目" : "题目详情"}
                    </h3>
                    {editing && dirty ? (
                      <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">未保存</span>
                    ) : null}
                    {!editing ? (
                      <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-500">
                        #{selectedQuestionId}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {editing ? "修改题目内容、知识点与解析模块" : "查看题目内容与结构化解析信息"}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {!editing && canWrite ? (
                  <Button variant="secondary" size="sm" onClick={startEditing} className="border-slate-200 bg-white shadow-none">
                    <Pencil className="h-3.5 w-3.5" />
                    编辑
                  </Button>
                ) : null}
                {!editing && canDelete ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-slate-500 hover:bg-red-50 hover:text-red-600"
                    onClick={() =>
                      setConfirmState({
                        action: "delete",
                        id: selectedQuestionId,
                      })
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                ) : null}
                <button
                  type="button"
                  onClick={closeDetailDrawer}
                  className="grid h-9 w-9 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-900"
                  aria-label="关闭题目详情"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </header>

            {selectedQuestion ? (
              editing ? (
                /* ===== Edit form ===== */
                <div className="question-drawer-edit px-7 pb-24 pt-1">
                  <section className="border-b border-slate-200 py-5">
                    <div className="grid gap-x-4 gap-y-3 md:grid-cols-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        科目
                      </p>
                      <CustomSelect
                        value={String(editForm.subject_id ?? "")}
                        onChange={(v) => setEditForm({ ...editForm, subject_id: v ? Number(v) : null })}
                        options={subjectOptions.map((s) => ({ label: s.name, value: String(s.id) }))}
                        placeholder="选择科目"
                        clearable={false}
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        题型
                      </p>
                      <CustomSelect
                        value={editForm.question_type ?? ""}
                        onChange={(v) =>
                          setEditForm({
                            ...editForm,
                            question_type: v,
                          })
                        }
                        options={canonicalizeQuestionType(editForm.question_type) || !editForm.question_type
                          ? QUESTION_TYPE_OPTIONS
                          : [...QUESTION_TYPE_OPTIONS, { value: editForm.question_type!, label: formatUnknownType(editForm.question_type!), disabled: true }]
                        }
                        clearable={false}
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        难度
                      </p>
                      <CustomSelect
                        value={String(editForm.difficulty ?? 3)}
                        onChange={(v) => setEditForm({ ...editForm, difficulty: Number(v) })}
                        options={["简单", "较易", "中等", "较难", "困难"].map((label, index) => ({ label, value: String(index + 1) }))}
                        clearable={false}
                        className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
                      />
                    </div>
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-5">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-950">题干</p>
                        <p className="mt-1 text-[11px] text-slate-400">编辑题目正文、代码块与题干图片</p>
                      </div>
                    </div>
                    <textarea
                      wrap="soft"
                      spellCheck={false}
                      className="min-h-36 w-full resize-y overflow-x-hidden whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3 text-sm leading-7 text-slate-800 outline-none transition [overflow-wrap:anywhere] placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
                      value={editStemText}
                      onChange={(e) => setEditStemText(e.target.value)}
                    />
                    <div className="mt-4">
                      <p className="mb-2 text-xs font-medium text-slate-500">题干图片</p>
                    {editingSegments.some(isPlainImageSegment) ||
                    editingFallbackStemImageUrls.length > 0 ? (
                      /* 已有图：大图直接占据插入区，hover 替换/删除；无插入按钮 */
                      <div className="space-y-3">
                        {editingSegments.map((seg, index) =>
                          isPlainImageSegment(seg) ? (
                            <div key={index} className="w-full max-w-xl">
                              <QuestionImageField
                                questionId={selectedQuestionId!}
                                target="stem"
                                valueUrl={typeof seg.url === "string" ? seg.url : null}
                                canDelete
                                dirty={dirty}
                                beforeDirtyMutation={prepareImmediateQuestionMutation}
                                addLabel="更换图片"
                                onMutated={handleQuestionMutated}
                              />
                            </div>
                          ) : null,
                        )}
                        {editingFallbackStemImageUrls.map((url, index) => (
                          <div key={`legacy-${url}-${index}`} className="w-full max-w-xl">
                            <QuestionImageField
                              questionId={selectedQuestionId!}
                              target="stem"
                              valueUrl={url}
                              canDelete
                              dirty={dirty}
                              beforeDirtyMutation={prepareImmediateQuestionMutation}
                              addLabel="更换图片"
                              onMutated={handleQuestionMutated}
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <QuestionImageField
                        questionId={selectedQuestionId!}
                        target="stem"
                        dirty={dirty}
                        beforeDirtyMutation={prepareImmediateQuestionMutation}
                        addLabel="插入题干图片"
                        onMutated={handleQuestionMutated}
                      />
                    )}
                    </div>
                  </section>

                  {editingSegments.some((segment) => isTableSegment(segment)) ? (
                    <div className="space-y-4">
                      {editingSegments.map((segment, segmentIndex) => {
                        const table = normalizeStructuredTableSegment(segment);
                        if (!table) return null;
                        return (
                          <StructuredTableEditor
                            key={table.table_id || segmentIndex}
                            segment={table}
                            onChange={(nextTable) => {
                              const next = [...editingSegments];
                              next[segmentIndex] = nextTable;
                              replaceEditingSegments(next);
                            }}
                            onDelete={() => {
                              replaceEditingSegments(
                                editingSegments.filter((_, index) => index !== segmentIndex),
                              );
                            }}
                          />
                        );
                      })}
                    </div>
                  ) : null}

                  <section className="border-b border-slate-200 py-5">
                    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-950">代码块</p>
                        <p className="mt-1 text-[11px] text-slate-400">
                          可手动插入代码内容；只有显式 caption 才作为可见标题，segment.alt 仅保留为辅助描述。
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-[11px] tabular-nums text-slate-400">
                          {editingSegments.filter(isCodeSegment).length} 个代码块
                        </span>
                        <Button
                          type="button"
                          variant="secondary"
                          className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
                          onClick={addEditingCodeSegment}
                        >
                          <Plus className="h-3.5 w-3.5" />
                          添加代码块
                        </Button>
                      </div>
                    </div>

                    {editingSegments.some(isCodeSegment) ? (
                      <div className="space-y-4">
                        {editingSegments.map((segment, segmentIndex) => {
                          if (!isCodeSegment(segment)) return null;
                          const caption = String(segment.caption ?? "");
                          const language = String(segment.language ?? "");
                          const code = codeSegmentText(segment);
                          return (
                            <div
                              key={String(segment.region_id ?? `code-${segmentIndex}`)}
                              className={`overflow-hidden rounded-xl border bg-slate-50/50 ${
                                comparableText(code) ? "border-slate-200" : "border-amber-300"
                              }`}
                            >
                              <div className="grid gap-3 border-b border-slate-200 bg-white px-4 py-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
                                <label className="space-y-1">
                                  <span className="text-[11px] font-medium text-slate-500">显示标题（可选）</span>
                                  <input
                                    className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50/60 px-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
                                    value={caption}
                                    placeholder="留空则不在题干中显示标题"
                                    onChange={(e) => {
                                      const next = [...editingSegments];
                                      const nextSegment: Record<string, unknown> = {
                                        ...segment,
                                      };
                                      const nextCaption = e.target.value;
                                      if (nextCaption) nextSegment.caption = nextCaption;
                                      else delete nextSegment.caption;
                                      next[segmentIndex] = nextSegment;
                                      replaceEditingSegments(next);
                                    }}
                                  />
                                </label>
                                <label className="space-y-1">
                                  <span className="text-[11px] font-medium text-slate-500">语言（可选）</span>
                                  <input
                                    className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50/60 px-3 font-mono text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
                                    value={language}
                                    placeholder="assembly / c / cpp"
                                    onChange={(e) => {
                                      const next = [...editingSegments];
                                      const nextSegment: Record<string, unknown> = { ...segment };
                                      const nextLanguage = e.target.value;
                                      if (nextLanguage) nextSegment.language = nextLanguage;
                                      else delete nextSegment.language;
                                      next[segmentIndex] = nextSegment;
                                      replaceEditingSegments(next);
                                    }}
                                  />
                                </label>
                                <div className="flex items-end">
                                  <Button
                                    type="button"
                                    variant="secondary"
                                    className="h-9 border-red-100 bg-white px-3 text-xs text-red-600 shadow-none hover:border-red-200 hover:bg-red-50"
                                    onClick={() => {
                                      replaceEditingSegments(
                                        editingSegments.filter((_, index) => index !== segmentIndex),
                                      );
                                    }}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                    删除
                                  </Button>
                                </div>
                              </div>
                              <textarea
                                wrap="off"
                                spellCheck={false}
                                className="min-h-48 w-full resize-y overflow-auto whitespace-pre border-0 bg-slate-950 px-4 py-4 font-mono text-[13px] leading-6 text-slate-100 outline-none [tab-size:2]"
                                value={code}
                                placeholder="在这里输入代码内容……"
                                onChange={(e) => {
                                  const next = [...editingSegments];
                                  const nextSegment: Record<string, unknown> = {
                                    ...segment,
                                    code: e.target.value,
                                  };
                                  // `code` is the canonical field for textual code segments.
                                  // Remove a legacy duplicate `text` field so future reads cannot
                                  // accidentally prefer stale code from another property.
                                  if (Object.prototype.hasOwnProperty.call(nextSegment, "text")) {
                                    delete nextSegment.text;
                                  }
                                  next[segmentIndex] = nextSegment;
                                  replaceEditingSegments(next);
                                }}
                              />
                              {!comparableText(code) ? (
                                <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-[11px] text-amber-800">
                                  代码正文不能为空。输入内容后即可保存，或删除该空代码块。
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={addEditingCodeSegment}
                        className="flex min-h-24 w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/40 px-4 text-sm text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
                      >
                        <span className="flex items-center gap-2">
                          <Plus className="h-4 w-4" />
                          插入代码块
                        </span>
                      </button>
                    )}
                  </section>

                  {/* Options inline editor */}
                  {(() => {
                    const qtype = canonicalizeQuestionType(editForm.question_type ?? "");

                    if (qtype === "multi_blank_choice" || qtype === "multi_blank_multiple_choice") {
                      const groups = normalizeBlankOptionGroups(
                        resolveBlankOptionGroupsValue(editForm.content),
                      );
                      const totalOptions = groups.reduce(
                        (sum, group) => sum + group.options.length,
                        0,
                      );
                      const inferredBlankIds = extractBlankSlotIds(editStemText);
                      const canAddSharedOption =
                        groups.length > 0 || inferredBlankIds.length > 0;
                      const addSharedOption = () => {
                        setEditForm((current) => {
                          const currentContent = contentRecord(current.content);
                          const field = blankOptionGroupsStorageField(currentContent);
                          const rawGroups = resolveBlankOptionGroupsValue(currentContent);
                          return {
                            ...current,
                            content: {
                              ...currentContent,
                              [field]: addBlankOptionToAllGroups(
                                rawGroups,
                                extractBlankSlotIds(editStemText),
                              ),
                            },
                          };
                        });
                      };

                      return (
                        <section className="border-b border-slate-200 py-5">
                          <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
                            <div>
                              <p className="text-sm font-semibold text-slate-950">选项</p>
                              <p className="mt-1 text-[11px] text-slate-400">
                                按空位编辑分组选项；顶部按钮会向所有空位添加同一字母选项
                              </p>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="text-[11px] tabular-nums text-slate-400">
                                {groups.length} 个空位 · {totalOptions} 个选项
                              </span>
                              <Button
                                type="button"
                                size="sm"
                                variant="secondary"
                                className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
                                disabled={!canAddSharedOption || groups.some((group) => group.options.length >= 26)}
                                onClick={addSharedOption}
                              >
                                <Plus className="h-3.5 w-3.5" />
                                添加选项
                              </Button>
                            </div>
                          </div>

                          {groups.length === 0 ? (
                            <div className="mb-3 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-4 text-sm text-[var(--color-text-hint)]">
                              {inferredBlankIds.length > 0
                                ? `已从题干识别 ${inferredBlankIds.length} 个空位，点击“添加选项”创建分组选项。`
                                : "未从题干识别到空位标记，请先使用（ ）、① 或 ___ 标记空位。"}
                            </div>
                          ) : (
                            <div className="space-y-3">
                              {groups.map((group) => (
                                <div
                                  key={group.id}
                                  className="overflow-hidden rounded-lg border border-slate-200 bg-white"
                                >
                                  <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-3 py-2">
                                    <div className="flex items-center gap-2">
                                      <span className="flex h-7 min-w-7 items-center justify-center rounded-md bg-slate-900 px-1.5 text-[11px] font-semibold text-white">
                                        {group.id}
                                      </span>
                                      <span className="text-xs font-medium text-slate-600">该空选项</span>
                                    </div>
                                    <span className="text-[10px] text-slate-400">
                                      {group.options.length} 项
                                    </span>
                                  </div>
                                  {group.options.map((opt) => (
                                    <div
                                      key={`${group.id}-${opt.key}`}
                                      className="flex items-center gap-3 border-b border-slate-100 px-3 py-2.5"
                                    >
                                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[11px] font-semibold text-slate-600">
                                        {opt.key}
                                      </span>
                                      <input
                                        className="h-9 min-w-0 flex-1 border-0 bg-transparent px-1 text-sm text-slate-800 outline-none placeholder:text-slate-300 focus:ring-0"
                                        value={opt.text ?? ""}
                                        placeholder="请输入选项内容"
                                        onChange={(e) => {
                                          const nextText = e.target.value;
                                          setEditForm((current) => {
                                            const currentContent = contentRecord(current.content);
                                            const field = blankOptionGroupsStorageField(currentContent);
                                            const rawGroups = resolveBlankOptionGroupsValue(currentContent);
                                            return {
                                              ...current,
                                              content: {
                                                ...currentContent,
                                                [field]: updateBlankOptionGroupText(
                                                  rawGroups,
                                                  group.id,
                                                  opt.key,
                                                  nextText,
                                                ),
                                              },
                                            };
                                          });
                                        }}
                                      />
                                    </div>
                                  ))}
                                  <div className="flex items-center justify-between gap-3 bg-slate-50/40 px-3 py-2.5">
                                    <span className="text-[10px] text-slate-400">
                                      自动使用下一个可用字母
                                    </span>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="secondary"
                                      className="h-8 border-slate-200 bg-white px-3 text-xs shadow-none"
                                      disabled={group.options.length >= 26}
                                      onClick={() => {
                                        setEditForm((current) => {
                                          const currentContent = contentRecord(current.content);
                                          const field = blankOptionGroupsStorageField(currentContent);
                                          const rawGroups = resolveBlankOptionGroupsValue(currentContent);
                                          return {
                                            ...current,
                                            content: {
                                              ...currentContent,
                                              [field]: addBlankOptionToGroup(rawGroups, group.id),
                                            },
                                          };
                                        });
                                      }}
                                    >
                                      <Plus className="h-3.5 w-3.5" />
                                      添加选项
                                    </Button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </section>
                      );
                    }

                    const optList = optionsToKeyValueList(editForm.options);
                    const isChoiceType = qtype === "single_choice" || qtype === "multiple_choice";
                    return (
                      <section className="border-b border-slate-200 py-5">
                        <div className="mb-4 flex items-end justify-between gap-4">
                          <div>
                            <p className="text-sm font-semibold text-slate-950">选项</p>
                            <p className="mt-1 text-[11px] text-slate-400">逐项编辑文字或补充选项图片</p>
                          </div>
                          <span className="text-[11px] tabular-nums text-slate-400">{optList.length} 个选项</span>
                        </div>
                        {optList.length === 0 ? (
                          <p className="mb-3 text-sm text-[var(--color-text-hint)]">
                            暂无可编辑选项
                          </p>
                        ) : (
                          <div className="mb-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
                            {optList.map((opt, index) => {
                              const imgUrl = optionImageUrl(editForm.options, opt.key);
                              return (
                                <div key={index} className="flex items-center gap-3 border-b border-slate-100 px-3 py-2.5 last:border-b-0">
                                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[11px] font-semibold text-slate-600">
                                    {opt.key}
                                  </span>
                                  <input
                                    className="h-9 min-w-0 flex-1 border-0 bg-transparent px-1 text-sm text-slate-800 outline-none placeholder:text-slate-300 focus:ring-0"
                                    value={opt.text}
                                    onChange={(e) => {
                                      const currentOptions = (editForm.options ?? {}) as Record<string, unknown>;
                                      const storageKey = optionStorageKey(editForm.options, opt.key);
                                      const prevValue = currentOptions[storageKey];
                                      const nextValue =
                                        prevValue && typeof prevValue === "object" && !Array.isArray(prevValue)
                                          ? { ...(prevValue as Record<string, unknown>), text: e.target.value }
                                          : e.target.value;
                                      setEditForm({
                                        ...editForm,
                                        options: { ...currentOptions, [storageKey]: nextValue },
                                      });
                                    }}
                                  />
                                  <QuestionImageField
                                    questionId={selectedQuestionId!}
                                    target={`option:${opt.key}`}
                                    valueUrl={imgUrl}
                                    canDelete={!!imgUrl}
                                    addLabel="上传图片"
                                    dirty={dirty}
                                    beforeDirtyMutation={prepareImmediateQuestionMutation}
                                    variant="row"
                                    onMutated={handleQuestionMutated}
                                  />
                                </div>
                              );
                            })}
                          </div>
                        )}
                        <QuickAddOptions
                          questionId={selectedQuestionId!}
                          existingKeys={optList.map((o) => o.key)}
                          disabled={!isChoiceType}
                          dirty={dirty}
                          beforeDirtyMutation={prepareImmediateQuestionMutation}
                          onMutated={handleQuestionMutated}
                        />
                      </section>
                    );
                  })()}

                  {/* Answer editor */}
                  {isMultiBlankChoice(editForm.question_type ?? "") ? (
                    (() => {
                      const groups = normalizeBlankOptionGroups(
                        resolveBlankOptionGroupsValue(editForm.content),
                      );
                      const multiSelect = isMultiBlankMultipleChoice(
                        editForm.question_type ?? "",
                      );
                      const parsedAnswer = parseMultiBlankChoiceAnswer(editForm.answer);
                      const parsedAnswerMap = new Map(
                        parsedAnswer.map((item) => [item.blankId, item.optionKey]),
                      );
                      const blankIds =
                        groups.length > 0
                          ? groups.map((group) => group.id)
                          : parsedAnswer.map((item) => item.blankId);

                      return (
                        <section className="border-b border-slate-200 py-5">
                          <div className="mb-4">
                            <p className="text-sm font-semibold text-slate-950">答案</p>
                            <p className="mt-1 text-[11px] text-slate-400">
                              {multiSelect
                                ? "按空位分别编辑答案；每空可填写多个选项字母，以逗号分隔（如 A,C）"
                                : "按空位分别编辑答案；保存时自动写回多空答案格式"}
                            </p>
                          </div>

                          {blankIds.length > 0 ? (
                            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                              {blankIds.map((blankId, index) => {
                                const group = groups.find((g) => g.id === blankId);
                                const currentLetters = (parsedAnswerMap.get(blankId) ?? "")
                                  .split(",")
                                  .map((l) => l.trim().toUpperCase())
                                  .filter(Boolean);
                                return (
                                <div
                                  key={`${blankId}-${index}`}
                                  className="flex items-center gap-4 border-b border-slate-100 px-4 py-3 last:border-b-0"
                                >
                                  <span className="w-8 shrink-0 text-sm font-medium text-slate-900">
                                    {blankId}
                                  </span>
                                  {multiSelect && group && group.options.length > 0 ? (
                                    <div className="flex flex-wrap items-center gap-1.5">
                                      {group.options.map((opt) => {
                                        const selected = currentLetters.includes(
                                          opt.key.trim().toUpperCase(),
                                        );
                                        return (
                                          <button
                                            key={opt.key}
                                            type="button"
                                            className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                                              selected
                                                ? "border-slate-900 bg-slate-900 text-white"
                                                : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
                                            }`}
                                            onClick={() =>
                                              setEditForm({
                                                ...editForm,
                                                answer: updateMultiBlankChoiceAnswer(
                                                  editForm.answer,
                                                  blankIds,
                                                  blankId,
                                                  opt.key.trim().toUpperCase(),
                                                  true,
                                                ),
                                              })
                                            }
                                          >
                                            {opt.key}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  ) : (
                                    <Input
                                      value={parsedAnswerMap.get(blankId) ?? ""}
                                      aria-label={`${blankId} 答案`}
                                      className="h-9 max-w-32 border-slate-200 bg-slate-50/60 text-center shadow-none focus:bg-white"
                                      onChange={(e) =>
                                        setEditForm({
                                          ...editForm,
                                          answer: updateMultiBlankChoiceAnswer(
                                            editForm.answer,
                                            blankIds,
                                            blankId,
                                            e.target.value,
                                          ),
                                        })
                                      }
                                    />
                                  )}
                                </div>
                                );
                              })}
                            </div>
                          ) : (
                            <Input
                              value={editForm.answer ?? ""}
                              className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                              onChange={(e) =>
                                setEditForm({ ...editForm, answer: e.target.value })
                              }
                            />
                          )}
                        </section>
                      );
                    })()
                  ) : optionsToKeyValueList(editForm.options).length > 0 ? (
                    <section className="border-b border-slate-200 py-5">
                      <div className="mb-4">
                        <p className="text-sm font-semibold text-slate-950">答案</p>
                        <p className="mt-1 text-[11px] text-slate-400">快速选择正确选项，也可直接编辑答案内容</p>
                      </div>
                      <p className="mb-2 text-[11px] font-medium text-slate-500">快速选择</p>
                      {editForm.question_type &&
                      isMultiChoice(editForm.question_type) ? (
                        <p className="mb-2 text-[10px] text-[var(--color-text-hint)]">
                          多选：单击切换各选项，以逗号分隔
                        </p>
                      ) : null}
                      <div className="mb-3 flex flex-wrap gap-2">
                        {optionsToKeyValueList(editForm.options).map((opt) => {
                          const normalizedKey = opt.key.trim().toUpperCase();
                          const selected = isMultiChoice(
                            editForm.question_type ?? "",
                          )
                            ? normalizedChoiceAnswerKeys(editForm.answer).includes(normalizedKey)
                            : String(editForm.answer ?? "").trim().toUpperCase() === normalizedKey;
                          return (
                            <button
                              key={opt.key}
                              type="button"
                              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md border px-3 text-sm font-medium transition ${
                                selected
                                  ? "border-slate-900 bg-slate-900 text-white"
                                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-900"
                              }`}
                              onClick={() => {
                                if (
                                  isMultiChoice(editForm.question_type ?? "")
                                ) {
                                  const keys = normalizedChoiceAnswerKeys(editForm.answer);
                                  const next = keys.includes(normalizedKey)
                                    ? keys.filter((key) => key !== normalizedKey)
                                    : [...keys, normalizedKey];
                                  setEditForm({
                                    ...editForm,
                                    answer: next.join(","),
                                  });
                                } else {
                                  setEditForm({
                                    ...editForm,
                                    answer: selected ? "" : normalizedKey,
                                  });
                                }
                              }}
                            >
                              {opt.key}
                            </button>
                          );
                        })}
                      </div>
                      <div className="mt-4 space-y-1.5">
                        <p className="text-[11px] font-medium text-slate-500">答案内容</p>
                        <Input
                          value={editForm.answer ?? ""}
                          className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                          onChange={(e) =>
                            setEditForm({ ...editForm, answer: e.target.value })
                          }
                        />
                      </div>
                    </section>
                  ) : (
                    <section className="border-b border-slate-200 py-5">
                      <p className="mb-3 text-sm font-semibold text-slate-950">答案</p>
                      <div>
                        <Input
                          value={editForm.answer ?? ""}
                          className="border-slate-200 bg-slate-50/60 shadow-none focus:bg-white"
                          onChange={(e) =>
                            setEditForm({ ...editForm, answer: e.target.value })
                          }
                        />
                      </div>
                    </section>
                  )}

                  <QuestionKnowledgePointsEditor
                    value={editForm.knowledge_points ?? []}
                    onChange={(knowledgePoints) =>
                      setEditForm((current) => ({
                        ...current,
                        knowledge_points: knowledgePoints,
                      }))
                    }
                  />

                  <QuestionAnalysisEditor
                    value={editForm.analysis ?? ""}
                    onChange={(analysis) =>
                      setEditForm((current) => ({ ...current, analysis }))
                    }
                  />

                  {unresolvedEditingTableCount > 0 ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      仍有 {unresolvedEditingTableCount} 个结构化表格需要人工核验。请检查单元格和合并关系，并点击“标记人工已核验”后再保存。
                    </div>
                  ) : null}
                  {emptyEditingCodeCount > 0 ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      仍有 {emptyEditingCodeCount} 个代码块正文为空。请输入代码内容，或删除空代码块后再保存。
                    </div>
                  ) : null}

                  <div className="sticky bottom-0 z-10 -mx-7 -mb-24 mt-8 flex justify-end gap-2 border-t border-slate-200 bg-white/96 px-7 py-4 shadow-[0_-12px_30px_rgba(15,23,42,0.04)] backdrop-blur-xl">
                    <Button variant="secondary" className="min-w-24 border-slate-200 bg-white shadow-none" onClick={cancelEditing}>
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button
                      variant="primary"
                      className="min-w-28 shadow-none"
                      onClick={() => updateMutation.mutate()}
                      disabled={!dirty || updateMutation.isPending || unresolvedEditingTableCount > 0 || emptyEditingCodeCount > 0}
                    >
                      <Save className="h-4 w-4" />
                      {updateMutation.isPending ? "保存中..." : "保存修改"}
                    </Button>
                  </div>
                </div>
              ) : (
                /* ===== Detail view ===== */
                <div className="question-drawer-detail px-7 py-6 text-sm">
                  <section className="border-b border-slate-200 pb-6">
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-950">
                        题干
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        <TypeBadge type={selectedQuestion.question_type} />
                        <DifficultyBadge
                          difficulty={selectedQuestion.difficulty}
                        />
                      </div>
                    </div>
                    <div className="whitespace-pre-wrap text-[15px] leading-7 text-slate-700">
                      <QuestionContentRenderer
                        content={selectedQuestion.content}
                        fallbackText={textFromContent(selectedQuestion.content)}
                        showTableMetadata
                        preserveCodeText
                      />
                    </div>
                  </section>

                  {/* ── Legacy/fallback question images ── */}
                  {(() => {
                    // Structured content already renders image segments above.
                    // `image_url` is a legacy mirror on many records; rendering
                    // both produced duplicate images in the detail drawer.
                    const fallbackUrls = fallbackQuestionImageUrls(
                      selectedQuestion.content,
                      selectedQuestion.image_url,
                    );
                    if (fallbackUrls.length === 0) return null;
                    return (
                      <section className="border-b border-slate-200 py-6">
                        <p className="mb-3 text-sm font-semibold text-slate-950">其他题目图片</p>
                        <div className="grid gap-3">
                          {fallbackUrls.map((raw, idx) => {
                            const src = resolveAssetUrl(raw) || raw;
                            return (
                              <a
                                key={`${comparableAssetUrl(raw)}-${idx}`}
                                href={src}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group/img relative block overflow-hidden rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/30 focus:outline-none focus:ring-2 focus:ring-slate-300"
                                aria-label={`在新窗口查看题目图片 ${idx + 1}`}
                              >
                                <img
                                  src={src}
                                  alt={`题目图片 ${idx + 1}`}
                                  className="max-w-full cursor-zoom-in rounded-lg transition-transform duration-300 group-hover/img:scale-[1.02]"
                                  style={{ maxHeight: "400px", width: "auto", objectFit: "contain" }}
                                  onError={(e) => {
                                    const target = e.currentTarget;
                                    target.style.display = "none";
                                    target.closest("a")?.classList.add("hidden");
                                  }}
                                />
                                <div className="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-inset ring-black/5" />
                              </a>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })()}

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      选项
                    </p>
                    <div className="mt-3">
                      {isMultiBlankChoice(selectedQuestion.question_type) ? (
                        <MultiBlankQuestionOptions
                          groups={resolveQuestionBlankOptionGroups(selectedQuestion)}
                        />
                      ) : (
                        <QuestionOptions
                          options={normalizeQuestionOptions(
                            resolveQuestionOptions(selectedQuestion),
                          )}
                        />
                      )}
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      答案
                    </p>
                    <div className="mt-3 inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[15px] font-semibold leading-6 text-slate-800">
                      <QuestionAnswerDisplay
                        questionType={selectedQuestion.question_type}
                        answer={selectedQuestion.answer}
                      />
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <p className="text-sm font-semibold text-slate-950">
                      解析
                    </p>
                    <div className="mt-3">
                      <QuestionAnalysis value={selectedQuestion.analysis} />
                    </div>
                  </section>

                  <section className="border-b border-slate-200 py-6">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-950">知识点与难度</p>
                      <DifficultyBadge difficulty={selectedQuestion.difficulty} />
                    </div>
                    <QuestionKnowledgePointsDisplay value={selectedQuestion.knowledge_points} />
                  </section>

                  <section className="py-6">
                    <button
                      type="button"
                      onClick={() => setVersionHistoryOpen((open) => !open)}
                      className="flex w-full items-center justify-between gap-4 rounded-lg px-1 py-1 text-left transition hover:bg-slate-50"
                      aria-expanded={versionHistoryOpen}
                    >
                      <div>
                        <p className="text-sm font-semibold text-slate-950">版本历史</p>
                        <p className="mt-1 text-[11px] leading-5 text-slate-400">
                          可按时间、修改人或修改原因查找，并支持任意两个版本对比。
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500">
                          {versions.data?.total ?? 0} 个版本
                        </span>
                        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${versionHistoryOpen ? "rotate-180" : ""}`} />
                      </div>
                    </button>

                    {versionHistoryOpen ? (
                      <div className="mt-4 animate-fade-in">
                        {(versions.data?.total ?? 0) === 0 && !versions.isFetching ? (
                          <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-5 text-center text-xs text-slate-400">
                            暂无历史版本
                          </div>
                        ) : (
                          <>
                            <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-3">
                              <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)]">
                                <div className="min-w-0">
                                  <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">基准版本</p>
                                  <QuestionVersionPicker
                                    value={baseVersion}
                                    onChange={setBaseVersion}
                                    versions={versions.data?.items ?? []}
                                    disabledValue={compareVersion}
                                    loading={versions.isFetching && !versions.data}
                                  />
                                </div>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  size="sm"
                                  className="h-10 w-11 rounded-xl p-0 shadow-none"
                                  disabled={compareVersion === null}
                                  title="交换对比版本"
                                  aria-label="交换基准版本和对比版本"
                                  onClick={() => {
                                    if (compareVersion === null) return;
                                    const previousBase = baseVersion;
                                    setBaseVersion(compareVersion);
                                    setCompareVersion(previousBase);
                                  }}
                                >
                                  <ArrowLeftRight className="h-4 w-4" />
                                </Button>
                                <div className="min-w-0">
                                  <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">对比版本</p>
                                  <QuestionVersionPicker
                                    value={compareVersion}
                                    onChange={setCompareVersion}
                                    versions={versions.data?.items ?? []}
                                    disabledValue={baseVersion}
                                    disabled={compareVersion === null && !versions.isFetching && (versions.data?.total ?? 0) === 0}
                                    loading={versions.isFetching && !versions.data}
                                  />
                                </div>
                              </div>
                              <p className="mt-3 text-[10px] leading-5 text-slate-400">
                                可按日期精确筛选，也可按“今天 / 本周 / 上周 / 更早”浏览；支持搜索版本号、修改人或修改原因。切换版本时会保留当前对比区域，避免页面跳动。
                              </p>
                            </div>

                            {compareVersion !== null && baseVersionData && compareVersionData ? (
                              <div className="relative mt-4 [overflow-anchor:none]">
                                {versionComparisonLoading ? (
                                  <div className="mb-2 flex justify-end">
                                    <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-medium text-slate-500">
                                      <Loader2 className="h-3 w-3 animate-spin" />
                                      正在切换到 {pendingVersionLabel ?? "所选版本"}
                                    </span>
                                  </div>
                                ) : null}
                                <div
                                  key={`${baseVersionLabel}-${compareVersionLabel}`}
                                  className={`space-y-3 transition-opacity duration-200 ${
                                    versionComparisonLoading ? "opacity-60" : "animate-fade-in opacity-100"
                                  }`}
                                >
                                  {renderDiff(
                                    "题干",
                                    baseVersionData.content,
                                    compareVersionData.content,
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  {renderDiff(
                                    "选项",
                                    isMultiBlankChoice(selectedQuestion.question_type)
                                      ? resolveBlankOptionGroupsValue(baseVersionData.content)
                                      : (baseVersionData.options ?? null),
                                    isMultiBlankChoice(selectedQuestion.question_type)
                                      ? resolveBlankOptionGroupsValue(compareVersionData.content)
                                      : (compareVersionData.options ?? null),
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  {renderDiff(
                                    "答案",
                                    baseVersionData.answer,
                                    compareVersionData.answer,
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  {renderDiff(
                                    "解析",
                                    baseVersionData.analysis ?? null,
                                    compareVersionData.analysis ?? null,
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  {renderDiff(
                                    "难度",
                                    baseVersionData.difficulty,
                                    compareVersionData.difficulty,
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  {renderDiff(
                                    "知识点",
                                    baseVersionData.knowledge_points ?? null,
                                    compareVersionData.knowledge_points ?? null,
                                    baseVersionLabel,
                                    compareVersionLabel,
                                  )}
                                  <details className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-3 transition-colors hover:border-slate-300">
                                    <summary className="cursor-pointer select-none text-xs font-medium text-slate-500 hover:text-slate-700">
                                      查看原始版本数据
                                    </summary>
                                    <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-white p-3 text-[11px] leading-5 text-slate-500">
                                      {JSON.stringify(
                                        {
                                          [baseVersionLabel]: baseVersionData,
                                          [compareVersionLabel]: compareVersionData,
                                        },
                                        null,
                                        2,
                                      )}
                                    </pre>
                                  </details>
                                </div>
                              </div>
                            ) : versionComparisonLoading ? (
                              <div className="mt-4 space-y-3 animate-pulse">
                                <div className="h-24 rounded-xl border border-slate-200 bg-slate-50/60" />
                                <div className="h-20 rounded-xl border border-slate-200 bg-slate-50/60" />
                                <div className="h-20 rounded-xl border border-slate-200 bg-slate-50/60" />
                              </div>
                            ) : null}
                          </>
                        )}
                      </div>
                    ) : null}
                  </section>

                  {renderSecondaryQuestionInfo(selectedQuestion)}
                </div>
              )
            ) : detail.isError ? (
              <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-7 text-center">
                <AlertCircle className="h-8 w-8 text-red-400" />
                <div>
                  <p className="text-sm font-semibold text-red-700">题目详情加载失败</p>
                  <p className="mt-1 text-xs text-slate-400">请检查网络连接后重试。</p>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="border-slate-200 bg-white shadow-none"
                  onClick={() => detail.refetch()}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  重新加载
                </Button>
              </div>
            ) : (
              <div className="space-y-3 px-7 py-6">
                <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
                <div className="h-32 animate-pulse rounded-xl bg-slate-100/80" />
                <div className="h-24 animate-pulse rounded-xl bg-slate-100/60" />
              </div>
            )}
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={unsavedIntent !== null}
        title={unsavedIntent === "close-drawer" ? "关闭题目编辑？" : "放弃当前修改？"}
        description={
          unsavedIntent === "close-drawer"
            ? "当前题目还有未保存修改。关闭后这些修改不会保留。"
            : "当前题目还有未保存修改。返回详情后这些修改不会保留。"
        }
        confirmText="放弃修改"
        danger
        onCancel={() => setUnsavedIntent(null)}
        onConfirm={() => {
          if (unsavedIntent === "close-drawer") finishCloseDetailDrawer();
          else if (unsavedIntent === "cancel-edit") finishCancelEditing();
        }}
      />

      <ConfirmDialog
        open={confirmState !== null}
        title="确认删除题目"
        description={confirmDescription}
        confirmText="删除"
        danger
        loading={deleteMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          deleteMutation.mutate(confirmState);
        }}
      />
    </div>
  );
}
