import type { AdminQuestion, QuestionOptionsValue } from "@/lib/api/types";
import { isImageSegmentType } from "@/lib/segment-utils";

/**
 * Normalized option representation for display.
 */
export type NormalizedQuestionOption = {
  key: string;
  text?: string;
  imageUrl?: string;
};

/** Normalized option group used by multi_blank_choice questions. */
export type NormalizedBlankOptionGroup = {
  id: string;
  options: NormalizedQuestionOption[];
};

const BLANK_OPTION_GROUP_FIELDS = ["blank_option_groups", "blank_groups"] as const;

/** Return the raw grouped-option value from question content, including the legacy alias. */
export function resolveBlankOptionGroupsValue(content: unknown): unknown {
  if (!content || typeof content !== "object" || Array.isArray(content)) return null;
  const record = content as Record<string, unknown>;
  for (const field of BLANK_OPTION_GROUP_FIELDS) {
    if (record[field] != null) return record[field];
  }
  return null;
}

/** Resolve multi-blank option groups from a question. */
export function resolveQuestionBlankOptionGroups(
  question: AdminQuestion | Record<string, unknown> | null | undefined,
): NormalizedBlankOptionGroup[] {
  if (!question) return [];

  const direct = (question as Record<string, unknown>).blank_option_groups;
  const directGroups = normalizeBlankOptionGroups(direct);
  if (directGroups.length > 0) return directGroups;

  return normalizeBlankOptionGroups(resolveBlankOptionGroupsValue(question.content));
}

/**
 * Normalize content.blank_option_groups into a stable display/edit shape.
 * Supports array and record-style option containers while preserving empty text.
 */
export function normalizeBlankOptionGroups(raw: unknown): NormalizedBlankOptionGroup[] {
  if (!Array.isArray(raw)) return [];

  return raw
    .map((group): NormalizedBlankOptionGroup | null => {
      if (!group || typeof group !== "object" || Array.isArray(group)) return null;
      const record = group as Record<string, unknown>;
      const id = String(record.id ?? record.marker ?? "").trim();
      if (!id) return null;

      const options = normalizeBlankGroupOptions(record.options);
      if (options.length === 0) return null;
      return { id, options };
    })
    .filter((group): group is NormalizedBlankOptionGroup => group !== null);
}

function normalizeBlankGroupOptions(raw: unknown): NormalizedQuestionOption[] {
  if (Array.isArray(raw)) {
    return raw
      .map((item, index): NormalizedQuestionOption | null => {
        const fallbackKey = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[index] ?? String(index + 1);
        if (item == null) return null;
        if (typeof item !== "object" || Array.isArray(item)) {
          return { key: fallbackKey, text: String(item) };
        }

        const record = item as Record<string, unknown>;
        const rawKey = String(record.key ?? record.label ?? record.name ?? fallbackKey).trim();
        const key = stripBlankGroupPrefix(rawKey).toUpperCase();
        if (!key) return null;
        const text = extractText(record) ?? "";
        const imageUrl = extractImageUrl(record);
        return { key, text, imageUrl };
      })
      .filter((option): option is NormalizedQuestionOption => option !== null);
  }

  if (raw && typeof raw === "object") {
    return Object.entries(raw as Record<string, unknown>)
      .map(([storageKey, value]): NormalizedQuestionOption | null => {
        const key = stripBlankGroupPrefix(storageKey).toUpperCase();
        if (!key) return null;
        if (value && typeof value === "object" && !Array.isArray(value)) {
          const record = value as Record<string, unknown>;
          const childKey = stripBlankGroupPrefix(
            String(record.key ?? record.label ?? record.name ?? key),
          ).toUpperCase();
          return {
            key: childKey || key,
            text: extractText(record) ?? "",
            imageUrl: extractImageUrl(record),
          };
        }
        return { key, text: value == null ? "" : String(value) };
      })
      .filter((option): option is NormalizedQuestionOption => option !== null);
  }

  return [];
}

function stripBlankGroupPrefix(key: string): string {
  return key.trim().replace(/^[①-⑳]/, "").replace(/^\d+(?=[A-Za-z])/, "");
}

/** Append an empty option to one blank group, preserving its array or record storage shape. */
export function addBlankOptionToGroup(rawGroups: unknown, groupId: string): unknown {
  if (!Array.isArray(rawGroups)) return rawGroups;
  const wantedGroup = String(groupId).trim();

  return rawGroups.map((group) => {
    if (!group || typeof group !== "object" || Array.isArray(group)) return group;
    const groupRecord = group as Record<string, unknown>;
    const currentId = String(groupRecord.id ?? groupRecord.marker ?? "").trim();
    if (currentId !== wantedGroup) return group;

    const rawOptions = groupRecord.options;
    const usedKeys = new Set(
      normalizeBlankGroupOptions(rawOptions).map((option) => option.key.trim().toUpperCase()),
    );
    const nextKey = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
      .split("")
      .find((candidate) => !usedKeys.has(candidate));
    if (!nextKey) return group;

    if (Array.isArray(rawOptions)) {
      return {
        ...groupRecord,
        options: [...rawOptions, { key: nextKey, text: "" }],
      };
    }

    if (rawOptions && typeof rawOptions === "object") {
      return {
        ...groupRecord,
        options: { ...(rawOptions as Record<string, unknown>), [nextKey]: "" },
      };
    }

    return { ...groupRecord, options: [{ key: nextKey, text: "" }] };
  });
}

/** Update one grouped option's text without discarding unrelated fields such as segments/images. */
export function updateBlankOptionGroupText(
  rawGroups: unknown,
  groupId: string,
  optionKey: string,
  text: string,
): unknown {
  if (!Array.isArray(rawGroups)) return rawGroups;
  const wantedGroup = String(groupId).trim();
  const wantedKey = stripBlankGroupPrefix(optionKey).toUpperCase();

  return rawGroups.map((group) => {
    if (!group || typeof group !== "object" || Array.isArray(group)) return group;
    const groupRecord = group as Record<string, unknown>;
    const currentId = String(groupRecord.id ?? groupRecord.marker ?? "").trim();
    if (currentId !== wantedGroup) return group;

    const rawOptions = groupRecord.options;
    if (Array.isArray(rawOptions)) {
      const nextOptions = rawOptions.map((option, index) => {
        const fallbackKey = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[index] ?? String(index + 1);
        if (!option || typeof option !== "object" || Array.isArray(option)) {
          return fallbackKey.toUpperCase() === wantedKey ? text : option;
        }
        const optionRecord = option as Record<string, unknown>;
        const key = stripBlankGroupPrefix(
          String(optionRecord.key ?? optionRecord.label ?? optionRecord.name ?? fallbackKey),
        ).toUpperCase();
        return key === wantedKey ? { ...optionRecord, text } : option;
      });
      return { ...groupRecord, options: nextOptions };
    }

    if (rawOptions && typeof rawOptions === "object") {
      const optionsRecord = rawOptions as Record<string, unknown>;
      const storageKey = Object.keys(optionsRecord).find(
        (candidate) => stripBlankGroupPrefix(candidate).toUpperCase() === wantedKey,
      );
      if (!storageKey) return group;
      const previous = optionsRecord[storageKey];
      const nextValue =
        previous && typeof previous === "object" && !Array.isArray(previous)
          ? { ...(previous as Record<string, unknown>), text }
          : text;
      return {
        ...groupRecord,
        options: { ...optionsRecord, [storageKey]: nextValue },
      };
    }

    return group;
  });
}

/** True when every blank uses the same keys/text/images. */
export function haveIdenticalBlankOptionSets(groups: NormalizedBlankOptionGroup[]): boolean {
  if (groups.length < 2) return false;
  const first = JSON.stringify(groups[0].options);
  return groups.slice(1).every((group) => JSON.stringify(group.options) === first);
}

const OPTION_KEYS = new Set(["key", "label", "name"]);
const OPTION_TEXT_KEYS = new Set([
  "text",
  "content",
  "option",
  "value",
  "stem",
]);
const OPTION_IMAGE_KEYS = new Set(["url", "image_url", "imageUrl", "src"]);

/**
 * Extract raw options from a question object.
 *
 * Priority:
 *  1. question.options (top-level)
 *  2. question.content.options
 *  3. question.content.parsed_options
 *  4. question.content.option_list
 *
 * Returns null when no structured options are found.
 */
export function resolveQuestionOptions(
  question: AdminQuestion | Record<string, unknown> | null | undefined,
): QuestionOptionsValue {
  if (!question) return null;

  // Check 1: top-level options
  if (question.options != null) {
    if (!_isEmptyOptionsValue(question.options)) {
      return question.options as QuestionOptionsValue;
    }
  }

  // Check 2–4: content-fields
  const content = question.content;
  if (content && typeof content === "object" && !Array.isArray(content)) {
    for (const field of ["options", "parsed_options", "option_list"] as const) {
      const val = (content as Record<string, unknown>)[field];
      if (val != null && !_isEmptyOptionsValue(val)) {
        return val as QuestionOptionsValue;
      }
    }
  }

  return null;
}

function _isEmptyOptionsValue(val: unknown): boolean {
  if (typeof val === "object" && !Array.isArray(val) && val !== null) {
    return Object.keys(val).length === 0;
  }
  if (typeof val === "string") return val === "";
  if (Array.isArray(val)) return val.length === 0;
  return false;
}

/**
 * Normalize raw options into a uniform array of { key, text?, imageUrl? }.
 *
 * Supported input formats:
 *  - { A: "text", B: "text" }       (object with key-value)
 *  - { A: { text: "…", url: "…" } } (object with rich values)
 *  - ["text", "text"]               (array of strings)
 *  - [{ key: "A", text: "…" }, …]   (array of objects)
 *  - "A. text\nB. text"             (formatted string)
 *  - null / undefined / "" → []
 */
export function normalizeQuestionOptions(
  raw: QuestionOptionsValue | undefined,
): NormalizedQuestionOption[] {
  if (raw == null) return [];
  if (typeof raw === "string") {
    return normalizeStringOptions(raw);
  }

  if (Array.isArray(raw)) {
    return normalizeArrayOptions(raw);
  }

  // Object (Record) format
  return normalizeRecordOptions(raw);
}

// ─── string format ────────────────────────────────────────────────

function normalizeStringOptions(raw: string): NormalizedQuestionOption[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];

  const lines = trimmed.split(/\n+/).filter(Boolean);
  if (lines.length >= 1) {
    const result: NormalizedQuestionOption[] = [];
    for (const line of lines) {
      const match = line.match(
        /^([A-Za-z0-9一二三四五六七八九十]+)\s*[.、，,]\s*(.*)/,
      );
      if (match) {
        result.push({
          key: match[1].toUpperCase(),
          text: match[2].trim(),
        });
      } else {
        // No label prefix — use index as key
        result.push({
          key: String(result.length + 1),
          text: line.trim(),
        });
      }
    }
    if (result.length > 0) return result;
  }
  // Single line, no labels — return as one item
  return [{ key: "1", text: trimmed }];
}

// ─── array format ─────────────────────────────────────────────────

function normalizeArrayOptions(raw: unknown[]): NormalizedQuestionOption[] {
  if (raw.length === 0) return [];
  const result: NormalizedQuestionOption[] = [];
  const labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  for (let i = 0; i < raw.length; i++) {
    const item = raw[i];
    if (item == null) continue;
    if (
      typeof item === "string" ||
      typeof item === "number" ||
      typeof item === "boolean"
    ) {
      result.push({
        key: labels[i] ?? String(i + 1),
        text: String(item),
      });
    } else if (typeof item === "object") {
      const obj = item as Record<string, unknown>;
      const key = extractKey(obj, labels[i] ?? String(i + 1));
      const text = extractText(obj);
      const imageUrl = extractImageUrl(obj);
      if (text || imageUrl) {
        result.push({
          key,
          text: text || undefined,
          imageUrl: imageUrl || undefined,
        });
      }
    }
  }
  return result;
}

// ─── record (object) format ───────────────────────────────────────

function normalizeRecordOptions(
  raw: Record<string, unknown>,
): NormalizedQuestionOption[] {
  const entries = Object.entries(raw);
  if (entries.length === 0) return [];

  // Determine sort order: natural key order if keys look like A,B,C or 1,2,3
  const sorted = keysLikeAlphaNumeric(entries.map(([k]) => k))
    ? entries.sort(([a], [b]) => compareAlphaNumericKeys(a, b))
    : entries;

  const result: NormalizedQuestionOption[] = [];
  for (const [key, value] of sorted) {
    if (value == null) continue;
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      result.push({ key: key.toUpperCase(), text: String(value) });
    } else if (typeof value === "object" && !Array.isArray(value)) {
      const obj = value as Record<string, unknown>;
      const text = extractText(obj);
      const imageUrl = extractImageUrl(obj);
      const childKey = extractKey(obj, key);
      if (text || imageUrl) {
        result.push({
          key: childKey.toUpperCase(),
          text: text || undefined,
          imageUrl: imageUrl || undefined,
        });
      } else {
        // Fallback: serialize
        result.push({ key: key.toUpperCase(), text: JSON.stringify(value) });
      }
    } else {
      result.push({ key: key.toUpperCase(), text: String(value) });
    }
  }
  return result;
}

// ─── helpers ───────────────────────────────────────────────────────

function extractKey(
  obj: Record<string, unknown>,
  fallback: string,
): string {
  for (const k of OPTION_KEYS) {
    const v = obj[k];
    if (v != null && typeof v === "string") return v;
  }
  return fallback;
}

function extractText(
  obj: Record<string, unknown>,
): string | undefined {
  for (const k of OPTION_TEXT_KEYS) {
    const v = obj[k];
    if (
      v != null &&
      (typeof v === "string" || typeof v === "number" || typeof v === "boolean")
    ) {
      return String(v);
    }
  }
  return undefined;
}

function extractImageUrl(
  obj: Record<string, unknown>,
): string | undefined {
  for (const k of OPTION_IMAGE_KEYS) {
    const v = obj[k];
    if (v != null && typeof v === "string" && v.trim()) return v.trim();
  }
  // Rich options store images as segments: { text, segments: [{type:"image", url}] }
  // (canonical form the miniprogram renders). Fall back to reading them here.
  const segments = obj["segments"];
  if (Array.isArray(segments)) {
    const segs = segments as Array<Record<string, unknown>>;
    for (const seg of segs) {
      if (
        seg &&
        typeof seg === "object" &&
        isImageSegmentType(String(seg.type ?? "")) &&
        typeof seg.url === "string" &&
        seg.url.trim()
      ) {
        return seg.url.trim();
      }
    }
    for (const seg of segs) {
      if (seg && typeof seg === "object" && typeof seg.url === "string" && seg.url.trim()) {
        return seg.url.trim();
      }
    }
  }
  return undefined;
}

function keysLikeAlphaNumeric(keys: string[]): boolean {
  if (keys.length === 0) return false;
  return keys.every((k) => /^[A-Za-z0-9]+$/.test(k));
}

function compareAlphaNumericKeys(a: string, b: string): number {
  // Numeric keys first
  const aNum = /^\d+$/.test(a) ? parseInt(a, 10) : NaN;
  const bNum = /^\d+$/.test(b) ? parseInt(b, 10) : NaN;
  if (!isNaN(aNum) && !isNaN(bNum)) return aNum - bNum;
  if (!isNaN(aNum)) return -1;
  if (!isNaN(bNum)) return 1;
  // Alpha keys: sort by length then alphabetically (A, B, C, …, AA, AB, …)
  if (a.length !== b.length) return a.length - b.length;
  return a.localeCompare(b);
}
