export type BlankOption = {
  key: string;
  text: string;
  segments?: Record<string, unknown>[];
};

export type BlankOptionGroup = {
  id: string;
  options: BlankOption[];
};

export type NormalizeResult = {
  groups: BlankOptionGroup[];
  warnings: string[];
  errors: string[];
};

export type BlankAnswerMap = Record<string, string>; // slotId -> option key(s), e.g. {"①": "B", "②": "D"}; multi-select blanks join letters with "," e.g. {"①": "A,C"}

/**
 * Normalize blank_option_groups from various input formats into a canonical
 * array of {id: string, options: BlankOption[]}.
 ...
 *  - Does NOT mutate input
 */
export function normalizeBlankOptionGroups(value: unknown): BlankOptionGroup[] {
  if (!Array.isArray(value)) return [];

  return value
    .map((group: unknown): BlankOptionGroup | null => {
      if (!group || typeof group !== "object") return null;
      const g = group as Record<string, unknown>;

      const rawId = g.id;
      const id = rawId != null ? String(rawId) : "";
      if (!id) return null;

      const rawOptions = g.options;
      let opts: BlankOption[] = [];

      if (Array.isArray(rawOptions)) {
        opts = rawOptions
          .map((opt: unknown): BlankOption | null => {
            if (!opt || typeof opt !== "object") return null;
            const o = opt as Record<string, unknown>;
            const rawKey = o.key;
            let key = rawKey != null ? String(rawKey).toUpperCase() : "";
            // Strip group-ID prefix from option key (e.g. "①D" → "D", "1A" → "A")
            // Some data stores prefixed keys like "①D" when options are per-group.
            key = key.replace(/^[①-⑳\d]/, "");
            const text = String(o.text ?? "");
            if (!key || !text) return null;
            const segments =
              o.segments && Array.isArray(o.segments) && o.segments.length > 0
                ? (o.segments as Record<string, unknown>[])
                : undefined;
            return { key, text, segments };
          })
          .filter((o): o is BlankOption => o !== null);
      } else if (rawOptions && typeof rawOptions === "object") {
        opts = Object.entries(rawOptions as Record<string, unknown>)
          .map(([key, value]): BlankOption | null => {
            let k = key.toUpperCase();
            // Strip group-ID prefix (e.g. "①D" → "D", "1A" → "A")
            k = k.replace(/^[①-⑳\d]/, "");
            if (value && typeof value === "object" && "text" in (value as Record<string, unknown>)) {
              const v = value as Record<string, unknown>;
              return {
                key: k,
                text: String(v.text ?? ""),
                segments: v.segments as Record<string, unknown>[] | undefined,
              };
            }
            const text = String(value ?? "");
            if (!k || !text) return null;
            return { key: k, text };
          })
          .filter((o): o is BlankOption => o !== null);
      }

      if (opts.length < 2) return null;

      return { id, options: opts };
    })
    .filter((g): g is BlankOptionGroup => g !== null);
}

/**
 * Normalize a slot value to canonical form: uppercase letters, deduplicated,
 * sorted, comma-joined ("c,a" → "A,C", "AC" → "A,C"). Returns "" when no
 * valid letter is present.
 */
export function normalizeSlotValue(raw: string): string {
  const letters = raw.toUpperCase().match(/[A-H]/g) ?? [];
  return [...new Set(letters)].sort().join(",");
}

/**
 * Parse a multi-blank answer string into a {slotId: answerKey(s)} map.
 *
 * Supports:
 *  - Canonical: ①:B;②:D / ①:A,C;②:B
 *  - OCR circled: ①B、②D / ①AC、②D
 *  - Parenthesized: (1)B、(2)D
 *  - Numbered colon: 1:B,2:D / 1:A,C;2:B,D
 *  - Chinese: 第1空B
 *  - Positional B,D (only when parts count matches groupIds.length)
 *
 * Multi-letter slot values are canonicalized to sorted comma-joined letters.
 * Falls back to an empty map if unparseable.
 */
export function parseBlankAnswer(
  answer: string | null | undefined,
  groupIds: string[],
): BlankAnswerMap {
  const map: BlankAnswerMap = {};
  if (!answer) return map;
  const a = answer.trim();
  if (!a) return map;

  // Value = one or more A-H letters, optionally comma/顿号 separated
  // (only when the next char is another letter — a separator before a slot
  // marker such as ② is a pair separator, not a value separator).
  const VALUE = String.raw`[A-Ha-h](?:\s*[，,、](?=\s*[A-Ha-h])\s*[A-Ha-h])*`;

  // Try canonical "slot:value;slot:value" format
  for (const pair of a.split(/[;；]/)) {
    const m = pair.match(new RegExp(`^\\s*(.+?)\\s*[:：]\\s*(${VALUE})\\s*$`));
    if (m) {
      const val = normalizeSlotValue(m[2]);
      if (val) map[m[1].trim()] = val;
      else map[m[1].trim()] = "";
    }
  }
  if (Object.keys(map).filter((k) => map[k]).length > 0) return map;

  // Try OCR circled format ①B、②D / ①AC、②D (letters may run together)
  const RUN_VALUE = String.raw`[A-Ha-h]{1,4}(?:\s*[，,、](?=\s*[A-Ha-h])\s*[A-Ha-h]{1,4})*`;
  const circledRe = new RegExp(`([①-⑳])\\s*(${RUN_VALUE})`, "g");
  let cm: RegExpExecArray | null;
  while ((cm = circledRe.exec(a)) !== null) {
    const val = normalizeSlotValue(cm[2]);
    if (val) map[cm[1]] = val;
  }
  if (Object.keys(map).length > 0) return map;

  // Try parenthesized (1)B、(2)D
  const parenRe = new RegExp(`[(（]\\s*(\\d+)\\s*[)）]\\s*(${RUN_VALUE})`, "g");
  let pm: RegExpExecArray | null;
  while ((pm = parenRe.exec(a)) !== null) {
    const val = normalizeSlotValue(pm[2]);
    if (val) map[pm[1]] = val;
  }
  if (Object.keys(map).length > 0) return map;

  // Try 1:B,2:D format
  const numColonRe = /(\d+)\s*[:：]\s*([A-Ha-h](?:\s*[，,、]\s*[A-Ha-h])*)/g;
  let nm: RegExpExecArray | null;
  while ((nm = numColonRe.exec(a)) !== null) {
    const val = normalizeSlotValue(nm[2]);
    if (val) map[nm[1]] = val;
  }
  if (Object.keys(map).length > 0) return map;

  // Try 第1空B
  const cnRe = /第\s*(\d+)\s*空\s*([A-Ha-h])/g;
  let cnm: RegExpExecArray | null;
  while ((cnm = cnRe.exec(a)) !== null) {
    const val = normalizeSlotValue(cnm[2]);
    if (val) map[cnm[1]] = val;
  }
  if (Object.keys(map).length > 0) return map;

  // Positional B,D only when parts count matches groupIds.length
  const parts = a
    .split(/[，,、\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-H](,[A-H])*$/.test(s));
  if (parts.length === groupIds.length && parts.length >= 2) {
    parts.forEach((v, i) => {
      map[groupIds[i]] = normalizeSlotValue(v);
    });
  }

  return map;
}

/**
 * Serialize a BlankAnswerMap to canonical format: ①:B;②:D
 *
 * Only includes slots that are in groupIds, in groupIds order.
 * Empty map produces "".
 */
export function serializeBlankAnswer(
  answerMap: BlankAnswerMap,
  groupIds: string[],
): string {
  return groupIds
    .filter((id) => answerMap[id])
    .map((id) => `${id}:${answerMap[id]}`)
    .join(";");
}

/**
 * Check if all groups have the exact same set of options (deep compare
 * of key + text + segments). Returns false when groups.length < 2.
 * Uses structured comparison, not JSON.stringify ordering tricks.
 */
/**
 * Check if all groups have the exact same set of options (deep compare
 * of key + text + segments). Returns false when groups.length < 2.
 * Uses structured comparison, not JSON.stringify ordering tricks.
 */
export function haveIdenticalOptionSets(groups: BlankOptionGroup[]): boolean {
  if (groups.length < 2) return false;

  const first = groups[0].options;
  for (let i = 1; i < groups.length; i++) {
    const curr = groups[i].options;
    if (curr.length !== first.length) return false;
    for (let j = 0; j < first.length; j++) {
      const a = first[j];
      const b = curr[j];
      if (a.key !== b.key || a.text !== b.text) return false;
      // Compare segments
      const aHasSegs = !!(a.segments && a.segments.length > 0);
      const bHasSegs = !!(b.segments && b.segments.length > 0);
      if (aHasSegs !== bHasSegs) return false;
      if (aHasSegs && bHasSegs) {
        if (JSON.stringify(a.segments) !== JSON.stringify(b.segments)) return false;
      }
    }
  }
  return true;
}

/**
 * Return the shared options when all groups are identical.
 * Returns a copy of the first group's options, or empty array.
 */
export function getSharedOptions(groups: BlankOptionGroup[]): BlankOption[] {
  if (!haveIdenticalOptionSets(groups)) return [];
  return groups[0].options.map((opt) => ({ ...opt }));
}

/**
 * Create a new groups array with an option update applied to ALL groups.
 * Does NOT mutate the input.
 */
export function updateSharedOption(
  groups: BlankOptionGroup[],
  key: string,
  value: Partial<BlankOption>,
): BlankOptionGroup[] {
  return groups.map((group) => ({
    ...group,
    options: group.options.map((opt) =>
      opt.key === key ? { ...opt, ...value } : opt,
    ),
  }));
}

export type MultiBlankSource =
  | "parsed_content"
  | "raw_data"
  | "none";

export type ExtractMultiBlankResult = {
  groups: BlankOptionGroup[];
  answer: string;
  source: MultiBlankSource;
  warnings: string[];
  errors: string[];
};

/**
 * Extract multi_blank_choice source data from an import item with explicit
 * priority, warnings, and error reporting.
 *
 * Priority:
 *  1. parsed_content.blank_option_groups (must be valid after normalize+dedup)
 *  2. raw_data.blank_option_groups (only when parsed_content field is absent)
 *  3. none → empty groups + error
 *
 * Rules:
 *  - parsed_content exists but blank_option_groups is invalid → error, do NOT
 *    fall through to raw_data (would mask a storage corruption)
 *  - raw_data fallback shows a warning that the item is using legacy data
 *  - Does NOT mutate input
 */
export function extractMultiBlankSource(
  item: Record<string, unknown>,
): ExtractMultiBlankResult {
  const warnings: string[] = [];
  const errors: string[] = [];

  const parsedContent = item.parsed_content as Record<string, unknown> | undefined;
  const rawData = item.raw_data as Record<string, unknown> | undefined;

  // Priority 1: parsed_content.blank_option_groups
  if (parsedContent) {
    const rawGroups = normalizeBlankOptionGroups(
      parsedContent.blank_option_groups,
    );
    const { groups, warnings: dw, errors: de } = deduplicateGroupOptions(rawGroups);
    warnings.push(...dw);
    errors.push(...de);

    if (groups.length >= 2) {
      const answer = String(item.parsed_answer ?? "");
      return { groups, answer, source: "parsed_content", warnings, errors };
    }

    // parsed_content exists but groups are invalid → this is a corruption
    errors.push(
      "parsed_content 中存在 blank_option_groups 但数据无效，请检查数据完整性",
    );
    return { groups: [], answer: "", source: "parsed_content", warnings, errors };
  }

  // Priority 2: raw_data.blank_option_groups (only when parsed_content is absent)
  if (rawData) {
    const rawGroups = normalizeBlankOptionGroups(rawData.blank_option_groups);
    const { groups, warnings: dw, errors: de } = deduplicateGroupOptions(rawGroups);
    warnings.push(...dw);
    errors.push(...de);

    if (groups.length >= 2) {
      warnings.push("当前题目使用历史原始数据初始化，保存后将写入标准 parsed_content 结构");
      const answer = String(item.parsed_answer ?? "");
      return { groups, answer, source: "raw_data", warnings, errors };
    }
  }

  // No valid source found
  return {
    groups: [],
    answer: "",
    source: "none",
    warnings,
    errors: ["未找到有效的多空选择数据"],
  };
}

/**
 * Validate that an answer map covers every group with valid option keys.
 * Each slot value may be a single letter ("A") or a comma-joined letter set
 * ("A,C") for multi-select blanks.
 */
export function validateBlankAnswerMap(
  groups: BlankOptionGroup[],
  answerMap: BlankAnswerMap,
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  const groupIds = new Set(groups.map((g) => g.id));

  // Must cover all groups
  const answeredIds = new Set(Object.keys(answerMap));
  for (const group of groups) {
    if (!answeredIds.has(group.id)) {
      errors.push(`缺少空 ${group.id} 的答案`);
    }
  }

  // No extra slots
  for (const key of Object.keys(answerMap)) {
    if (!groupIds.has(key)) {
      errors.push(`含未知空位: ${key}`);
    }
  }

  // Each answer value must be in the group's option keys
  for (const group of groups) {
    const selected = answerMap[group.id];
    if (selected) {
      const validKeys = new Set(group.options.map((o) => o.key));
      const letters = selected.split(",").filter(Boolean);
      const invalid = letters.filter((l) => !validKeys.has(l));
      if (letters.length === 0) {
        errors.push(`空 ${group.id} 尚未选择答案`);
      } else if (invalid.length > 0) {
        errors.push(`空 ${group.id} 的答案 "${invalid.join(",")}" 不在选项内`);
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

/**
 * Compare two options for full equality (key + text + segments).
 */
function optionsEqual(a: BlankOption, b: BlankOption): boolean {
  if (a.key !== b.key || a.text !== b.text) return false;
  const aSegs = !!(a.segments && a.segments.length > 0);
  const bSegs = !!(b.segments && b.segments.length > 0);
  if (aSegs !== bSegs) return false;
  if (aSegs && JSON.stringify(a.segments) !== JSON.stringify(b.segments)) return false;
  return true;
}

/**
 * Deduplicate fully identical options within each group and detect
 * conflicting duplicates (same key, different text).
 *
 * Rules:
 *  1. Fully identical (key+text+segments) → fold, add warning.
 *  2. Same key, different text → conflict, add error, leave both.
 *  3. Different key, same text → allowed, keep both.
 *  4. Order preserves first occurrence.
 *
 * Returns deduplicated groups plus per-group warnings/errors.
 */
export function deduplicateGroupOptions(
  groups: BlankOptionGroup[],
): { groups: BlankOptionGroup[]; warnings: string[]; errors: string[] } {
  const warnings: string[] = [];
  const errors: string[] = [];

  const newGroups = groups.map((group) => {
    const seen: BlankOption[] = [];
    const keyIndex = new Map<string, number>(); // key → index in seen

    for (const opt of group.options) {
      const existingIdx = keyIndex.get(opt.key);
      if (existingIdx !== undefined) {
        const existing = seen[existingIdx];
        if (optionsEqual(existing, opt)) {
          warnings.push(`空位 ${group.id} 中存在完全重复的选项 ${opt.key}，已折叠（保留第一项）`);
          // skip duplicate
        } else {
          errors.push(`空位 ${group.id} 中选项 ${opt.key} 出现多次且内容不一致，请人工处理`);
          // keep both (don't auto-resolve conflicts)
          seen.push(opt);
        }
      } else {
        keyIndex.set(opt.key, seen.length);
        seen.push(opt);
      }
    }

    return { ...group, options: seen };
  });

  return { groups: newGroups, warnings, errors };
}

/**
 * Result from getMultiBlankSaveState.
 */
export type MultiBlankSaveState = {
  canSave: boolean;
  errors: string[];
  warnings: string[];
};

/**
 * Compute save availability for multi-blank choice.
 *
 * Blocking conditions (error → !canSave):
 *  1. groups < 2
 *  2. group ID empty
 *  3. group ID duplicate
 *  4. any group has < 2 options
 *  5. option key empty
 *  6. option key duplicate per group
 *  7. dedupErrors non-empty (conflicting duplicates)
 *  8. answerMap missing group
 *  9. answerMap has extra (phantom) slot
 *  10. answer value not in group's option keys
 *  11. rawAnswerError non-empty (hasUnappliedDraft with parse error)
 *  12. hasUnappliedDraft is true (unapplied edit blocks save)
 *
 * Non-blocking warnings:
 *  - raw_data fallback
 *  - identical duplicates folded
 *  - empty header map (no selection yet)
 *
 * Pure function: no side effects, no mutations.
 */
export function getMultiBlankSaveState(
  groups: BlankOptionGroup[],
  answerMap: BlankAnswerMap,
  dedupWarnings: string[] | undefined,
  dedupErrors: string[] | undefined,
  hasUnappliedDraft: boolean | undefined,
): MultiBlankSaveState {
  const errors: string[] = [];
  const warnings: string[] = [];

  // 1. Groups count
  if (groups.length < 2) {
    errors.push("多空选择题至少需要 2 个空位");
    return { canSave: false, errors, warnings };
  }

  // 2-3. Group IDs
  const groupIds = groups.map((g) => g.id);
  for (let i = 0; i < groupIds.length; i++) {
    if (!groupIds[i].trim()) {
      errors.push(`空位 ${i + 1} 的 ID 为空`);
    }
  }
  if (new Set(groupIds).size !== groupIds.length) {
    errors.push("空位 ID 存在重复");
  }

  // 4. Options count per group
  for (const group of groups) {
    if (group.options.length < 2) {
      errors.push(`空位 ${group.id} 至少需要 2 个选项`);
    }
  }

  // 5-6. Option keys
  for (const group of groups) {
    const keys = group.options.map((o) => o.key).filter(Boolean);
    if (keys.length !== new Set(keys).size) {
      errors.push(`空位 ${group.id} 的选项 key 存在重复`);
    }
  }

  // 7. Dedup errors
  if (dedupErrors && dedupErrors.length > 0) {
    errors.push(...dedupErrors);
  }

  // 8-10. Answer map validation
  const answeredIds = new Set(Object.keys(answerMap));
  for (const group of groups) {
    if (!answeredIds.has(group.id)) {
      errors.push(`空位 ${group.id} 尚未选择答案`);
    }
  }
  for (const key of Object.keys(answerMap)) {
    if (!groupIds.includes(key)) {
      errors.push(`答案列表中含未知空位: ${key}`);
    }
  }
  for (const group of groups) {
    const selected = answerMap[group.id];
    if (selected) {
      const validKeys = new Set(group.options.map((o) => o.key));
      const letters = selected.split(",").filter(Boolean);
      const invalid = letters.filter((l) => !validKeys.has(l));
      if (letters.length === 0) {
        errors.push(`空位 ${group.id} 尚未选择答案`);
      } else if (invalid.length > 0) {
        errors.push(`空位 ${group.id} 的答案 "${invalid.join(",")}" 不在选项内`);
      }
    }
  }

  // 11-12. Unapplied draft
  if (hasUnappliedDraft) {
    errors.push("高级答案输入有未应用的修改，请先点击「应用」或完成输入");
  }

  // Non-blocking warnings
  if (dedupWarnings && dedupWarnings.length > 0) {
    warnings.push(...dedupWarnings);
  }

  return { canSave: errors.length === 0, errors, warnings };
}

/**
 * The sub-state of multi_blank_choice managed by the reducer.
 *
 * Use reduceMultiBlankEditState for all mutations.
 */
export type MultiBlankEditState = {
  groups: BlankOptionGroup[];
  answerMap: BlankAnswerMap;
  usesSharedOptions: boolean;
  sharedOptions: BlankOption[];
  dedupWarnings?: string[];
  dedupErrors?: string[];
  hasUnappliedDraft?: boolean;
};

/**
 * Action types for the multi_blank_choice reducer.
 *
 * Every state-changing user interaction dispatches an action.
 * The reducer reads the latest state from its argument, not from a closure.
 */
export type MultiBlankAction =
  | { type: "toggle_answer"; groupId: string; optionKey: string; multi?: boolean }
  | { type: "apply_answer_map"; answerMap: BlankAnswerMap }
  | { type: "update_shared_options"; options: BlankOption[] }
  | { type: "update_group_options"; groupId: string; options: BlankOption[] }
  | { type: "rename_group"; oldId: string; newId: string }
  | { type: "add_group" }
  | { type: "remove_group"; groupId: string }
  | { type: "split_shared_groups" }
  | { type: "set_draft_state"; hasUnappliedDraft: boolean }
  | { type: "reset"; state: MultiBlankEditState };

/**
 * Remove answerMap entries whose value no longer exists in the group's options.
 * Slot values may be comma-joined letter sets ("A,C"); each letter is checked
 * independently and invalid letters are dropped (empty values removed).
 */
function cleanAnswerMapForGroups(
  answerMap: BlankAnswerMap,
  groups: BlankOptionGroup[],
): BlankAnswerMap {
  const cleaned: BlankAnswerMap = {};
  for (const group of groups) {
    const selected = answerMap[group.id];
    if (selected) {
      const validKeys = new Set(group.options.map((o) => o.key));
      const letters = selected.split(",").filter((l) => validKeys.has(l));
      if (letters.length > 0) {
        cleaned[group.id] = letters.join(",");
      }
    }
  }
  return cleaned;
}

/**
 * Find the next available alphabetic key (A-Z) not already used in an option set.
 */
function nextAlphaKey(usedKeys: Set<string>): string {
  for (let i = 0; i < 26; i++) {
    const letter = String.fromCharCode(65 + i);
    if (!usedKeys.has(letter)) return letter;
  }
  return "";
}

/**
 * Generate the next group ID in sequence (①, ②, ③, …).
 */
function nextGroupId(existingIds: string[]): string {
  const circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  for (const ch of circled) {
    if (!existingIds.includes(ch)) return ch;
  }
  return `G${existingIds.length + 1}`;
}

/**
 * Pure reducer for multi_blank_choice edit state.
 *
 * Rules:
 *  - Does NOT mutate input state (returns a new object).
 *  - Safe under React Strict Mode (no side effects).
 *  - closure-safe: reads the latest state from the first argument.
 *  - Invalid option selections are cleaned up on groups change.
 *  - sharedOptions is kept in-sync via the parent's sync function.
 */
export function reduceMultiBlankEditState(
  state: MultiBlankEditState,
  action: MultiBlankAction,
): MultiBlankEditState {
  switch (action.type) {
    case "toggle_answer": {
      const newMap = { ...state.answerMap };
      if (action.multi) {
        // Multi-select blank: toggle one letter within the slot's letter set.
        const current = (newMap[action.groupId] ?? "")
          .split(",")
          .filter(Boolean);
        const next = current.includes(action.optionKey)
          ? current.filter((k) => k !== action.optionKey)
          : [...current, action.optionKey];
        if (next.length === 0) {
          delete newMap[action.groupId];
        } else {
          newMap[action.groupId] = next.sort().join(",");
        }
      } else if (newMap[action.groupId] === action.optionKey) {
        delete newMap[action.groupId];
      } else {
        newMap[action.groupId] = action.optionKey;
      }
      return {
        ...state,
        answerMap: newMap,
        hasUnappliedDraft: false,
      };
    }

    case "apply_answer_map": {
      return {
        ...state,
        answerMap: { ...action.answerMap },
        hasUnappliedDraft: false,
      };
    }

    case "update_shared_options": {
      const newGroups = state.groups.map((g) => ({
        ...g,
        options: action.options.map((opt) => ({ ...opt })),
      }));
      const cleanMap = cleanAnswerMapForGroups(state.answerMap, newGroups);
      return {
        ...state,
        groups: newGroups,
        answerMap: cleanMap,
        usesSharedOptions: true,
      };
    }

    case "update_group_options": {
      const newGroups = state.groups.map((g) =>
        g.id === action.groupId
          ? { ...g, options: action.options.map((opt) => ({ ...opt })) }
          : g,
      );
      const cleanMap = cleanAnswerMapForGroups(state.answerMap, newGroups);
      return {
        ...state,
        groups: newGroups,
        answerMap: cleanMap,
      };
    }

    case "rename_group": {
      const newGroups = state.groups.map((g) =>
        g.id === action.oldId ? { ...g, id: action.newId } : g,
      );
      const newMap: BlankAnswerMap = {};
      for (const [k, v] of Object.entries(state.answerMap)) {
        newMap[k === action.oldId ? action.newId : k] = v;
      }
      return {
        ...state,
        groups: newGroups,
        answerMap: newMap,
      };
    }

    case "add_group": {
      const existingIds = state.groups.map((g) => g.id);
      const newId = nextGroupId(existingIds);
      const newGroups = [
        ...state.groups,
        {
          id: newId,
          options: [] as BlankOption[],
        },
      ];
      return { ...state, groups: newGroups };
    }

    case "remove_group": {
      const newGroups = state.groups.filter((g) => g.id !== action.groupId);
      const newMap = { ...state.answerMap };
      delete newMap[action.groupId];
      return {
        ...state,
        groups: newGroups,
        answerMap: newMap,
      };
    }

    case "split_shared_groups": {
      return { ...state, usesSharedOptions: false };
    }

    case "set_draft_state": {
      return { ...state, hasUnappliedDraft: action.hasUnappliedDraft };
    }

    case "reset": {
      return {
        ...action.state,
        sharedOptions: getSharedOptions(action.state.groups),
        hasUnappliedDraft: false,
      };
    }

    default:
      return state;
  }
}

/**
 * Sync derived fields on the parent EditState after a reducer action.
 *
 * Recomputes:
 *  - `answer` from answerMap
 *  - `sharedOptions` for the editor
 */
export function syncDerivedMultiBlankFields(
  prev: { answer: string; multiBlank?: MultiBlankEditState },
  nextMultiBlank: MultiBlankEditState,
): { answer: string; multiBlank: MultiBlankEditState } {
  const groupIds = nextMultiBlank.groups.map((g) => g.id);
  const canonical = serializeBlankAnswer(nextMultiBlank.answerMap, groupIds);
  const sharedOptions =
    nextMultiBlank.usesSharedOptions && nextMultiBlank.groups.length >= 2
      ? getSharedOptions(nextMultiBlank.groups)
      : [];

  return {
    answer: canonical,
    multiBlank: {
      ...nextMultiBlank,
      sharedOptions,
    },
  };
}

/**
 * Result from buildMultiBlankSavePayload.
 */
export type SavePayloadResult = {
  payload: Record<string, unknown> | null;
  errors: string[];
  warnings: string[];
};

/**
 * Validate edit state and build the save payload for a multi-blank choice.
 *
 * Checks:
 *  1. groups length >= 2
 *  2. group IDs are non-empty and unique
 *  3. each group has >= 2 options
 *  4. option keys are non-empty and unique per group
 *  5. no conflicting duplicates
 *  6. answerMap covers all groups
 *  7. each answer is valid for its group
 *  8. no extra slots in answerMap
 *
 * Produced payload:
 *  - question_type = the passed questionType (multi_blank_choice or
 *    multi_blank_multiple_choice)
 *  - parsed_content.blank_option_groups = deduplicated groups
 *  - parsed_content.text = stem (preserved from input)
 *  - answer = serialized canonical answer from answerMap
 *  - parsed_options = null
 *  - other fields preserved from input item
 *
 * Does NOT mutate input.
 */
export function buildMultiBlankSavePayload(
  item: Record<string, unknown> | undefined | null,
  groups: BlankOptionGroup[],
  answerMap: BlankAnswerMap,
  stem: string,
  questionType: string = "multi_blank_choice",
): SavePayloadResult {
  const errors: string[] = [];

  // 1. Groups must have at least 2
  if (groups.length < 2) {
    errors.push("多空选择题至少需要 2 个空位");
    return { payload: null, errors, warnings: [] };
  }

  // Dedup first so subsequent checks operate on clean data
  const { groups: dedupedGroups, warnings, errors: dedupErrors } = deduplicateGroupOptions(groups);

  // 2. Group IDs non-empty and unique
  const groupIds = dedupedGroups.map((g) => g.id);
  for (let i = 0; i < groupIds.length; i++) {
    if (!groupIds[i].trim()) {
      errors.push(`空位 ${i + 1} 的 ID 为空`);
    }
  }
  if (new Set(groupIds).size !== groupIds.length) {
    errors.push("空位 ID 存在重复");
  }

  // 3. Each group has >= 2 options
  for (const group of dedupedGroups) {
    if (group.options.length < 2) {
      errors.push(`空位 ${group.id} 至少需要 2 个选项`);
    }
  }

  // 4. Option keys non-empty and unique per group (after dedup)
  for (const group of dedupedGroups) {
    const keys = group.options.map((o) => o.key).filter(Boolean);
    if (keys.length !== new Set(keys).size) {
      errors.push(`空位 ${group.id} 的选项 key 存在重复`);
    }
  }

  // 5. No conflicting duplicates
  if (dedupErrors.length > 0) {
    errors.push(...dedupErrors);
  }

  // 6-8. Validate answer map against deduped groups
  const validation = validateBlankAnswerMap(dedupedGroups, answerMap);
  if (!validation.valid) {
    errors.push(...validation.errors);
  }

  if (errors.length > 0) {
    return { payload: null, errors, warnings };
  }

  // Build canonical answer from answerMap
  const canonicalAnswer = serializeBlankAnswer(answerMap, groupIds);

  // Build parsed_content preserving existing fields
  const existingContent = (item?.parsed_content as Record<string, unknown>) ?? {};
  const newContent: Record<string, unknown> = {
    ...existingContent,
    blank_option_groups: dedupedGroups,
  };
  if (stem) {
    newContent.text = stem;
  }

  const payload: Record<string, unknown> = {
    question_type: questionType,
    answer: canonicalAnswer,
    parsed_options: null,
    parsed_content: newContent,
  };

  // Preserve subject_id, analysis from item
  if (item?.subject_id != null) {
    payload.subject_id = item.subject_id;
  }
  if (item?.parsed_analysis) {
    payload.analysis = item.parsed_analysis;
  }

  return { payload, errors: [], warnings };
}
