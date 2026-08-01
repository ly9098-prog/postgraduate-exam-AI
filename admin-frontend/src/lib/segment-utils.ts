/**
 * Segment editor pure functions extracted from the import review page.
 * All functions are immutable — they return new arrays rather than mutating.
 */

export type SegmentData = Record<string, unknown>;

export type EditableOption = {
  key: string;
  text: string;
  segments?: SegmentData[];
};

const IMAGE_SEGMENT_TYPES = ["image", "math_image", "table_image", "code_image"];
const TABLE_SEGMENT_TYPES = ["table", "table_markdown"];

/** Check if a type string is an image-type segment. */
export function isImageSegmentType(type: string): boolean {
  return IMAGE_SEGMENT_TYPES.includes(type.toLowerCase());
}

/** Check whether a segments array contains any visual (image-type) segments. */
export function hasVisualSegments(segs: SegmentData[] | null | undefined): boolean {
  if (!segs) return false;
  return segs.some((s) => isImageSegmentType(String(s.type ?? "")));
}


/** Check if a type string is a structured or legacy table segment. */
export function isTableSegmentType(type: string): boolean {
  return TABLE_SEGMENT_TYPES.includes(type.toLowerCase());
}

/** Check whether a segments array contains editable structured tables. */
export function hasTableSegments(segs: SegmentData[] | null | undefined): boolean {
  if (!segs) return false;
  return segs.some((s) => isTableSegmentType(String(s.type ?? "")));
}
/** Human-readable label for a segment type. */
export function getSegmentTypeLabel(type: string): string {
  const t = type.toLowerCase();
  if (t === "math_image") return "公式";
  if (t === "table" || t === "table_markdown") return "结构化表格";
  if (t === "table_image") return "表格";
  if (t === "code_image") return "代码";
  if (t === "newline") return "换行";
  if (t === "image") return "图片";
  return type;
}

/** Move a segment one position up (swap with previous). */
export function reorderSegmentUp(segs: SegmentData[], si: number): SegmentData[] {
  if (si <= 0 || si >= segs.length) return [...segs];
  const next = [...segs];
  [next[si - 1], next[si]] = [next[si], next[si - 1]];
  return next;
}

/** Move a segment one position down (swap with next). */
export function reorderSegmentDown(segs: SegmentData[], si: number): SegmentData[] {
  if (si < 0 || si >= segs.length - 1) return [...segs];
  const next = [...segs];
  [next[si], next[si + 1]] = [next[si + 1], next[si]];
  return next;
}

/** Drag-and-drop: move a segment from index `from` to index `to`. */
export function moveSegment(segs: SegmentData[], from: number, to: number): SegmentData[] {
  if (from < 0 || to < 0 || from >= segs.length || to >= segs.length || from === to) return [...segs];
  const next = [...segs];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** Delete the segment at the given index. Returns an empty array when the last item is removed. */
export function deleteSegmentAtIndex(segs: SegmentData[], index: number): SegmentData[] {
  return segs.filter((_, i) => i !== index);
}

/** Update a segment's option_key assignment and optionally set assignment_method. */
export function updateSegOptionKey(segs: SegmentData[], index: number, val: string): SegmentData[] {
  return segs.map((s, i) => {
    if (i !== index) return s;
    return {
      ...s,
      option_key: val || undefined,
      assignment_method: val && val !== s.option_key ? "manual_review" : s.assignment_method,
    };
  });
}

/** Replace a segment's image URL and mark assignment as manual_review. */
export function updateSegUrl(segs: SegmentData[], index: number, url: string): SegmentData[] {
  return segs.map((s, i) => {
    if (i !== index) return s;
    return { ...s, url, assignment_method: "manual_review" };
  });
}
