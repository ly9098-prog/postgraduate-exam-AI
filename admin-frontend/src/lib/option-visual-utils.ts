/**
 * Pure functions for extracting and normalizing image-type option data
 * from parsed_content / parsed_options JSON columns.
 *
 * Zero React dependencies — testable with Vitest.
 */

import { isImageSegmentType } from "@/lib/segment-utils";

// ─── Types ───────────────────────────────────────────────────────

export type OptionVisualSegment = {
  type: string;
  url: string;
  optionKey?: string;
  regionType?: string;
  regionId?: string;
  semanticRole?: string;
  alt?: string;
  bbox?: number[];
  coordinateSpace?: string;
  assetHash?: string;
  cropVersion?: string;
  requiresReview?: boolean;
};

export type OptionVisualModel = {
  /** Classification of how this question's options should be rendered. */
  mode: "none" | "option_group" | "option_images" | "placeholder_missing" | "unknown_visual";

  /** The single group image containing all option diagrams (option_group mode). */
  groupImage?: OptionVisualSegment;

  /** Per-option-key images (option_images mode). */
  optionImages: Record<string, OptionVisualSegment[]>;

  /** Option keys whose parsed_options value is an image placeholder string. */
  placeholderKeys: string[];

  /** Option keys expected to have images but none found. */
  missingImageKeys: string[];

  /** True when real visual data exists (option_group or option_images with images). */
  hasValidVisual: boolean;

  /** Expected A/B/C/D keys from the data. */
  expectedOptionKeys: string[];

  /** Keys actually detected in the data. */
  detectedOptionKeys: string[];

  /**
   * Stable segment identifiers consumed by this model so the caller can
   * filter them out of the generic segments display.
   * Priority: region_id > asset_hash > fingerprint > index
   */
  consumedSegmentIds: string[];

  /** True when detection relied on legacy/fallback heuristics. */
  legacy: boolean;

  /** Human-readable issues found during extraction. */
  issues: string[];
};

// ─── Placeholder detection ───────────────────────────────────────

const PLACEHOLDER_PATTERNS = [
  /图片\s*选项\s*[A-D]/,
  /原题图已内嵌/,
  /见原图/,
  /图略/,
  /\[.*?图片.*?\]/,
  /【.*?图片.*?】/,
  /option\s*image\s*placeholder/i,
  /图形\s*选项\s*[A-D]/,
  /[图片图形]\s*缺失/,
  /此题为图片题/,
];

/**
 * Check whether a value is a known Chinese image-option placeholder.
 * Accepts strings only; non-string values return false.
 */
export function isImageOptionPlaceholder(text: unknown): boolean {
  if (typeof text !== "string") return false;
  const t = text.trim();
  if (!t) return false;
  return PLACEHOLDER_PATTERNS.some((re) => re.test(t));
}

// ─── Segment ID helpers ──────────────────────────────────────────

function segmentId(seg: Record<string, unknown>, index: number): string {
  const rid = seg.region_id as string | undefined;
  if (rid && typeof rid === "string" && rid.trim()) return rid;
  const hash = seg.asset_hash as string | undefined;
  if (hash && typeof hash === "string" && hash.trim()) return `ah:${hash}`;
  // Fingerprint from stable properties
  const type = String(seg.type ?? "");
  const url = String(seg.url ?? "");
  const bbox = Array.isArray(seg.bbox) ? JSON.stringify(seg.bbox) : "";
  const fp = `${type}|${url}|${bbox}`;
  if (fp.length > 3) return `fp:${sha256like(fp)}`;
  return `idx:${index}`;
}

/** Deterministic short hash for fingerprinting (not cryptographic). */
function sha256like(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

// ─── Extract model ───────────────────────────────────────────────

const VALID_OPTION_KEYS = ["A", "B", "C", "D", "E", "F", "G", "H"];

/** Build an OptionVisualSegment from a raw segment record. */
function toSegment(raw: Record<string, unknown>): OptionVisualSegment {
  return {
    type: String(raw.type ?? ""),
    url: String(raw.url ?? ""),
    optionKey: raw.option_key as string | undefined,
    regionType: String(raw.region_type ?? ""),
    regionId: String(raw.region_id ?? ""),
    semanticRole: String(raw.semantic_role ?? ""),
    alt: String(raw.alt ?? ""),
    bbox: Array.isArray(raw.bbox) ? (raw.bbox as number[]) : undefined,
    coordinateSpace: String(raw.coordinate_space ?? ""),
    assetHash: String(raw.asset_hash ?? ""),
    cropVersion: String(raw.crop_version ?? ""),
    requiresReview: raw.requires_review === true,
  };
}

/**
 * Extract an OptionVisualModel from the raw parsed_content and parsed_options.
 *
 * Cascading detection priority:
 * 1. Rich option segments (in parsed_options entries)
 * 2. Explicit option images (in parsed_content.segments with option_key)
 * 3. Explicit option_group region
 * 4. Legacy option_group from region_id fallback
 * 5. Strict legacy Plan B heuristic
 * 6. Placeholder text detected
 * 7. Default: none
 */
export function extractOptionVisualModel(
  parsedContent: Record<string, unknown> | null | undefined,
  parsedOptions: Record<string, unknown> | null | undefined,
): OptionVisualModel {
  const consumedSegmentIds: string[] = [];
  const issues: string[] = [];
  const optionImages: Record<string, OptionVisualSegment[]> = {};
  const placeholderKeys: string[] = [];
  const missingImageKeys: string[] = [];
  let mode: OptionVisualModel["mode"] = "none";
  let groupImage: OptionVisualSegment | undefined;
  let legacy = false;

  const contentSegments = (parsedContent?.segments as Record<string, unknown>[] | undefined) ?? [];
  const optionKeys = parsedOptions ? Object.keys(parsedOptions) : [];
  const expectedKeys = optionKeys.filter((k) => VALID_OPTION_KEYS.includes(k));

  // ── 1. Rich option segments (in parsed_options entries) ──
  let foundRich = false;
  if (parsedOptions) {
    for (const [key, value] of Object.entries(parsedOptions)) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const v = value as Record<string, unknown>;
        const segs = v.segments as Record<string, unknown>[] | undefined;
        if (segs && segs.length > 0) {
          foundRich = true;
          const visualSegs = segs
            .filter((s) => isImageSegmentType(String(s.type ?? "")) && String(s.url ?? "").trim())
            .map((s) => ({ ...toSegment(s), optionKey: key }));
          if (visualSegs.length > 0) {
            optionImages[key] = [...(optionImages[key] ?? []), ...visualSegs];
            visualSegs.forEach((vs) => {
              const id = segmentId(vs as unknown as Record<string, unknown>, contentSegments.indexOf(vs as unknown as Record<string, unknown>));
              if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);
            });
          }
        }
      }
    }
  }
  if (foundRich) {
    mode = "option_images";
  }

  // ── 2. Explicit option images (parsed_content.segments with option_key) ──
  if (mode === "none" && contentSegments.length > 0) {
    let foundOptionImages = false;
    for (let i = 0; i < contentSegments.length; i++) {
      const seg = contentSegments[i];
      const optKey = seg.option_key as string | undefined;
      if (
        optKey &&
        VALID_OPTION_KEYS.includes(optKey) &&
        isImageSegmentType(String(seg.type ?? "")) &&
        String(seg.url ?? "").trim()
      ) {
        foundOptionImages = true;
        const vs = { ...toSegment(seg), optionKey: optKey };
        optionImages[optKey] = [...(optionImages[optKey] ?? []), vs];
        const id = segmentId(seg, i);
        if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);
      }
    }
    if (foundOptionImages) {
      mode = "option_images";
    }
  }

  // ── 3. Explicit option_group region_type ──
  if (mode === "none" && contentSegments.length > 0) {
    for (let i = 0; i < contentSegments.length; i++) {
      const seg = contentSegments[i];
      const rt = String(seg.region_type ?? "");
      const url = String(seg.url ?? "").trim();
      if (rt === "option_group" && isImageSegmentType(String(seg.type ?? "")) && url) {
        const expectedCount = (seg.expected_option_count as number | undefined) ?? 0;
        const detectedCount = (seg.detected_option_count as number | undefined) ?? 0;
        const placement = String(seg.placement ?? "");

        if (expectedCount !== 4 || detectedCount !== 4) {
          issues.push(`option_group invalid counts: expected=${expectedCount} detected=${detectedCount}`);
        }
        if (placement !== "before_options") {
          issues.push(`option_group unexpected placement: ${placement}`);
        }

        groupImage = toSegment(seg);
        mode = "option_group";
        const id = segmentId(seg, i);
        if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);
        break; // first option_group segment wins
      }
    }
  }

  // ── 4. Legacy fallback (region_id contains "option_group") ──
  if (mode === "none" && contentSegments.length > 0) {
    for (let i = 0; i < contentSegments.length; i++) {
      const seg = contentSegments[i];
      const rid = String(seg.region_id ?? "");
      const url = String(seg.url ?? "").trim();
      // Only match if region_type is NOT explicitly set to something else
      const rt = String(seg.region_type ?? "");
      if (rt !== "option_group" && rid.includes("option_group") && isImageSegmentType(String(seg.type ?? "")) && url) {
        legacy = true;
        issues.push("legacy_region_type_fallback: region_id used instead of region_type");
        groupImage = { ...toSegment(seg), requiresReview: true };
        mode = "option_group";
        const id = segmentId(seg, i);
        if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);

        // Verify counts if available
        const expectedCount = (seg.expected_option_count as number | undefined) ?? 0;
        const detectedCount = (seg.detected_option_count as number | undefined) ?? 0;
        if (expectedCount !== 4 || detectedCount !== 4) {
          issues.push(`legacy option_group missing expected/detected option counts`);
        }
        break;
      }
    }
  }

  // ── 5. Strict legacy Plan B heuristic ──
  if (mode === "none" && expectedKeys.length > 0 && contentSegments.length > 0) {
    const allEmpty = expectedKeys.every((k) => {
      const v = parsedOptions?.[k];
      return typeof v === "string" && v.trim() === "";
    });
    const hasLegacyPlaceholders = !!(parsedContent as Record<string, unknown>)?.legacy_option_placeholders;

    if (allEmpty || hasLegacyPlaceholders) {
      // Find a suitable content image
      for (let i = 0; i < contentSegments.length; i++) {
        const seg = contentSegments[i];
        const sr = String(seg.semantic_role ?? "");
        const url = String(seg.url ?? "").trim();
        if (
          (sr === "content_image" || hasLegacyPlaceholders) &&
          isImageSegmentType(String(seg.type ?? "")) &&
          url
        ) {
          const expectedCount = (seg.expected_option_count as number | undefined) ?? 0;
          const detectedCount = (seg.detected_option_count as number | undefined) ?? 0;
          const placement = String(seg.placement ?? "");

          // Strict criteria
          const countOk = expectedCount === 4 && detectedCount === 4;
          const placementOk = placement === "before_options";

          if (countOk && placementOk) {
            legacy = true;
            issues.push("legacy_plan_b_heuristic: parsed_options cleared with option_group content image");
            groupImage = { ...toSegment(seg), requiresReview: true };
            mode = "option_group";
            const id = segmentId(seg, i);
            if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);
            break;
          } else {
            issues.push(
              `option_group heuristic failed: counts=${expectedCount}/${detectedCount} placement=${placement}`,
            );
            mode = "unknown_visual";
            legacy = true;
            const id = segmentId(seg, i);
            if (!consumedSegmentIds.includes(id)) consumedSegmentIds.push(id);
            break;
          }
        }
      }
      if (mode === "none" && allEmpty) {
        // All parsed_options empty but no content image → placeholder_missing
        // (This means the old data was cleared but no image was generated)
        mode = "unknown_visual";
        legacy = true;
        missingImageKeys.push(...expectedKeys);
        issues.push("parsed_options empty with no content image — unknown state");
      }
    }
  }

  // ── 6. Placeholder text detected ──
  if (mode === "none" && parsedOptions) {
    let hasPlaceholder = false;
    for (const [key, value] of Object.entries(parsedOptions)) {
      if (VALID_OPTION_KEYS.includes(key) && isImageOptionPlaceholder(value)) {
        placeholderKeys.push(key);
        missingImageKeys.push(key);
        hasPlaceholder = true;
      }
    }
    if (hasPlaceholder) {
      mode = "placeholder_missing";
    }
  }

  // ── Populate remaining fields ──
  const detectedKeys = new Set<string>();
  if (groupImage) {
    expectedKeys.forEach((k) => detectedKeys.add(k));
  }
  Object.keys(optionImages).forEach((k) => detectedKeys.add(k));

  const nonPlaceholderTextKeys = expectedKeys.filter((k) => {
    const v = parsedOptions?.[k];
    return typeof v === "string" && v.trim() !== "" && !isImageOptionPlaceholder(v);
  });
  if (mode === "none" && nonPlaceholderTextKeys.length > 0) {
    // Normal text options — no visual mode needed
  }

  // Detect duplicate region_ids in consumedSegmentIds
  const seen = new Map<string, number>();
  consumedSegmentIds.forEach((id) => {
    seen.set(id, (seen.get(id) ?? 0) + 1);
  });
  seen.forEach((count, id) => {
    if (count > 1 && !id.startsWith("idx:")) {
      issues.push(`duplicate consumedSegmentId: ${id} (count=${count})`);
    }
  });

  return {
    mode,
    groupImage,
    optionImages,
    placeholderKeys,
    missingImageKeys,
    hasValidVisual: mode === "option_group" || mode === "option_images",
    expectedOptionKeys: expectedKeys,
    detectedOptionKeys: Array.from(detectedKeys),
    consumedSegmentIds,
    legacy,
    issues,
  };
}

/**
 * Normalize option text for display:
 * - Image placeholders → ""
 * - Empty/null/undefined → ""
 * - Normal text → as-is
 */
export function normalizeOptionTextForDisplay(text: string | null | undefined): string {
  if (!text) return "";
  if (isImageOptionPlaceholder(text)) return "";
  return text;
}
