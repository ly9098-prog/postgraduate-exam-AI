"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, ExternalLink, ImageIcon, AlertCircle, Check, Loader2, RefreshCw, X, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import { formatChinaDateTime } from "@/lib/time";
import type { FormulaGraphAsset } from "@/lib/api/types";
import { resolveAssetUrl } from "@/lib/asset-url";

type Props = {
  cardId: number;
  canUpdate: boolean;
};

function getDisplayUrl(asset: FormulaGraphAsset): string {
  const base = resolveAssetUrl(asset.image_url);
  if (!base) return base;
  const ts = asset.updated_at || asset.checksum || "";
  if (!ts) return base;
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}v=${encodeURIComponent(ts)}`;
}

function formatDt(d: string | null | undefined) {
  return formatChinaDateTime(d);
}

function AltDescEditor({
  asset, cardId,
}: {
  asset: FormulaGraphAsset;
  cardId: number;
}) {
  const queryClient = useQueryClient();
  const [altText, setAltText] = useState(asset.alt_text || "");
  const [description, setDescription] = useState(asset.description || "");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveMsgType, setSaveMsgType] = useState<"success" | "error">("success");
  const [dirty, setDirty] = useState(false);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<FormulaGraphAsset>(
        `/formulas/${cardId}/graph-assets/${asset.id}/metadata`,
        {
          method: "PUT",
          body: JSON.stringify({ alt_text: altText || null, description: description || null }),
        },
      ),
    onSuccess: () => {
      setSaveMsgType("success");
      setSaveMsg("图像说明已保存");
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
    },
    onError: (e) => {
      setSaveMsgType("error");
      setSaveMsg(e instanceof Error ? e.message : "保存失败");
    },
  });

  const charCount = (s: string) => s.replace(/\s/g, "").length;

  return (
    <div className="space-y-2 rounded-lg border border-[var(--color-border-light)] bg-white/70 px-3 py-2.5 text-xs">
      {/* alt_text */}
      <div>
        <label className="flex items-center justify-between text-[var(--color-text-hint)]">
          <span>替代文本 (alt text)</span>
          <span className={charCount(altText) > 100 ? "text-amber-500" : ""}>{charCount(altText)}字</span>
        </label>
        <input
          className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
          placeholder="图片加载失败时显示的替代文本"
          value={altText}
          onChange={(e) => { setAltText(e.target.value); setDirty(true); }}
          disabled={saveMutation.isPending}
        />
      </div>
      {/* description */}
      <div>
        <label className="flex items-center justify-between text-[var(--color-text-hint)]">
          <span>详细说明 (description)</span>
          <span className={charCount(description) > 300 ? "text-amber-500" : ""}>{charCount(description)}字</span>
        </label>
        <textarea
          className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
          rows={3}
          placeholder="用于 SEO 和管理端参考的详细说明"
          value={description}
          onChange={(e) => { setDescription(e.target.value); setDirty(true); }}
          disabled={saveMutation.isPending}
        />
      </div>
      {saveMsg && (
        <p className={`text-[11px] ${saveMsgType === "success" ? "text-[var(--color-success)]" : "text-red-500"}`}>
          {saveMsg}
          <button type="button" className="ml-1" onClick={() => setSaveMsg(null)}>✕</button>
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" onClick={() => saveMutation.mutate()} disabled={!dirty || saveMutation.isPending}>
          {saveMutation.isPending ? <><Loader2 className="h-3 w-3 animate-spin" /> 保存中</> : <><Save className="h-3 w-3" /> 保存</>}
        </Button>
        {dirty && <span className="text-[10px] text-amber-500">有未保存的修改</span>}
      </div>
    </div>
  );
}

function PendingUploadPanel({
  file,
  previewUrl,
  replacing,
  pending,
  onCancel,
  onSave,
}: {
  file: File;
  previewUrl: string;
  replacing: boolean;
  pending: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-primary)]/25 bg-[var(--color-primary-light)]/35 p-3 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex h-16 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <img src={previewUrl} alt="待上传图片预览" className="h-full w-full object-contain" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-[var(--color-primary-dark)]">待保存图片</span>
              <span className="rounded-md bg-white/80 px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-hint)]">
                {replacing ? "将替换当前手工图" : "上传后立即生效"}
              </span>
            </div>
            <p className="mt-1 truncate text-xs font-medium text-[var(--ink)]">{file.name}</p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">{(file.size / 1024 / 1024).toFixed(2)} MB · PNG / JPEG / WebP</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:justify-end">
          <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            <X className="h-3.5 w-3.5" /> 取消
          </Button>
          <Button type="button" size="sm" onClick={onSave} disabled={pending}>
            {pending ? (
              <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 保存中…</>
            ) : (
              <><Save className="h-3.5 w-3.5" /> 保存图片</>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function FormulaGraphAssetPanel({ cardId, canUpdate }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"success" | "error">("success");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showReplaceConfirm, setShowReplaceConfirm] = useState(false);

  // Local preview state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");

  // Image load error
  const [imageLoadError, setImageLoadError] = useState(false);

  // Clean up object URL on unmount or file change
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  // Load assets
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-formula-graph-assets", cardId],
    queryFn: () => apiRequest<{ items: FormulaGraphAsset[]; effective: FormulaGraphAsset | null }>(
      `/formulas/${cardId}/graph-assets`,
    ),
    enabled: !!cardId,
  });

  const effective = data?.effective ?? null;
  const assets = data?.items ?? [];
  const hasUploaded = assets.some((a) => a.source_type === "uploaded");
  const hasGenerated = assets.some((a) => a.source_type === "generated");
  const hasTemplate = assets.some((a) => a.source_type === "template");

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.set("file", file);
      return apiRequest<FormulaGraphAsset>(`/formulas/${cardId}/graph-assets/upload`, {
        method: "POST",
        body: formData,
      });
    },
    onSuccess: () => {
      setMessageType("success");
      setMessage("函数图像上传成功");
      clearFileSelection();
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => {
      setMessageType("error");
      const errMsg = e instanceof Error ? e.message : "函数图像上传失败，请稍后重试";
      setMessage(errMsg);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async () => {
      return apiRequest<{ status: string }>(
        `/formulas/${cardId}/graph-assets/uploaded`,
        { method: "DELETE" },
      );
    },
    onSuccess: () => {
      setMessageType("success");
      setMessage(hasTemplate ? "已删除手工上传图片，将回退到模板图" : "已删除手工上传图片");
      setShowDeleteConfirm(false);
      setImageLoadError(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : "删除失败");
    },
  });

  const clearFileSelection = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(null);
    setPreviewUrl("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [previewUrl]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Client-side validation
    const validTypes = ["image/png", "image/jpeg", "image/webp"];
    if (!validTypes.includes(file.type)) {
      setMessageType("error");
      setMessage("仅支持 PNG、JPEG、WebP 格式");
      clearFileSelection();
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setMessageType("error");
      setMessage("文件大小不能超过 10MB");
      clearFileSelection();
      return;
    }

    // Show local preview
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setMessage(null);
  }, [clearFileSelection]);

  const handleConfirmUpload = useCallback(() => {
    if (!selectedFile) return;

    if (hasUploaded) {
      setShowReplaceConfirm(true);
    } else {
      uploadMutation.mutate(selectedFile);
    }
  }, [selectedFile, hasUploaded, uploadMutation]);

  const handleReplaceConfirm = useCallback(() => {
    setShowReplaceConfirm(false);
    if (selectedFile) {
      uploadMutation.mutate(selectedFile);
    }
  }, [selectedFile, uploadMutation]);

  const handleCancelPreview = useCallback(() => {
    clearFileSelection();
  }, [clearFileSelection]);

  const openImage = useCallback(() => {
    const url = resolveAssetUrl(effective?.image_url);
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }, [effective]);

  const reloadImage = useCallback(() => {
    setImageLoadError(false);
  }, []);

  const handleImageError = useCallback(() => {
    setImageLoadError(true);
  }, []);

  const pendingUpload = uploadMutation.isPending;
  const pendingDelete = deleteMutation.isPending;

  // ── Loading state ──
  if (isLoading) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-white/60 p-4">
        <p className="flex items-center gap-2 text-sm text-[var(--color-text-hint)]">
          <Loader2 className="h-4 w-4 animate-spin" /> 正在加载函数图像资产……
        </p>
      </section>
    );
  }

  // ── Load error state ──
  if (error) {
    return (
      <section className="rounded-xl border border-red-200 bg-red-50/50 p-4">
        <p className="flex items-center gap-2 text-sm text-red-600">
          <AlertCircle className="h-4 w-4" /> 资产加载失败
        </p>
      </section>
    );
  }

  return (
    <section id="graph-assets" className="scroll-mt-28 overflow-hidden rounded-xl border border-[var(--color-border)] bg-white/60">
      {/* ── Header ── */}
      <div className="flex flex-col gap-1 border-b border-[var(--color-border)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <ImageIcon className="h-4 w-4 text-[var(--color-primary)]" />
          <span className="text-sm font-semibold text-[var(--ink)]">展示图片</span>
        </div>
        <span className="text-[11px] text-[var(--color-text-hint)]">上传后独立保存并立即用于小程序展示</span>
      </div>

      {/* ── Image preview area ── */}
      <div className="p-4">
        {effective?.image_url ? (
          <div className="space-y-3">
            {/* Image display */}
            <div className="relative rounded-lg border bg-white overflow-hidden">
              {imageLoadError ? (
                <div className="flex flex-col items-center gap-3 py-12 text-center">
                  <AlertCircle className="h-8 w-8 text-[var(--color-text-hint)]" />
                  <p className="text-sm text-[var(--color-text-secondary)]">图片资源加载失败，但资产记录仍然存在。</p>
                  <div className="flex items-center gap-2">
                    <Button type="button" variant="secondary" size="sm" onClick={reloadImage}>
                      <RefreshCw className="h-3.5 w-3.5" /> 重新加载
                    </Button>
                    {effective.image_url && (
                      <Button type="button" variant="ghost" size="sm" onClick={openImage}>
                        <ExternalLink className="h-3.5 w-3.5" /> 打开原图
                      </Button>
                    )}
                    {canUpdate && (
                      <>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          className="hidden"
                          onChange={handleFileSelect}
                        />
                        <Button type="button" variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()}>
                          <Upload className="h-3.5 w-3.5" /> 替换图片
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <img
                  src={getDisplayUrl(effective)}
                  alt="函数图像"
                  className="max-h-[480px] w-full object-contain bg-[var(--porcelain)]"
                  onError={handleImageError}
                />
              )}
            </div>

            {/* Asset metadata */}
            <div className="grid grid-cols-2 gap-3 text-xs text-[var(--color-text-secondary)]">
              <div>
                <span className="font-semibold">当前来源：</span>
                {effective.source_type === "uploaded" ? "手工上传" : effective.source_type === "generated" ? "自动生成" : "模板生成"}
              </div>
              <div>
                <span className="font-semibold">尺寸：</span>
                {effective.width ?? "—"} × {effective.height ?? "—"}
              </div>
              <div>
                <span className="font-semibold">格式：</span>
                {effective.mime_type ?? "—"}
              </div>
              <div>
                <span className="font-semibold">更新时间：</span>
                {formatDt(effective.updated_at)}
              </div>
            </div>

            {/* alt_text / description editing (only for generated assets) */}
            {effective.source_type === "generated" && (
              <AltDescEditor asset={effective} cardId={cardId} key={`asset-${effective.id}-${effective.updated_at}`} />
            )}

            {/* Status info */}
            <div className="rounded-lg border border-[var(--color-border-light)] bg-white/70 px-3 py-2.5 text-xs text-[var(--color-text-secondary)]">
              {hasUploaded && (
                <p>当前优先展示手工上传图。</p>
              )}
              {!hasUploaded && hasGenerated && (
                <p>当前展示自动生成图。上传手工图片后将优先展示手工图片。</p>
              )}
              {!hasUploaded && !hasGenerated && hasTemplate && (
                <p>当前展示模板生成图。</p>
              )}
              {hasUploaded && (
                <p className="mt-0.5">
                  <span className="font-semibold">手工上传：</span>有
                </p>
              )}
              {!hasUploaded && hasGenerated && (
                <p className="mt-0.5">
                  <span className="font-semibold">自动生成：</span>
                  <span className="text-[var(--color-success)] flex items-center gap-1"><Check className="h-3 w-3" /> 可用</span>
                </p>
              )}
              {hasTemplate && (
                <p className="mt-0.5">
                  <span className="font-semibold">模板回退：</span>
                  <span className="text-[var(--color-success)] flex items-center gap-1"><Check className="h-3 w-3" /> 可用</span>
                </p>
              )}
            </div>

            {message && (
              <div role="status" aria-live="polite" className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs ${
                messageType === "success"
                  ? "bg-[var(--color-success-light)] text-[var(--color-success)]"
                  : "bg-red-50 text-red-600"
              }`}>
                <span>{message}</span>
                <button type="button" className="ml-3 shrink-0 rounded p-0.5 hover:bg-white/60" onClick={() => setMessage(null)} aria-label="关闭提示"><X className="h-3 w-3" /></button>
              </div>
            )}

            {/* Keep the image-save action exactly where the upload action was invoked.
                Selecting a file no longer inserts controls above a tall preview and forces
                the user to scroll backwards to find the confirm button. */}
            {selectedFile && previewUrl ? (
              <PendingUploadPanel
                file={selectedFile}
                previewUrl={previewUrl}
                replacing={hasUploaded}
                pending={pendingUpload}
                onCancel={handleCancelPreview}
                onSave={handleConfirmUpload}
              />
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="ghost" size="sm" onClick={openImage}>
                  <ExternalLink className="h-3.5 w-3.5" /> 打开原图
                </Button>
                {canUpdate && (
                  <>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      onChange={handleFileSelect}
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={pendingUpload}
                    >
                      <Upload className="h-3.5 w-3.5" />
                      {hasUploaded ? "替换手工图片" : "上传函数图像"}
                    </Button>
                    {hasUploaded && (
                      <Button
                        type="button"
                        variant="danger"
                        size="sm"
                        onClick={() => setShowDeleteConfirm(true)}
                        disabled={pendingDelete}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> 删除手工图片
                      </Button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ) : selectedFile && previewUrl ? (
          <div className="py-2">
            <PendingUploadPanel
              file={selectedFile}
              previewUrl={previewUrl}
              replacing={false}
              pending={pendingUpload}
              onCancel={handleCancelPreview}
              onSave={handleConfirmUpload}
            />
          </div>
        ) : (
          /* ── Empty state ── */
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <ImageIcon className="h-10 w-10 text-[var(--color-text-hint)]" />
            <div>
              <p className="text-sm font-semibold text-[var(--color-text-secondary)]">尚未上传函数图像</p>
              <p className="mt-1 text-xs text-[var(--color-text-hint)]">支持 PNG、JPEG、WebP，单张不超过 10MB。</p>
            </div>
            {message && (
              <div role="status" aria-live="polite" className={`rounded-lg px-3 py-2 text-xs ${messageType === "success" ? "bg-[var(--color-success-light)] text-[var(--color-success)]" : "bg-red-50 text-red-600"}`}>{message}</div>
            )}
            {canUpdate && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={pendingUpload}
                >
                  <Upload className="h-3.5 w-3.5" /> 上传函数图像
                </Button>
              </>
            )}
            {!canUpdate && (
              <p className="text-xs text-[var(--color-text-hint)]">您没有上传权限</p>
            )}
          </div>
        )}
      </div>

      {/* ── Replace confirmation dialog ── */}
      <ConfirmDialog
        open={showReplaceConfirm}
        title="替换手工图片"
        description="新的图片将替换当前手工上传图，但不会删除模板生成图。是否继续？"
        confirmText="继续替换"
        danger={false}
        loading={pendingUpload}
        onCancel={() => setShowReplaceConfirm(false)}
        onConfirm={handleReplaceConfirm}
      />

      {/* ── Delete confirmation dialog ── */}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="删除手工上传图片"
        description={
          hasTemplate
            ? "删除后将自动恢复模板生成图。此操作仅删除上传的图片，不影响模板图。"
            : "删除后该卡片将暂时没有函数图像。"
        }
        confirmText="删除"
        danger
        loading={pendingDelete}
        onCancel={() => setShowDeleteConfirm(false)}
        onConfirm={() => deleteMutation.mutate()}
      />
    </section>
  );
}
