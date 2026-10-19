import { looksLikeProgrammingCode } from "@/lib/math-text";

export type ContentSegment = Record<string, unknown>;

export function contentRecord(content: unknown): ContentSegment {
  return content && typeof content === "object" && !Array.isArray(content)
    ? (content as ContentSegment)
    : {};
}

export function contentSegments(content: unknown): ContentSegment[] {
  const record = contentRecord(content);
  if (!Array.isArray(record.segments)) return [];
  return record.segments.filter(
    (segment): segment is ContentSegment =>
      Boolean(segment) && typeof segment === "object" && !Array.isArray(segment),
  );
}

export function segmentType(segment: ContentSegment | null | undefined): string {
  return segment && typeof segment === "object" && !Array.isArray(segment)
    ? String(segment.type ?? "").trim().toLowerCase()
    : "";
}

/** Only literal "image" segments are editable here; generated image segments
 * are handled by their dedicated renderers and editors. */
export function isPlainImageSegment(segment: ContentSegment): boolean {
  return segmentType(segment) === "image";
}

export function isCodeSegment(segment: ContentSegment): boolean {
  return segmentType(segment) === "code";
}

export function codeSegmentText(segment: ContentSegment): string {
  return String(segment.code ?? segment.text ?? "");
}

export function comparableText(value: unknown): string {
  return String(value ?? "").replace(/\r\n?/g, "\n").trim();
}

function visibleCodeSegmentText(segment: ContentSegment): string {
  const code = comparableText(codeSegmentText(segment));
  const caption = comparableText(segment.caption);
  return caption && code ? `${caption}\n${code}` : (caption || code);
}

export function canonicalStemAfterSegmentUpdate(
  content: ContentSegment,
  nextSegments: ContentSegment[],
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
  // Preserve identity for insert/delete operations; use the index only for
  // in-place replacement where the editor creates a new segment object.
  let nextSegment = nextSegments.find((segment) => segment === matchedSegment);
  if (!nextSegment && nextSegments.length === currentSegments.length) {
    const sameIndexSegment = nextSegments[matchedIndex];
    if (sameIndexSegment && isCodeSegment(sameIndexSegment)) {
      nextSegment = sameIndexSegment;
    }
  }

  // Legacy code-only records duplicated code into content.stem. Keep that
  // fallback synchronized, including clearing it when the code is deleted.
  return nextSegment && isCodeSegment(nextSegment)
    ? visibleCodeSegmentText(nextSegment)
    : "";
}

/** Text/newline segments carry the stem while option segments remain separate. */
export function isStemTextSegment(
  segment: ContentSegment | null | undefined,
): boolean {
  if (!segment || segment.option_key) return false;
  const type = segmentType(segment);
  return type === "text" || type === "newline";
}

function stemTextToSegments(text: string): ContentSegment[] {
  const lines = String(text ?? "").split("\n");
  const segments: ContentSegment[] = [];
  lines.forEach((line, index) => {
    if (line) segments.push({ type: "text", text: line });
    if (index < lines.length - 1) segments.push({ type: "newline" });
  });
  return segments;
}

function isMathWrapBoundary(left: string, right: string): boolean {
  const leftChar = left.match(/\S(?=\s*$)/)?.[0] ?? "";
  const rightChar = right.match(/^\s*(\S)/)?.[1] ?? "";
  const mathContinuationLeft = /[=<>≤≥≠≈→←±×÷+\-*/^_,:([{\\]/;
  const mathContinuationRight = /[=<>≤≥≠≈→←±×÷+\-*/^_,:)\]}]/;
  return mathContinuationLeft.test(leftChar) || mathContinuationRight.test(rightChar);
}

export function normalizeStemForEditing(value: string): string {
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

export function updateStemInContent(
  content: unknown,
  newStem: string,
): ContentSegment {
  const record = contentRecord(content);
  const next: ContentSegment = { ...record, stem: newStem, text: newStem };
  if (Array.isArray(record.segments)) {
    const segments = record.segments as ContentSegment[];
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

export function textFromContent(
  content: ContentSegment | string | null | undefined,
): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  const candidate = [content.stem, content.text, content.question, content.title]
    .find((value) => typeof value === "string" && value.length > 0);
  if (typeof candidate === "string") return candidate;

  // Segment-only records are valid; code/table/image segments are rendered
  // separately and must not be serialized as raw JSON into the stem.
  if (Array.isArray(content.segments)) {
    return content.segments
      .map((rawSegment) => {
        if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return "";
        const segment = rawSegment as ContentSegment;
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
 * Match the structured stem used by the detail renderer while retaining the
 * canonical text for text-only programming questions.
 */
export function textForStemEditor(
  content: ContentSegment | string | null | undefined,
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

  if (canonicalText && hasOnlyTextStemSegments && looksLikeProgrammingCode(canonicalText)) {
    return canonicalText;
  }

  let hasStemTextSegment = false;
  const segmentText = content.segments
    .map((rawSegment) => {
      if (!rawSegment || typeof rawSegment !== "object" || Array.isArray(rawSegment)) return "";
      const segment = rawSegment as ContentSegment;
      if (!isStemTextSegment(segment)) return "";
      const type = segmentType(segment);
      hasStemTextSegment = true;
      return type === "newline" ? "\n" : String(segment.text ?? "");
    })
    .join("");

  return hasStemTextSegment ? segmentText : canonicalText;
}

export function nonStemContentSegments(content: unknown): ContentSegment[] {
  return contentSegments(content).filter((segment) => !isStemTextSegment(segment));
}
