"use client";

import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api/client";
import type { FormulaCategoryNode } from "@/components/formulas/formula-category-picker";

type Props = {
  parentNode: FormulaCategoryNode | null; // null = create subject
  onClose: () => void;
};

export function FormulaCategoryDialog({ parentNode, onClose }: Props) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  // Determine node_type based on parent
  const nodeType = !parentNode
    ? "subject"
    : parentNode.node_type === "subject"
      ? "chapter"
      : parentNode.node_type === "chapter"
        ? "group"
        : null; // group can't have children

  const title = !parentNode
    ? "新建科目"
    : parentNode.node_type === "subject"
      ? `新建章节（属于：${parentNode.name}）`
      : parentNode.node_type === "chapter"
        ? `新建分组（属于：${parentNode.name}）`
        : "";

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!code.trim()) throw new Error("请填写编码");
      if (!name.trim()) throw new Error("请填写名称");

      return apiRequest("/formulas/categories", {
        method: "POST",
        body: JSON.stringify({
          parent_id: parentNode?.id ?? null,
          code: code.trim(),
          name: name.trim(),
          node_type: nodeType,
          exam_scope: parentNode?.exam_scope || "math2",
        }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-formula-categories"] });
      onClose();
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "创建失败");
    },
  });

  const handleSubmit = useCallback(() => {
    setError("");
    createMutation.mutate();
  }, [createMutation]);

  if (!nodeType) {
    // group can't have children
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-[rgba(16,24,40,0.42)] backdrop-blur-[2px] pt-[15vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display text-lg font-bold text-[var(--ink)]">{title}</h3>
          <button onClick={onClose} className="h-8 w-8 rounded-lg hover:bg-[var(--color-bg-input)]">
            <X className="h-4 w-4 mx-auto" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">编码（英文）*</label>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="例如：chapter1_limits"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">名称 *</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：函数、极限与连续"
            />
          </div>

          <div className="inline-flex items-center gap-1.5 rounded-lg border bg-gray-50 px-3 py-1.5 text-xs text-[var(--color-text-secondary)]">
            <span className="font-semibold">类型：</span>
            {nodeType === "subject" ? "科目" : nodeType === "chapter" ? "章节" : "分组"}
          </div>

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={onClose}>
              <X className="h-3.5 w-3.5" /> 取消
            </Button>
            <Button onClick={handleSubmit} disabled={createMutation.isPending}>
              <Save className="h-3.5 w-3.5" />
              {createMutation.isPending ? "创建中..." : "创建"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
