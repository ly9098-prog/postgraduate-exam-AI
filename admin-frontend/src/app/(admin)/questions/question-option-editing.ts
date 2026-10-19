import type { QuestionEditRequest, QuestionOptionsValue } from "@/lib/api/types";
import {
  addBlankOptionToAllGroups,
  addBlankOptionToGroup,
  normalizeQuestionOptions,
  resolveBlankOptionGroupsValue,
  reuseFirstBlankOptions,
  updateBlankOptionGroupText,
} from "@/lib/question-options";
import { contentRecord } from "./question-content-editing";

export function blankOptionGroupsStorageField(
  content: unknown,
): "blank_option_groups" | "blank_groups" {
  const record = contentRecord(content);
  if (record.blank_option_groups != null) return "blank_option_groups";
  if (record.blank_groups != null) return "blank_groups";
  return "blank_option_groups";
}

export function optionsToKeyValueList(options: QuestionOptionsValue | undefined) {
  return normalizeQuestionOptions(options).map(({ key, text }) => ({
    key,
    text: text ?? "",
  }));
}

export function optionStorageKey(options: QuestionOptionsValue | undefined, key: string) {
  if (!options || typeof options !== "object" || Array.isArray(options)) return key;
  const normalizedKey = key.trim().toUpperCase();
  return Object.keys(options).find(
    (candidate) => candidate.trim().toUpperCase() === normalizedKey,
  ) ?? key;
}

export function optionImageUrl(options: QuestionOptionsValue | undefined, key: string) {
  if (!options || typeof options !== "object" || Array.isArray(options)) return null;
  const storageKey = optionStorageKey(options, key);
  const value = (options as Record<string, unknown>)[storageKey];
  if (!value || typeof value !== "object") return null;
  return normalizeQuestionOptions({ [storageKey]: value })[0]?.imageUrl ?? null;
}

export function updateOptionText(
  options: QuestionOptionsValue | undefined,
  key: string,
  text: string,
): QuestionOptionsValue {
  const current = (options ?? {}) as Record<string, unknown>;
  const storageKey = optionStorageKey(options, key);
  const value = current[storageKey];
  const nextValue = value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>), text }
    : text;
  return { ...current, [storageKey]: nextValue };
}

function updateBlankGroups(
  current: QuestionEditRequest,
  update: (rawGroups: unknown, content: Record<string, unknown>) => unknown,
): QuestionEditRequest {
  const content = contentRecord(current.content);
  const field = blankOptionGroupsStorageField(content);
  return {
    ...current,
    content: { ...content, [field]: update(resolveBlankOptionGroupsValue(content), content) },
  };
}

export function addSharedBlankOption(
  current: QuestionEditRequest,
  slotIds: string[],
): QuestionEditRequest {
  return updateBlankGroups(current, (raw) => addBlankOptionToAllGroups(raw, slotIds));
}

export function reuseFirstBlankOption(
  current: QuestionEditRequest,
  targetGroupId?: string,
): QuestionEditRequest {
  return updateBlankGroups(current, (raw) => reuseFirstBlankOptions(raw, targetGroupId));
}

export function updateBlankOptionText(
  current: QuestionEditRequest,
  groupId: string,
  key: string,
  text: string,
): QuestionEditRequest {
  return updateBlankGroups(current, (raw) => updateBlankOptionGroupText(raw, groupId, key, text));
}

export function addOptionToBlankGroup(
  current: QuestionEditRequest,
  groupId: string,
): QuestionEditRequest {
  return updateBlankGroups(current, (raw) => addBlankOptionToGroup(raw, groupId));
}
