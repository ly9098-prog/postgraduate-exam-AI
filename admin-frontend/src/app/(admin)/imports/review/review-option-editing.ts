import type { EditState } from "./review-edit-state";

type ReviewOptions = EditState["options"];

export function updateReviewOptionText(options: ReviewOptions, index: number, text: string): ReviewOptions {
  const next = [...options];
  next[index] = { ...next[index], text };
  return next;
}

export function removeReviewOptionSegment(
  options: ReviewOptions, index: number, segmentIndex: number,
): ReviewOptions {
  const next = [...options];
  const segments = next[index].segments?.filter((_, current) => current !== segmentIndex) ?? [];
  next[index] = { ...next[index], segments: segments.length > 0 ? segments : undefined };
  return next;
}
