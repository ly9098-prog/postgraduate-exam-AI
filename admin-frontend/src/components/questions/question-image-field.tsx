"use client";

import { useRef, useState } from "react";
import { ImagePlus, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type { AdminQuestion } from "@/lib/api/types";
import { resolveAssetUrl } from "@/lib/asset-url";
import { cn } from "@/lib/utils";

const ACCEPT = "image/png,image/jpeg,image/webp";
const ACCEPTED_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_SIZE = 10 * 1024 * 1024;

type QuestionImageFieldProps = {
  questionId: number;
  /** "stem" or "option:A" — the backend image target. */
  target: string;
  /** Current image URL (root-relative asset path). */
  valueUrl?: string | null;
  canDelete?: boolean;
  addLabel?: string;
  /** Set when the parent edit form has unsaved changes → confirm before writing. */
  dirty?: boolean;
  /** Persist the parent edit form before an immediate image mutation. */
  beforeDirtyMutation?: () => Promise<boolean>;
  /** "hero" (default): large stem image that fills the insert area; "row": compact square for option rows. */
  variant?: "hero" | "row";
  onMutated: (question: AdminQuestion) => void;
};

/**
 * Custom (non-native) image control for a question stem or an option:
 * hidden file input triggered by a styled button, inline preview with a
 * hover replace/delete overlay, and a confirm dialog before writing.
 * When an image exists, it is shown large and *replaces* the add/upload
 * affordance (hero) or as a compact square in the option row.
 * Writes immediately via POST/DELETE /questions/{id}/images.
 */
export function QuestionImageField({
  questionId,
  target,
  valueUrl,
  canDelete = true,
  addLabel = "添加图片",
  dirty = false,
  beforeDirtyMutation,
  variant = "hero",
  onMutated,
}: QuestionImageFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  // pending confirm action: "upload" keeps a picked file; "delete" removes valueUrl
  const [pendingConfirm, setPendingConfirm] = useState<null | "upload" | "delete">(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const isRow = variant === "row";
  const resolved = valueUrl ? resolveAssetUrl(valueUrl) : null;
  const showImage = previewUrl ?? resolved;
  const alt = target === "stem" ? "题干图片" : `选项 ${target.slice("option:".length)} 图片`;

  const triggerPicker = () => inputRef.current?.click();

  const handleFilePicked = (file: File | null | undefined) => {
    setError(null);
    if (!file) return;
    if (!ACCEPTED_MIME_TYPES.has(file.type)) {
      setError("仅支持 PNG、JPEG 或 WebP 图片");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    if (file.size > MAX_SIZE) {
      setError("图片不能超过 10MB");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    if (dirty) {
      setPendingFile(file);
      setPendingConfirm("upload");
      return;
    }
    void upload(file);
  };

  const upload = async (file: File) => {
    const objectUrl = URL.createObjectURL(file);
    setPreviewUrl(objectUrl);
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("target", target);
      if (valueUrl) fd.append("replace_url", valueUrl);
      const question = await apiRequest<AdminQuestion>(`/questions/${questionId}/images`, {
        method: "POST",
        body: fd,
      });
      onMutated(question);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
      URL.revokeObjectURL(objectUrl);
      setPreviewUrl(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const prepareParentIfNeeded = async (): Promise<boolean> => {
    if (!dirty) return true;
    if (!beforeDirtyMutation) {
      setError("请先保存当前题目修改，再执行图片操作。");
      return false;
    }
    setPreparing(true);
    try {
      return await beforeDirtyMutation();
    } catch (err) {
      setError(getErrorMessage(err));
      return false;
    } finally {
      setPreparing(false);
    }
  };

  const confirmUpload = async () => {
    const file = pendingFile;
    if (!file) {
      setPendingConfirm(null);
      return;
    }
    const ready = await prepareParentIfNeeded();
    if (!ready) {
      setPendingConfirm(null);
      setPendingFile(null);
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setPendingConfirm(null);
    setPendingFile(null);
    await upload(file);
  };

  const confirmDelete = async () => {
    if (!valueUrl) {
      setPendingConfirm(null);
      return;
    }
    const ready = await prepareParentIfNeeded();
    if (!ready) {
      setPendingConfirm(null);
      return;
    }
    setPendingConfirm(null);
    setBusy(true);
    setError(null);
    try {
      const question = await apiRequest<AdminQuestion>(`/questions/${questionId}/images`, {
        method: "DELETE",
        body: JSON.stringify({ target, url: valueUrl }),
        headers: { "Content-Type": "application/json" },
      });
      onMutated(question);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const confirmMessage =
    pendingConfirm === "delete"
      ? `${dirty ? "当前表单有未保存修改。继续后会先保存这些修改，再删除图片；保存失败则不会删除。\n" : ""}将移除该图片引用；若无其他题目引用，图片文件也会一并删除。`
      : dirty
        ? "当前表单有未保存修改。继续后会先保存这些修改，再上传图片；保存失败则不会上传。"
        : null;

  const overlayButtons = (
    <>
      <button
        type="button"
        onClick={triggerPicker}
        title="替换图片"
        aria-label="替换图片"
        className={cn(
          "flex items-center justify-center rounded-full bg-white/90 text-[var(--color-primary-dark)] shadow-sm transition hover:bg-white",
          isRow ? "h-5 w-5" : "h-8 w-8",
        )}
      >
        <RefreshCw className={isRow ? "h-3 w-3" : "h-4 w-4"} />
      </button>
      {canDelete ? (
        <button
          type="button"
          onClick={() => setPendingConfirm("delete")}
          title="删除图片"
          aria-label="删除图片"
          className={cn(
            "flex items-center justify-center rounded-full bg-white/90 text-red-500 shadow-sm transition hover:bg-white",
            isRow ? "h-5 w-5" : "h-8 w-8",
          )}
        >
          <Trash2 className={isRow ? "h-3 w-3" : "h-4 w-4"} />
        </button>
      ) : null}
    </>
  );

  return (
    <div className={isRow ? "shrink-0" : "w-full"}>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handleFilePicked(e.target.files?.[0])}
      />

      {showImage ? (
        isRow ? (
          /* ── Row: compact square thumbnail with hover replace/delete ── */
          <div className="group/img relative h-9 w-9 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <img src={showImage} alt={alt} className="h-full w-full object-cover" />
            <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/45 opacity-0 transition-opacity duration-150 group-hover/img:opacity-100">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin text-white" /> : overlayButtons}
            </div>
          </div>
        ) : (
          /* ── Hero: large stem image fills the insert area ── */
          <div className="group/img relative overflow-hidden rounded-lg border border-slate-200 bg-white">
            <img
              src={showImage}
              alt={alt}
              className="mx-auto max-h-72 w-auto max-w-full object-contain"
            />
            <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/40 opacity-0 transition-opacity duration-150 group-hover/img:opacity-100">
              {busy ? <Loader2 className="h-5 w-5 animate-spin text-white" /> : overlayButtons}
            </div>
          </div>
        )
      ) : isRow ? (
        /* ── Row: compact square add button ── */
        <button
          type="button"
          onClick={triggerPicker}
          disabled={busy}
          title={addLabel}
          aria-label={addLabel}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-slate-400 transition hover:border-slate-400 hover:bg-slate-50 hover:text-slate-700 disabled:cursor-wait disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
        </button>
      ) : (
        /* ── Hero: dashed upload area when no image ── */
        <button
          type="button"
          onClick={triggerPicker}
          disabled={busy}
          className="flex h-24 w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 text-slate-400 transition hover:border-slate-400 hover:bg-slate-50 hover:text-slate-700 disabled:cursor-wait disabled:opacity-60"
        >
          {busy ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <ImagePlus className="h-5 w-5" />
          )}
          <span className="text-xs font-medium leading-none">{busy ? "上传中..." : addLabel}</span>
        </button>
      )}

      {error ? (
        <p className="mt-1.5 text-xs text-red-600" role="alert">
          {error}
        </p>
      ) : null}

      <ConfirmDialog
        open={pendingConfirm !== null}
        title={pendingConfirm === "delete" ? "删除图片" : "确认上传图片"}
        description={confirmMessage ?? undefined}
        danger={pendingConfirm === "delete"}
        confirmText={
          pendingConfirm === "delete"
            ? (dirty ? "保存并删除" : "删除")
            : (dirty ? "保存并上传" : "继续上传")
        }
        loading={busy || preparing}
        onConfirm={pendingConfirm === "delete" ? confirmDelete : confirmUpload}
        onCancel={() => {
          setPendingConfirm(null);
          setPendingFile(null);
        }}
      />
    </div>
  );
}
