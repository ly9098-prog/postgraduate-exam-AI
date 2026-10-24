/** Pure helpers for the segment-image replace flow in the import review page. */

import type { Dispatch, SetStateAction } from "react";

import { updateSegUrl } from "@/lib/segment-utils";

export type SegmentUploadResult = { url: string; filename: string };

export type SegmentReplaceOptions = {
  canWrite: boolean;
  previewId: number | null;
  setSegmentUploading: Dispatch<SetStateAction<number>>;
  setEditedSegments: Dispatch<SetStateAction<Array<Record<string, unknown>> | null>>;
  updateMessage: (message: string) => void;
  uploadSegmentImage: (file: File) => Promise<SegmentUploadResult>;
};

/** Execute a segment-image replacement, guarding on canWrite and preview identity. */
export async function executeSegmentReplace(
  si: number,
  file: File,
  options: SegmentReplaceOptions,
): Promise<void> {
  if (!file || !options.canWrite) return;
  const targetPreviewId = options.previewId;
  options.setSegmentUploading(si);
  try {
    const result = await options.uploadSegmentImage(file);
    if (options.previewId !== targetPreviewId) return;
    options.setEditedSegments((prev) => {
      if (!prev || si >= prev.length) return prev;
      return updateSegUrl(prev, si, result.url);
    });
    options.updateMessage(`图片已替换：${result.filename}`);
  } catch (err) {
    options.updateMessage(err instanceof Error ? err.message : "图片上传失败");
  } finally {
    options.setSegmentUploading(-1);
  }
}

/** Extract the selected file and index from a change event, then reset the input. */
export function resolveSegmentFileChange(
  e: React.ChangeEvent<HTMLInputElement>,
  currentIndex: number,
): { file: File | null; index: number } {
  const file = e.target.files?.[0] ?? null;
  e.target.value = "";
  return { file, index: currentIndex };
}
