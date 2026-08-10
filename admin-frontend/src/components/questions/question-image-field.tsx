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
const MAX_SIZE = 10 * 1024 * 1024;

const DIRTY_WARNING = "表单有未保存的修改，继续将立即保存该操作并刷新表单，未保存的修改将被丢弃。";

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
  /** Compact row-friendly variant for option rows. */
  compact?: boolean;
  onMutated: (question: AdminQuestion) => void;
};

/**
 * Custom (non-native) image control for a question stem or an option:
 * hidden file input triggered by a styled button, inline preview with a
 * hover replace/delete overlay, and a confirm dialog before writing.
 * Writes immediately via POST/DELETE /questions/{id}/images.
 */
export function QuestionImageField({
  questionId,
  target,
  valueUrl,
  canDelete = true,
  addLabel = "添加图片",
  dirty = false,
  compact = false,
  onMutated,
}: QuestionImageFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  // pending confirm action: "upload" keeps a picked file; "delete" removes valueUrl
  const [pendingConfirm, setPendingConfirm] = useState<null | "upload" | "delete">(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const resolved = valueUrl ? resolveAssetUrl(valueUrl) : null;
  const showImage = previewUrl ?? resolved;

  const triggerPicker = () => inputRef.current?.click();

  const handleFilePicked = (file: File | null | undefined) => {
    setError(null);
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("仅支持图片文件（PNG/JPEG/WebP）");
      return;
    }
    if (file.size > MAX_SIZE) {
      setError("图片不能超过 10MB");
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

  const confirmUpload = () => {
    setPendingConfirm(null);
    if (pendingFile) void upload(pendingFile);
    setPendingFile(null);
  };

  const confirmDelete = () => {
    setPendingConfirm(null);
    if (!valueUrl) return;
    setBusy(true);
    setError(null);
    void (async () => {
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
    })();
  };

  const confirmMessage =
    pendingConfirm === "delete"
      ? `${dirty ? `${DIRTY_WARNING}\n` : ""}将移除该图片引用；若无其他题目引用，图片文件也会一并删除。`
      : dirty
        ? DIRTY_WARNING
        : null;

  return (
    <div className="w-full">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handleFilePicked(e.target.files?.[0])}
      />

      {showImage ? (
        <div className={cn("group/img relative overflow-hidden rounded-xl border border-[var(--color-border)]/60 bg-white", compact ? "h-11 w-16" : "")}>
          <img
            src={showImage}
            alt="题干/选项图片"
            className={cn("object-cover", compact ? "h-11 w-16" : "max-w-full object-contain")}
            style={compact ? undefined : { maxHeight: "140px" }}
          />
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/45 opacity-0 transition-opacity group-hover/img:opacity-100">
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin text-white" />
            ) : (
              <>
                <button
                  type="button"
                  onClick={triggerPicker}
                  title="替换图片"
                  aria-label="替换图片"
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-white/90 text-[var(--color-primary-dark)] shadow-sm transition hover:bg-white"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
                {canDelete ? (
                  <button
                    type="button"
                    onClick={() => setPendingConfirm("delete")}
                    title="删除图片"
                    aria-label="删除图片"
                    className="flex h-7 w-7 items-center justify-center rounded-full bg-white/90 text-red-500 shadow-sm transition hover:bg-white"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={triggerPicker}
          disabled={busy}
          className={cn(
            "flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--porcelain)]/60 text-[var(--color-text-hint)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)] disabled:cursor-wait disabled:opacity-60",
            compact
              ? "h-11 w-16 flex-col gap-0.5"
              : "h-24 w-full flex-col gap-1.5",
          )}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ImagePlus className="h-4 w-4" />
          )}
          <span className="text-[10px] font-medium leading-none">{busy ? "上传中..." : addLabel}</span>
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
        confirmText={pendingConfirm === "delete" ? "删除" : "继续上传"}
        loading={busy}
        onConfirm={pendingConfirm === "delete" ? confirmDelete : confirmUpload}
        onCancel={() => {
          setPendingConfirm(null);
          setPendingFile(null);
        }}
      />
    </div>
  );
}
