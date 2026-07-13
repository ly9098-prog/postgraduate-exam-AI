"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, ExternalLink, ImageIcon, AlertCircle, Check, Loader2, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import type { FormulaGraphAsset } from "@/lib/api/types";

type Props = {
  cardId: number;
  canUpdate: boolean;
};

function getDisplayUrl(asset: FormulaGraphAsset): string {
  const base = asset.image_url || "";
  if (!base) return base;
  const ts = asset.updated_at || asset.checksum || "";
  return ts ? `${base}?v=${encodeURIComponent(ts)}` : base;
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
    if (effective?.image_url) {
      window.open(effective.image_url, "_blank");
    }
  }, [effective]);

  const reloadImage = useCallback(() => {
    setImageLoadError(false);
  }, []);

  const handleImageError = useCallback(() => {
    setImageLoadError(true);
  }, []);

  const formatUpdatedAt = (dateStr?: string | null) => {
    if (!dateStr) return "—";
    try {
      const d = new Date(dateStr);
      return d.toLocaleString("zh-CN", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

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
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <ImageIcon className="h-4 w-4 text-[var(--color-text-secondary)]" />
          <span className="text-sm font-semibold text-[var(--ink)]">函数图像</span>
          <span className="text-[11px] text-[var(--color-text-hint)]">
            管理该公式卡片在小程序中展示的函数图
          </span>
        </div>
      </div>

      {/* ── Message ── */}
      {message && (
        <div className={`flex items-center justify-between px-4 py-2 text-sm ${
          messageType === "success"
            ? "bg-[var(--color-success-light)] text-[var(--color-success)]"
            : "bg-red-50 text-red-600"
        }`}>
          <span>{message}</span>
          <button type="button" className="ml-3 shrink-0" onClick={() => setMessage(null)}>✕</button>
        </div>
      )}

      {/* ── Local preview (file selected, not yet uploaded) ── */}
      {selectedFile && previewUrl && (
        <div className="border-b border-[var(--color-border)] p-4">
          <div className="mb-3 rounded-lg border bg-white p-2">
            <img
              src={previewUrl}
              alt="本地预览"
              className="max-h-64 w-full object-contain"
            />
          </div>
          <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-[var(--color-text-secondary)]">
            <div><span className="font-semibold">文件名：</span>{selectedFile.name}</div>
            <div><span className="font-semibold">大小：</span>{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleCancelPreview}
              disabled={pendingUpload}
            >
              <X className="h-3.5 w-3.5" /> 取消
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={handleConfirmUpload}
              disabled={pendingUpload}
            >
              {pendingUpload ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在上传</>
              ) : (
                <><Upload className="h-3.5 w-3.5" /> 确认上传</>
              )}
            </Button>
          </div>
        </div>
      )}

      {/* ── Upload progress (file already selected and uploading) ── */}
      {pendingUpload && !selectedFile && (
        <div className="flex items-center gap-2 border-b border-[var(--color-border)] p-4 text-sm text-[var(--color-text-secondary)]">
          <Loader2 className="h-4 w-4 animate-spin" /> 上传中...
        </div>
      )}

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
                {effective.source_type === "uploaded" ? "手工上传" : "模板生成"}
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
                {formatUpdatedAt(effective.updated_at)}
              </div>
            </div>

            {/* Status info */}
            <div className="rounded-lg border border-[var(--color-border-light)] bg-white/70 px-3 py-2.5 text-xs text-[var(--color-text-secondary)]">
              {hasUploaded && hasTemplate && (
                <p>当前优先展示手工上传图。删除手工图片后，将自动恢复模板图。</p>
              )}
              {hasUploaded && !hasTemplate && (
                <p>当前展示手工上传图。没有可用的模板回退图。</p>
              )}
              {!hasUploaded && hasTemplate && (
                <p>当前展示模板生成图。上传手工图片后，将优先展示手工图片。</p>
              )}
              {hasUploaded && (
                <p className="mt-0.5">
                  <span className="font-semibold">手工上传：</span>有
                  {hasTemplate && (
                    <span className="ml-3"><span className="font-semibold">模板回退：</span>
                      <span className="text-[var(--color-success)] flex items-center gap-1"><Check className="h-3 w-3" /> 可用</span>
                    </span>
                  )}
                </p>
              )}
              {!hasUploaded && hasTemplate && (
                <p><span className="font-semibold">模板回退：</span>
                  <span className="text-[var(--color-success)] flex items-center gap-1"><Check className="h-3 w-3" /> 可用</span>
                </p>
              )}
            </div>

            {/* Action buttons */}
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
                    disabled={pendingUpload || !!selectedFile}
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
          </div>
        ) : (
          /* ── Empty state ── */
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <ImageIcon className="h-10 w-10 text-[var(--color-text-hint)]" />
            <div>
              <p className="text-sm font-semibold text-[var(--color-text-secondary)]">尚未上传函数图像</p>
              <p className="mt-1 text-xs text-[var(--color-text-hint)]">支持 PNG、JPEG、WebP，单张不超过 10MB。</p>
            </div>
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
