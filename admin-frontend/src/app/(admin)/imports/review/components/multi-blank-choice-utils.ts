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

export type BlankAnswerMap = Record<string, string>; // slotId -> key e.g. {"①": "B", "②": "D"}

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
 * Parse a multi-blank answer string into a {slotId: answerKey} map.
 *
 * Supports:
 *  - Canonical: ①:B;②:D
 *  - OCR circled: ①B、②D
 *  - Parenthesized: (1)B、(2)D
 *  - Numbered colon: 1:B,2:D
 *  - Chinese: 第1空B
 *  - Positional B,D (only when parts count matches groupIds.length)
 *
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

  // Try canonical "slot:value;slot:value" format
  for (const pair of a.split(/[;；]/)) {
    const m = pair.match(/^\s*(.+?)\s*[:：]\s*([A-Ha-h])\s*$/);
    if (m) map[m[1].trim()] = m[2].toUpperCase();
  }
  if (Object.keys(map).length > 0) return map;

  // Try OCR circled format ①B、②D
  const circledRe = /([①-⑳])\s*([A-Ha-h])/g;
  let cm: RegExpExecArray | null;
  while ((cm = circledRe.exec(a)) !== null) map[cm[1]] = cm[2].toUpperCase();
  if (Object.keys(map).length > 0) return map;

  // Try parenthesized (1)B、(2)D
  const parenRe = /[(（]\s*(\d+)\s*[)）]\s*([A-Ha-h])/g;
  let pm: RegExpExecArray | null;
  while ((pm = parenRe.exec(a)) !== null) map[pm[1]] = pm[2].toUpperCase();
  if (Object.keys(map).length > 0) return map;

  // Try 1:B,2:D format
  const numColonRe = /(\d+)\s*[:：]\s*([A-Ha-h])/g;
  let nm: RegExpExecArray | null;
  while ((nm = numColonRe.exec(a)) !== null) map[nm[1]] = nm[2].toUpperCase();
  if (Object.keys(map).length > 0) return map;

  // Try 第1空B
  const cnRe = /第\s*(\d+)\s*空\s*([A-Ha-h])/g;
  let cnm: RegExpExecArray | null;
  while ((cnm = cnRe.exec(a)) !== null) map[cnm[1]] = cnm[2].toUpperCase();
  if (Object.keys(map).length > 0) return map;

  // Positional B,D only when parts count matches groupIds.length
  const parts = a
    .split(/[，,、\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-H]$/.test(s));
  if (parts.length === groupIds.length && parts.length >= 2) {
    parts.forEach((v, i) => {
      map[groupIds[i]] = v;
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

/**
 * Validate that an answer map covers every group with a valid option key.
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
      if (!validKeys.has(selected)) {
        errors.push(`空 ${group.id} 的答案 "${selected}" 不在选项内`);
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
