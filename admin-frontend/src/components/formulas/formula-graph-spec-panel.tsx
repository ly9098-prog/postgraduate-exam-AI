"use client";

import { useState, useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Eye,
  FileText,
  GripVertical,
  ImageIcon,
  LayoutTemplate,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import type {
  GraphSpec,
  GraphSpecExpression,
  GraphSpecPanel,
  GraphSpecDomain,
  GraphSpecAnnotation,
  GraphSpecRefLine,
  GraphPreviewResponse,
  GraphConfirmResponse,
  GraphStatus,
  QualityCheckResult,
  FormulaGraphAsset,
} from "@/lib/api/types";

// ── Types ──

type Props = {
  cardId: number;
  cardVersion: number;
  initialSpec: GraphSpec | null;
  initialStatus: GraphStatus | string;
  canUpdate: boolean;
  graphLastError?: string | null;
  graphGeneratedAt?: string | null;
  graphConfirmedAt?: string | null;
};

type DomainInterval = {
  start: number | null;
  end: number | null;
  leftOpen: boolean;
  rightOpen: boolean;
};

type ValidationError = {
  field: string;
  message: string;
};

// ── Constants ──

const TEMPLATE_OPTIONS: { value: string; label: string; desc: string }[] = [
  { value: "single_function", label: "单函数图像", desc: "单个或叠加多个函数" },
  { value: "function_comparison", label: "函数对比", desc: "多个函数在同一坐标系" },
  { value: "multi_panel", label: "多面板对比", desc: "独立子图组合" },
  { value: "discontinuity_comparison", label: "间断点对比", desc: "2×2 四类间断点" },
  { value: "inequality_auxiliary", label: "辅助函数对比", desc: "三联辅助函数图" },
];

const STATUS_LABELS: Record<string, string> = {
  not_applicable: "不适用",
  unconfigured: "未配置",
  missing: "缺少图像",
  generating: "生成中",
  draft: "待确认",
  ready: "已完成",
  failed: "生成失败",
  ignored: "已忽略",
};

const STATUS_BADGES: Record<string, string> = {
  not_applicable: "bg-gray-50 text-gray-400 border-gray-200",
  unconfigured: "bg-gray-50 text-gray-500 border-gray-200",
  missing: "bg-amber-50 text-amber-700 border-amber-200",
  generating: "bg-blue-50 text-blue-700 border-blue-200",
  draft: "bg-amber-50 text-amber-700 border-amber-200",
  ready: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  ignored: "bg-gray-50 text-gray-400 border-gray-200",
};

const LINE_STYLE_OPTIONS = [
  { value: "solid", label: "实线" },
  { value: "dashed", label: "虚线" },
  { value: "dotted", label: "点线" },
  { value: "dashdot", label: "点划线" },
];

const AXIS_MODE_OPTIONS = [
  { value: "manual", label: "手动" },
  { value: "auto", label: "自动" },
  { value: "auto_robust", label: "自动(鲁棒)" },
];

const POINT_STYLE_OPTIONS = [
  { value: "filled", label: "实心" },
  { value: "hollow", label: "空心" },
];

// ── Helpers ──

function domainIntervalsToGui(domain: GraphSpecDomain | undefined): DomainInterval[] {
  if (!domain?.intervals || domain.intervals.length === 0) return [];
  return domain.intervals.map((iv) => ({
    start: iv[0] ?? null,
    end: iv[1] ?? null,
    leftOpen: false,
    rightOpen: false,
  }));
}

function guiToDomainIntervals(intervals: DomainInterval[]): Array<[number | null, number | null]> {
  return intervals.map((iv) => [iv.start, iv.end]);
}

function intervalDisplay(iv: DomainInterval): string {
  const left = iv.leftOpen ? "(" : "[";
  const right = iv.rightOpen ? ")" : "]";
  const s = iv.start !== null ? (Number.isInteger(iv.start) ? iv.start.toString() : iv.start.toFixed(2)) : "−∞";
  const e = iv.end !== null ? (Number.isInteger(iv.end) ? iv.end.toString() : iv.end.toFixed(2)) : "+∞";
  return `${left}${s}, ${e}${right}`;
}

function formatDt(d: string | null | undefined) {
  if (!d) return "—";
  try { return new Date(d).toLocaleString("zh-CN"); } catch { return d; }
}

function defaultPanel(template: string, count: number): GraphSpecPanel[] {
  if (template === "single_function" || template === "function_comparison") {
    return [{
      expressions: count > 0
        ? Array.from({ length: count }, (_, i) => ({
            expression: i === 0 ? "x**2" : "x**2",
            label: i === 0 ? "y=x²" : "",
            line_style: "solid" as const,
          }))
        : [{ expression: "x**2", label: "y=x²", line_style: "solid" as const }],
      domain: { intervals: [] },
      axis_mode: "auto_robust" as const,
      x_range: [-6, 6] as [number, number],
      y_range: [-6, 6] as [number, number],
    }];
  }
  if (template === "multi_panel") {
    return Array.from({ length: count || 2 }, (_, i) => ({
      expressions: [{ expression: "x**2", label: "", line_style: "solid" as const }],
      domain: { intervals: [] },
      axis_mode: "manual" as const,
      x_range: [-6, 6] as [number, number],
      y_range: [-6, 6] as [number, number],
      title: `面板 ${i + 1}`,
    }));
  }
  return [];
}

function validateSpec(spec: GraphSpec): ValidationError[] {
  const errors: ValidationError[] = [];
  if (!spec.panels || spec.panels.length === 0) {
    errors.push({ field: "panels", message: "至少需要一个面板" });
    return errors;
  }
  const layout = spec.layout;
  if (layout && layout.rows * layout.columns < spec.panels.length) {
    errors.push({ field: "layout", message: `布局 ${layout.rows}×${layout.columns}=${layout.rows * layout.columns} 不足以容纳 ${spec.panels.length} 个面板` });
  }
  spec.panels.forEach((panel, pi) => {
    if (!panel.expressions || panel.expressions.length === 0) {
      errors.push({ field: `panel[${pi}].expressions`, message: `面板 ${pi + 1} 至少需要一个表达式` });
    }
    panel.expressions.forEach((expr, ei) => {
      if (!expr.expression || expr.expression.trim() === "") {
        errors.push({ field: `panel[${pi}].expressions[${ei}].expression`, message: `面板 ${pi + 1} 表达式 ${ei + 1} 不能为空` });
      }
    });
    if (panel.axis_mode === "manual") {
      const xr = panel.x_range;
      const yr = panel.y_range;
      if (xr && xr[0] >= xr[1]) {
        errors.push({ field: `panel[${pi}].x_range`, message: `面板 ${pi + 1} x 范围不合法（min ≥ max）` });
      }
      if (yr && yr[0] >= yr[1]) {
        errors.push({ field: `panel[${pi}].y_range`, message: `面板 ${pi + 1} y 范围不合法（min ≥ max）` });
      }
    }
    (panel.annotations || []).forEach((ann, ai) => {
      if (!Number.isFinite(ann.x) || !Number.isFinite(ann.y)) {
        errors.push({ field: `panel[${pi}].annotations[${ai}]`, message: `面板 ${pi + 1} 注释 ${ai + 1} 坐标不是有限数值` });
      }
    });
    (panel.vertical_lines || []).forEach((vl, li) => {
      if (!Number.isFinite(vl.value)) {
        errors.push({ field: `panel[${pi}].vertical_lines[${li}]`, message: `面板 ${pi + 1} 垂直参考线 ${li + 1} 值不是有限数值` });
      }
    });
    (panel.horizontal_lines || []).forEach((hl, li) => {
      if (!Number.isFinite(hl.value)) {
        errors.push({ field: `panel[${pi}].horizontal_lines[${li}]`, message: `面板 ${pi + 1} 水平参考线 ${li + 1} 值不是有限数值` });
      }
    });
  });
  return errors;
}

function specFromPanels(template: string, panels: GraphSpecPanel[]): GraphSpec {
  const panelCount = panels.length;
  const cols = panelCount === 1 ? 1 : Math.min(panelCount, 2);
  const rows = Math.ceil(panelCount / cols);
  return {
    schema_version: 1,
    render_mode: "explicit_2d",
    template: template as GraphSpec["template"],
    layout: { rows, columns: cols },
    panels,
  };
}

// ── Sub-components ──

function DataTableNumberInput({
  value, onChange, placeholder, min, disabled, className = "",
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  placeholder?: string;
  min?: number;
  disabled?: boolean;
  className?: string;
}) {
  const [local, setLocal] = useState(value !== null ? String(value) : "");
  return (
    <input
      type="number"
      className={`w-full rounded border bg-white px-2 py-1 text-xs font-mono ${className}`}
      placeholder={placeholder ?? ""}
      value={local}
      min={min}
      disabled={disabled}
      onChange={(e) => {
        setLocal(e.target.value);
        const parsed = parseFloat(e.target.value);
        onChange(Number.isFinite(parsed) ? parsed : null);
      }}
      onBlur={() => {
        if (value === null) setLocal("");
        else setLocal(String(value));
      }}
    />
  );
}

// ── Main Component ──

export function FormulaGraphSpecPanel({
  cardId, cardVersion, initialSpec, initialStatus, canUpdate,
  graphLastError, graphGeneratedAt, graphConfirmedAt,
}: Props) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"success" | "error">("success");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [activePanelIdx, setActivePanelIdx] = useState(0);
  const [showJsonMode, setShowJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonParseError, setJsonParseError] = useState<string | null>(null);

  const [template, setTemplate] = useState<string>(initialSpec?.template || "single_function");
  const [panels, setPanels] = useState<GraphSpecPanel[]>(
    initialSpec?.panels || defaultPanel(initialSpec?.template || "single_function", 1),
  );
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewToken, setPreviewToken] = useState<string | null>(null);
  const [previewChecksum, setPreviewChecksum] = useState<string | null>(null);
  const [quality, setQuality] = useState<QualityCheckResult | null>(null);
  const [currentStatus, setCurrentStatus] = useState<GraphStatus | string>(initialStatus);
  const [acceptWarnings, setAcceptWarnings] = useState(false);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);

  const specForApi = useMemo(() => specFromPanels(template, panels), [template, panels]);

  // Panel management
  const addPanel = useCallback(() => {
    setPanels((prev) => [
      ...prev,
      {
        expressions: [{ expression: "", line_style: "solid" as const }],
        domain: { intervals: [] },
        axis_mode: "auto_robust" as const,
        x_range: [-6, 6] as [number, number],
        y_range: [-6, 6] as [number, number],
        title: `面板 ${prev.length + 1}`,
      },
    ]);
    setActivePanelIdx(panels.length);
  }, [panels.length]);

  const deletePanel = useCallback((idx: number) => {
    setPanels((prev) => {
      if (prev.length <= 1) return prev;
      const next = prev.filter((_, i) => i !== idx);
      return next;
    });
    setActivePanelIdx((prev) => Math.min(prev, panels.length - 2));
  }, [panels.length]);

  const copyPanel = useCallback((idx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      const copy = JSON.parse(JSON.stringify(next[idx]));
      next.splice(idx + 1, 0, copy);
      return next;
    });
    setActivePanelIdx(idx + 1);
  }, []);

  const movePanel = useCallback((idx: number, dir: -1 | 1) => {
    setPanels((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
    setActivePanelIdx(idx + dir);
  }, []);

  // Panel field update
  const updatePanel = useCallback((idx: number, field: string, value: unknown) => {
    setPanels((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value } as GraphSpecPanel;
      return next;
    });
  }, []);

  // Expression management
  const updateExpression = useCallback((panelIdx: number, exprIdx: number, field: keyof GraphSpecExpression, value: string) => {
    setPanels((prev) => {
      const next = [...prev];
      const exprs = [...next[panelIdx].expressions];
      exprs[exprIdx] = { ...exprs[exprIdx], [field]: value };
      next[panelIdx] = { ...next[panelIdx], expressions: exprs };
      return next;
    });
  }, []);

  const addExpression = useCallback((panelIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      next[panelIdx] = {
        ...next[panelIdx],
        expressions: [...next[panelIdx].expressions, { expression: "", line_style: "solid" as const }],
      };
      return next;
    });
  }, []);

  const copyExpression = useCallback((panelIdx: number, exprIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      const exprs = [...next[panelIdx].expressions];
      const copy = { ...exprs[exprIdx] };
      exprs.splice(exprIdx + 1, 0, copy);
      next[panelIdx] = { ...next[panelIdx], expressions: exprs };
      return next;
    });
  }, []);

  const removeExpression = useCallback((panelIdx: number, exprIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      next[panelIdx] = {
        ...next[panelIdx],
        expressions: next[panelIdx].expressions.filter((_, i) => i !== exprIdx),
      };
      return next;
    });
  }, []);

  const moveExpression = useCallback((panelIdx: number, exprIdx: number, dir: -1 | 1) => {
    setPanels((prev) => {
      const next = [...prev];
      const exprs = [...next[panelIdx].expressions];
      const target = exprIdx + dir;
      if (target < 0 || target >= exprs.length) return prev;
      [exprs[exprIdx], exprs[target]] = [exprs[target], exprs[exprIdx]];
      next[panelIdx] = { ...next[panelIdx], expressions: exprs };
      return next;
    });
  }, []);

  // Domain management
  const updateDomainIntervals = useCallback((panelIdx: number, intervals: DomainInterval[]) => {
    setPanels((prev) => {
      const next = [...prev];
      next[panelIdx] = {
        ...next[panelIdx],
        domain: {
          intervals: guiToDomainIntervals(intervals),
          exclude_points: next[panelIdx].domain?.exclude_points || [],
        },
      };
      return next;
    });
  }, []);

  const updateExcludePoints = useCallback((panelIdx: number, text: string) => {
    const points = text.split(",").map((s) => parseFloat(s.trim())).filter((n) => Number.isFinite(n));
    setPanels((prev) => {
      const next = [...prev];
      next[panelIdx] = {
        ...next[panelIdx],
        domain: {
          intervals: next[panelIdx].domain?.intervals || [],
          exclude_points: points,
        },
      };
      return next;
    });
  }, []);

  // Annotations management
  const addAnnotation = useCallback((panelIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      const anns = next[panelIdx].annotations || [];
      next[panelIdx] = {
        ...next[panelIdx],
        annotations: [...anns, { x: 0, y: 0, label: "", color: "#b91c1c", point_style: "filled" as const }],
      };
      return next;
    });
  }, []);

  const updateAnnotation = useCallback((panelIdx: number, annIdx: number, field: string, value: unknown) => {
    setPanels((prev) => {
      const next = [...prev];
      const anns = [...(next[panelIdx].annotations || [])];
      anns[annIdx] = { ...anns[annIdx], [field]: value };
      next[panelIdx] = { ...next[panelIdx], annotations: anns };
      return next;
    });
  }, []);

  const removeAnnotation = useCallback((panelIdx: number, annIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      const anns = (next[panelIdx].annotations || []).filter((_, i) => i !== annIdx);
      next[panelIdx] = { ...next[panelIdx], annotations: anns.length > 0 ? anns : undefined };
      return next;
    });
  }, []);

  // Reference lines management
  const addRefLine = useCallback((panelIdx: number, orientation: "vertical" | "horizontal") => {
    setPanels((prev) => {
      const next = [...prev];
      const key = orientation === "vertical" ? "vertical_lines" : "horizontal_lines";
      const lines = next[panelIdx][key] || [];
      next[panelIdx] = {
        ...next[panelIdx],
        [key]: [...lines, { value: 0, label: "", style: "dashed" as const, is_vertical: orientation === "vertical" }],
      };
      return next;
    });
  }, []);

  const updateRefLine = useCallback((panelIdx: number, orientation: "vertical" | "horizontal", lineIdx: number, field: string, value: unknown) => {
    setPanels((prev) => {
      const next = [...prev];
      const key = orientation === "vertical" ? "vertical_lines" : "horizontal_lines";
      const lines = [...(next[panelIdx][key] || [])];
      lines[lineIdx] = { ...lines[lineIdx], [field]: value };
      next[panelIdx] = { ...next[panelIdx], [key]: lines };
      return next;
    });
  }, []);

  const removeRefLine = useCallback((panelIdx: number, orientation: "vertical" | "horizontal", lineIdx: number) => {
    setPanels((prev) => {
      const next = [...prev];
      const key = orientation === "vertical" ? "vertical_lines" : "horizontal_lines";
      const lines = (next[panelIdx][key] || []).filter((_, i) => i !== lineIdx);
      next[panelIdx] = { ...next[panelIdx], [key]: lines.length > 0 ? lines : undefined };
      return next;
    });
  }, []);

  // JSON sync
  const syncFormToJson = useCallback(() => {
    setJsonText(JSON.stringify(specForApi, null, 2));
    setJsonParseError(null);
  }, [specForApi]);

  const syncJsonToForm = useCallback(() => {
    if (!jsonText.trim()) return;
    try {
      const parsed = JSON.parse(jsonText);
      const newPanels: GraphSpecPanel[] = parsed.panels || [];
      const newTemplate = parsed.template || template;
      setPanels(newPanels);
      setTemplate(newTemplate);
      setJsonParseError(null);
      setActivePanelIdx(0);
    } catch (e) {
      setJsonParseError(e instanceof Error ? e.message : "JSON 解析失败");
    }
  }, [jsonText, template]);

  // Mutations
  const previewMutation = useMutation({
    mutationFn: () =>
      apiRequest<GraphPreviewResponse>(`/formulas/${cardId}/graph/preview`, {
        method: "POST",
        body: JSON.stringify(specForApi),
      }),
    onSuccess: (data) => {
      setPreviewUrl(data.preview_url);
      setPreviewToken(data.preview_token);
      setPreviewChecksum(data.checksum);
      setQuality(data.quality);
      setCurrentStatus("draft");
      setMessageType("success");
      setMessage(data.quality.warnings.length > 0
        ? `预览生成成功（${data.quality.warnings.length} 个警告）`
        : "预览生成成功");
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : "生成预览失败");
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () =>
      apiRequest<GraphConfirmResponse>(`/formulas/${cardId}/graph/confirm`, {
        method: "POST",
        body: JSON.stringify({
          preview_token: previewToken,
          checksum: previewChecksum,
          card_version: cardVersion,
          accept_warnings: acceptWarnings,
        }),
      }),
    onSuccess: () => {
      setCurrentStatus("ready");
      setMessageType("success");
      setMessage("函数图像已确认使用");
      setPreviewUrl(null);
      setPreviewToken(null);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : "确认失败");
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: () =>
      apiRequest<GraphConfirmResponse>(`/formulas/${cardId}/graph/regenerate`, {
        method: "POST",
        body: JSON.stringify(specForApi),
      }),
    onSuccess: () => {
      setCurrentStatus("ready");
      setMessageType("success");
      setMessage("函数图像已重新生成");
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : "重新生成失败");
    },
  });

  const deleteGeneratedMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ status: string }>(`/formulas/${cardId}/graph/generated`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setCurrentStatus("missing");
      setMessageType("success");
      setMessage("自动生成图像已删除");
      setShowDeleteConfirm(false);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-graph-assets", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas", cardId] });
      queryClient.invalidateQueries({ queryKey: ["admin-formulas"] });
    },
    onError: (e) => {
      setMessageType("error");
      setMessage(e instanceof Error ? e.message : "删除失败");
    },
  });

  // ── Interaction handlers ──

  const handleGeneratePreview = () => {
    const errs = validateSpec(specForApi);
    setValidationErrors(errs);
    if (errs.length > 0) {
      setMessageType("error");
      setMessage(`校验未通过（${errs.length} 项）`);
      return;
    }
    setQuality(null);
    previewMutation.mutate();
  };

  const handleTemplateChange = (newTemplate: string) => {
    setTemplate(newTemplate);
    setPanels(defaultPanel(newTemplate, 1));
    setPreviewUrl(null);
    setPreviewToken(null);
    setQuality(null);
    setValidationErrors([]);
    setActivePanelIdx(0);
  };

  const handleConfirm = () => {
    if (acceptWarnings) setAcceptWarnings(false);
    confirmMutation.mutate();
  };

  // ── Derived state ──

  const isLoading = previewMutation.isPending || confirmMutation.isPending || regenerateMutation.isPending;
  const showWarnings = quality && quality.warnings.length > 0;
  const canPreview = panels.some((p) => p.expressions.some((e) => e.expression.trim()));
  const canConfirm = previewToken !== null && currentStatus === "draft";

  // ── Read-only view ──

  if (!canUpdate) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-white/60 p-4">
        <div className="flex items-center gap-2">
          <LayoutTemplate className="h-4 w-4 text-[var(--color-text-secondary)]" />
          <span className="text-sm font-semibold text-[var(--ink)]">自动生成函数图像</span>
          {currentStatus && currentStatus !== "not_applicable" && (
            <span className={`inline-flex items-center gap-1 rounded-xl border px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGES[currentStatus] || ""}`}>
              {STATUS_LABELS[currentStatus] || currentStatus}
            </span>
          )}
        </div>
        {graphLastError && (
          <p className="mt-2 text-xs text-red-600">错误: {graphLastError}</p>
        )}
        {graphGeneratedAt && (
          <p className="mt-1 text-xs text-[var(--color-text-hint)]">生成时间: {formatDt(graphGeneratedAt)}</p>
        )}
        {graphConfirmedAt && (
          <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">确认时间: {formatDt(graphConfirmedAt)}</p>
        )}
        {(!currentStatus || currentStatus === "not_applicable") && (
          <p className="mt-2 text-xs text-[var(--color-text-hint)]">此公式不适用函数图像功能</p>
        )}
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white/60">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <LayoutTemplate className="h-4 w-4 text-[var(--color-text-secondary)]" />
          <span className="text-sm font-semibold text-[var(--ink)]">自动生成函数图像</span>
          <span className={`inline-flex items-center gap-1 rounded-xl border px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGES[currentStatus] || ""}`}>
            {STATUS_LABELS[currentStatus] || currentStatus}
          </span>
        </div>
      </div>

      {/* Message */}
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

      {/* Error banner */}
      {graphLastError && currentStatus === "failed" && (
        <div className="border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-600">
          错误: {graphLastError}
        </div>
      )}

      {/* Timestamp bar */}
      {(graphGeneratedAt || graphConfirmedAt) && currentStatus === "ready" && (
        <div className="flex gap-4 border-b border-[var(--color-border)] bg-gray-50 px-4 py-1.5 text-[11px] text-[var(--color-text-hint)]">
          {graphGeneratedAt && <span>生成时间: {formatDt(graphGeneratedAt)}</span>}
          {graphConfirmedAt && <span>确认时间: {formatDt(graphConfirmedAt)}</span>}
        </div>
      )}

      <div className="space-y-4 p-4">
        {/* ── Template selector ── */}
        <div>
          <label className="text-xs font-semibold text-[var(--color-text-secondary)]">图像模板</label>
          <div className="mt-1 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {TEMPLATE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={isLoading}
                className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                  template === opt.value
                    ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                    : "border-[var(--color-border)] bg-white/80 hover:bg-white"
                }`}
                onClick={() => handleTemplateChange(opt.value)}
              >
                <span className="font-semibold">{opt.label}</span>
                <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">{opt.desc}</p>
              </button>
            ))}
          </div>
        </div>

        {/* ── Layout info (auto-computed from panel count) ── */}
        <div className="flex items-center gap-3">
          <label className="text-xs font-semibold text-[var(--color-text-secondary)]">布局</label>
          <span className="text-xs text-[var(--color-text-hint)]">
            {specForApi.layout?.rows ?? 1}行 × {specForApi.layout?.columns ?? 1}列 = {(specForApi.layout?.rows ?? 1) * (specForApi.layout?.columns ?? 1)} 格，当前 {panels.length} 面板
            {(specForApi.layout?.rows ?? 1) * (specForApi.layout?.columns ?? 1) < panels.length && (
              <span className="ml-1 text-amber-600">（格子数不足）</span>
            )}
          </span>
        </div>

        {/* ── Panel tabs ── */}
        {panels.length > 0 && (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-1 border-b border-[var(--color-border)] pb-1">
              {panels.map((panel, pi) => (
                <button
                  key={pi}
                  type="button"
                  className={`inline-flex items-center gap-1 rounded-t-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                    activePanelIdx === pi
                      ? "border border-b-white bg-white text-[var(--color-primary)]"
                      : "text-[var(--color-text-secondary)] hover:bg-gray-50"
                  }`}
                  onClick={() => setActivePanelIdx(pi)}
                >
                  <span>{panel.title || `面板 ${pi + 1}`}</span>
                </button>
              ))}
              <button
                type="button"
                className="ml-1 inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-primary)] hover:bg-[var(--color-primary-light)]"
                disabled={isLoading || panels.length >= 9}
                onClick={addPanel}
                title="新增面板"
              >
                <Plus className="h-3 w-3" /> 新增
              </button>
            </div>

            {/* Per-panel controls */}
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs text-[var(--color-text-hint)]">
                {panels[activePanelIdx]?.title || `面板 ${activePanelIdx + 1}`}
              </span>
              <button
                type="button"
                className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-100 disabled:opacity-30"
                disabled={activePanelIdx <= 0 || isLoading}
                onClick={() => movePanel(activePanelIdx, -1)}
                title="左移"
              >
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-100 disabled:opacity-30"
                disabled={activePanelIdx >= panels.length - 1 || isLoading}
                onClick={() => movePanel(activePanelIdx, 1)}
                title="右移"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-100 disabled:opacity-30"
                disabled={isLoading}
                onClick={() => copyPanel(activePanelIdx)}
                title="复制面板"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="rounded p-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                disabled={panels.length <= 1 || isLoading}
                onClick={() => deletePanel(activePanelIdx)}
                title="删除面板"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Active panel content */}
            {panels[activePanelIdx] && (
              <div className="space-y-3 rounded-lg border border-[var(--color-border)] p-3">
                <PanelSettings
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  updatePanel={updatePanel}
                />

                <ExpressionsEditor
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  updateExpression={updateExpression}
                  addExpression={addExpression}
                  copyExpression={copyExpression}
                  removeExpression={removeExpression}
                  moveExpression={moveExpression}
                />

                <DomainEditor
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  updateDomainIntervals={updateDomainIntervals}
                  updateExcludePoints={updateExcludePoints}
                />

                <AnnotationsEditor
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  updateAnnotation={updateAnnotation}
                  addAnnotation={addAnnotation}
                  removeAnnotation={removeAnnotation}
                />

                <RefLinesEditor
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  orientation="vertical"
                  updateRefLine={updateRefLine}
                  addRefLine={addRefLine}
                  removeRefLine={removeRefLine}
                />

                <RefLinesEditor
                  panel={panels[activePanelIdx]}
                  panelIdx={activePanelIdx}
                  isLoading={isLoading}
                  orientation="horizontal"
                  updateRefLine={updateRefLine}
                  addRefLine={addRefLine}
                  removeRefLine={removeRefLine}
                />
              </div>
            )}
          </div>
        )}

        {/* ── Validation errors ── */}
        {validationErrors.length > 0 && (
          <div className="rounded-lg border border-red-200 bg-red-50/60 px-3 py-2">
            <p className="text-xs font-semibold text-red-700">表单校验错误（{validationErrors.length} 项）</p>
            <ul className="mt-1 list-disc pl-4 text-xs text-red-600">
              {validationErrors.map((ve, i) => (
                <li key={i}>{ve.message}</li>
              ))}
            </ul>
          </div>
        )}

        {/* ── JSON advanced mode toggle ── */}
        <div>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]"
            onClick={() => {
              if (!showJsonMode) syncFormToJson();
              setShowJsonMode(!showJsonMode);
            }}
          >
            <FileText className="h-3 w-3" />
            {showJsonMode ? "关闭 JSON 编辑" : "高级 JSON 编辑"}
          </button>

          {showJsonMode && (
            <div className="mt-2 space-y-2">
              <textarea
                className="w-full rounded-lg border bg-gray-50 px-3 py-2 font-mono text-xs"
                rows={12}
                value={jsonText}
                onChange={(e) => {
                  setJsonText(e.target.value);
                  setJsonParseError(null);
                }}
                disabled={isLoading}
              />
              {jsonParseError && (
                <p className="text-xs text-red-500">JSON 错误: {jsonParseError}</p>
              )}
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={syncFormToJson}
                >
                  同步表单 → JSON
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={syncJsonToForm}
                  disabled={!!jsonParseError}
                >
                  同步 JSON → 表单
                </Button>
              </div>
              <p className="text-[10px] text-[var(--color-text-hint)]">
                JSON 校验失败时不会覆盖当前表单。请先修正 JSON 错误后再同步到表单。
              </p>
            </div>
          )}
        </div>

        {/* ── Action buttons ── */}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" onClick={handleGeneratePreview} disabled={!canPreview || isLoading}>
            {previewMutation.isPending
              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 生成中</>
              : <><Eye className="h-3.5 w-3.5" /> 生成预览</>
            }
          </Button>

          {canConfirm && (
            <Button type="button" size="sm" onClick={handleConfirm} disabled={confirmMutation.isPending}>
              {confirmMutation.isPending
                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 确认中</>
                : <><CheckCircle2 className="h-3.5 w-3.5" /> {showWarnings && !acceptWarnings ? "确认使用（忽略警告）" : "确认使用"}</>
              }
            </Button>
          )}

          {showWarnings && canConfirm && !acceptWarnings && (
            <label className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
              <input type="checkbox" checked={acceptWarnings} onChange={(e) => setAcceptWarnings(e.target.checked)} className="rounded" />
              接受警告并确认
            </label>
          )}

          {currentStatus === "ready" && (
            <Button type="button" variant="secondary" size="sm" onClick={() => regenerateMutation.mutate()} disabled={regenerateMutation.isPending}>
              {regenerateMutation.isPending
                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 重生成中</>
                : <><RefreshCw className="h-3.5 w-3.5" /> 重新生成</>
              }
            </Button>
          )}

          {(currentStatus === "ready" || currentStatus === "draft" || currentStatus === "missing") && (
            <Button type="button" variant="danger" size="sm" onClick={() => setShowDeleteConfirm(true)} disabled={deleteGeneratedMutation.isPending}>
              <Trash2 className="h-3.5 w-3.5" /> 删除生成图
            </Button>
          )}
        </div>

        {/* ── Quality checks ── */}
        {quality && quality.warnings.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
            <p className="text-xs font-semibold text-amber-700">质量检查警告</p>
            <ul className="mt-1 list-disc pl-4 text-xs text-amber-600">
              {quality.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        )}

        {quality && quality.errors.length > 0 && (
          <div className="rounded-lg border border-red-200 bg-red-50/60 px-3 py-2">
            <p className="text-xs font-semibold text-red-700">质量检查错误（请修正后重新生成）</p>
            <ul className="mt-1 list-disc pl-4 text-xs text-red-600">
              {quality.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        )}

        {/* ── Preview image ── */}
        {previewUrl && (
          <div className="rounded-lg border bg-white p-2">
            <img src={`${previewUrl}?v=${Date.now()}`} alt="函数图像预览" className="max-h-[400px] w-full object-contain" />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={showDeleteConfirm}
        title="删除自动生成图像"
        description="将删除自动生成的函数图像资源。手动上传的图像不受影响。是否继续？"
        confirmText="删除"
        danger
        loading={deleteGeneratedMutation.isPending}
        onCancel={() => setShowDeleteConfirm(false)}
        onConfirm={() => deleteGeneratedMutation.mutate()}
      />
    </section>
  );
}

// ── Sub-component: Panel Settings ──

function PanelSettings({
  panel, panelIdx, isLoading, updatePanel,
}: {
  panel: GraphSpecPanel;
  panelIdx: number;
  isLoading: boolean;
  updatePanel: (idx: number, field: string, value: unknown) => void;
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">面板设置</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
        <div className="col-span-2 sm:col-span-3 lg:col-span-2">
          <label className="text-[10px] text-[var(--color-text-hint)]">标题</label>
          <input
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
            placeholder="面板标题"
            value={panel.title || ""}
            disabled={isLoading}
            onChange={(e) => updatePanel(panelIdx, "title", e.target.value || null)}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">X 轴模式</label>
          <select
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
            value={panel.axis_mode || "auto_robust"}
            disabled={isLoading}
            onChange={(e) => updatePanel(panelIdx, "axis_mode", e.target.value)}
          >
            {AXIS_MODE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">X min</label>
          <input
            type="number"
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs font-mono"
            placeholder="-6"
            value={panel.x_range?.[0] ?? ""}
            disabled={isLoading || (panel.axis_mode || "auto_robust") !== "manual"}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isFinite(v)) return;
              const xr: [number, number] = [v, panel.x_range?.[1] ?? 6];
              updatePanel(panelIdx, "x_range", xr);
            }}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">X max</label>
          <input
            type="number"
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs font-mono"
            placeholder="6"
            value={panel.x_range?.[1] ?? ""}
            disabled={isLoading || (panel.axis_mode || "auto_robust") !== "manual"}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isFinite(v)) return;
              const xr: [number, number] = [panel.x_range?.[0] ?? -6, v];
              updatePanel(panelIdx, "x_range", xr);
            }}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">Y min</label>
          <input
            type="number"
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs font-mono"
            placeholder="-6"
            value={panel.y_range?.[0] ?? ""}
            disabled={isLoading || (panel.axis_mode || "auto_robust") !== "manual"}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isFinite(v)) return;
              const yr: [number, number] = [v, panel.y_range?.[1] ?? 6];
              updatePanel(panelIdx, "y_range", yr);
            }}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">Y max</label>
          <input
            type="number"
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs font-mono"
            placeholder="6"
            value={panel.y_range?.[1] ?? ""}
            disabled={isLoading || (panel.axis_mode || "auto_robust") !== "manual"}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!Number.isFinite(v)) return;
              const yr: [number, number] = [panel.y_range?.[0] ?? -6, v];
              updatePanel(panelIdx, "y_range", yr);
            }}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">X 轴标签</label>
          <input
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
            placeholder="x"
            value={panel.x_label || ""}
            disabled={isLoading}
            onChange={(e) => updatePanel(panelIdx, "x_label", e.target.value || undefined)}
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--color-text-hint)]">Y 轴标签</label>
          <input
            className="mt-0.5 w-full rounded-lg border bg-white px-2 py-1.5 text-xs"
            placeholder="y"
            value={panel.y_label || ""}
            disabled={isLoading}
            onChange={(e) => updatePanel(panelIdx, "y_label", e.target.value || undefined)}
          />
        </div>
      </div>
      {panel.axis_mode === "manual" && (
        <p className="mt-1 text-[10px] text-amber-600">手动模式下请确保 min &lt; max，否则提交时会被阻止</p>
      )}
    </div>
  );
}

// ── Sub-component: Expression Editor ──

function ExpressionsEditor({
  panel, panelIdx, isLoading, updateExpression, addExpression, copyExpression, removeExpression, moveExpression,
}: {
  panel: GraphSpecPanel;
  panelIdx: number;
  isLoading: boolean;
  updateExpression: (panelIdx: number, exprIdx: number, field: keyof GraphSpecExpression, value: string) => void;
  addExpression: (panelIdx: number) => void;
  copyExpression: (panelIdx: number, exprIdx: number) => void;
  removeExpression: (panelIdx: number, exprIdx: number) => void;
  moveExpression: (panelIdx: number, exprIdx: number, dir: -1 | 1) => void;
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">
        表达式（{panel.expressions.length}/8）
      </p>
      <div className="space-y-1.5">
        {panel.expressions.map((expr, ei) => (
          <div key={ei} className="flex items-center gap-1.5 rounded-lg bg-gray-50/60 p-1.5">
            {/* Expression */}
            <input
              className="flex-[2] rounded border bg-white px-2 py-1.5 text-xs font-mono"
              placeholder="表达式 (如 x**2, sin(x))"
              value={expr.expression}
              onChange={(e) => updateExpression(panelIdx, ei, "expression", e.target.value)}
              disabled={isLoading}
            />
            {/* display_latex */}
            <input
              className="flex-1 rounded border bg-white px-2 py-1.5 text-xs font-mono"
              placeholder="LaTeX (可选)"
              value={(expr as Record<string, unknown>).display_latex as string || ""}
              onChange={(e) => updateExpression(panelIdx, ei, "display_latex" as keyof GraphSpecExpression, e.target.value)}
              disabled={isLoading}
            />
            {/* Label */}
            <input
              className="w-24 rounded border bg-white px-2 py-1.5 text-xs"
              placeholder="标签"
              value={expr.label || ""}
              onChange={(e) => updateExpression(panelIdx, ei, "label", e.target.value)}
              disabled={isLoading}
            />
            {/* Line style */}
            <select
              className="w-20 rounded border bg-white px-1 py-1.5 text-xs"
              value={expr.line_style || "solid"}
              onChange={(e) => updateExpression(panelIdx, ei, "line_style", e.target.value)}
              disabled={isLoading}
            >
              {LINE_STYLE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            {/* Actions */}
            <div className="flex shrink-0 items-center gap-0.5">
              <button type="button" className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-200 disabled:opacity-30"
                disabled={ei <= 0 || isLoading} onClick={() => moveExpression(panelIdx, ei, -1)} title="上移">
                <ChevronUp className="h-3 w-3" />
              </button>
              <button type="button" className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-200 disabled:opacity-30"
                disabled={ei >= panel.expressions.length - 1 || isLoading} onClick={() => moveExpression(panelIdx, ei, 1)} title="下移">
                <ChevronDown className="h-3 w-3" />
              </button>
              <button type="button" className="rounded p-1 text-[var(--color-text-hint)] hover:bg-gray-200 disabled:opacity-30"
                disabled={isLoading} onClick={() => copyExpression(panelIdx, ei)} title="复制">
                <Copy className="h-3 w-3" />
              </button>
              <button type="button" className="rounded p-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                disabled={panel.expressions.length <= 1 || isLoading} onClick={() => removeExpression(panelIdx, ei)} title="删除">
                <X className="h-3 w-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button type="button" className="mt-1 text-xs text-[var(--color-primary)] hover:underline disabled:opacity-50"
        disabled={isLoading || panel.expressions.length >= 8} onClick={() => addExpression(panelIdx)}>
        + 添加表达式
      </button>
    </div>
  );
}

// ── Sub-component: Domain Editor ──

function DomainEditor({
  panel, panelIdx, isLoading, updateDomainIntervals, updateExcludePoints,
}: {
  panel: GraphSpecPanel;
  panelIdx: number;
  isLoading: boolean;
  updateDomainIntervals: (panelIdx: number, intervals: DomainInterval[]) => void;
  updateExcludePoints: (panelIdx: number, text: string) => void;
}) {
  const intervals = useMemo(() => domainIntervalsToGui(panel.domain), [panel.domain]);

  const addInterval = () => {
    updateDomainIntervals(panelIdx, [...intervals, { start: null, end: null, leftOpen: false, rightOpen: false }]);
  };

  const removeInterval = (idx: number) => {
    updateDomainIntervals(panelIdx, intervals.filter((_, i) => i !== idx));
  };

  const updateIntervalField = (idx: number, field: keyof DomainInterval, value: unknown) => {
    const next = intervals.map((iv, i) => i === idx ? { ...iv, [field]: value } : iv);
    updateDomainIntervals(panelIdx, next);
  };

  const excludeText = useMemo(() => {
    const pts = panel.domain?.exclude_points || [];
    return pts.join(", ");
  }, [panel.domain]);

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">定义域</p>

      {/* Intervals */}
      {intervals.length > 0 && (
        <div className="mb-2 space-y-1">
          {intervals.map((iv, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span className="text-xs text-[var(--color-text-hint)] w-5">{intervalDisplay(iv)}</span>
              <label className="flex items-center gap-1 text-[10px]">
                <input type="checkbox" checked={!iv.leftOpen} onChange={(e) => updateIntervalField(i, "leftOpen", !e.target.checked)}
                  className="rounded" disabled={isLoading} />
                包含左端
              </label>
              <DataTableNumberInput value={iv.start} onChange={(v) => updateIntervalField(i, "start", v)}
                placeholder="左" disabled={isLoading} className="w-20" />
              <DataTableNumberInput value={iv.end} onChange={(v) => updateIntervalField(i, "end", v)}
                placeholder="右" disabled={isLoading} className="w-20" />
              <label className="flex items-center gap-1 text-[10px]">
                <input type="checkbox" checked={!iv.rightOpen} onChange={(e) => updateIntervalField(i, "rightOpen", !e.target.checked)}
                  className="rounded" disabled={isLoading} />
                包含右端
              </label>
              <button type="button" className="rounded p-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                disabled={isLoading} onClick={() => removeInterval(i)}>
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" className="text-xs text-[var(--color-primary)] hover:underline disabled:opacity-50"
          disabled={isLoading} onClick={addInterval}>
          + 添加区间
        </button>
      </div>

      {/* Exclude points */}
      <div className="mt-2">
        <label className="text-[10px] text-[var(--color-text-hint)]">排除点（逗号分隔）</label>
        <input
          className="mt-0.5 w-full max-w-xs rounded-lg border bg-white px-2 py-1.5 text-xs font-mono"
          placeholder="例如: 0, 1, -2"
          value={excludeText}
          disabled={isLoading}
          onChange={(e) => updateExcludePoints(panelIdx, e.target.value)}
        />
      </div>
    </div>
  );
}

// ── Sub-component: Annotations Editor ──

function AnnotationsEditor({
  panel, panelIdx, isLoading, addAnnotation, updateAnnotation, removeAnnotation,
}: {
  panel: GraphSpecPanel;
  panelIdx: number;
  isLoading: boolean;
  addAnnotation: (panelIdx: number) => void;
  updateAnnotation: (panelIdx: number, annIdx: number, field: string, value: unknown) => void;
  removeAnnotation: (panelIdx: number, annIdx: number) => void;
}) {
  const annotations = panel.annotations || [];

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">
        注释和关键点（{annotations.length}/20）
      </p>
      {annotations.length > 0 && (
        <div className="mb-1 space-y-1.5">
          {annotations.map((ann, ai) => (
            <div key={ai} className="flex items-center gap-1.5 rounded-lg bg-gray-50/60 p-1.5">
              <DataTableNumberInput value={ann.x} onChange={(v) => updateAnnotation(panelIdx, ai, "x", v)}
                placeholder="x" disabled={isLoading} className="w-16" />
              <DataTableNumberInput value={ann.y} onChange={(v) => updateAnnotation(panelIdx, ai, "y", v)}
                placeholder="y" disabled={isLoading} className="w-16" />
              <input className="flex-1 rounded border bg-white px-2 py-1 text-xs"
                placeholder="标签（可选）" value={ann.label || ""} disabled={isLoading}
                onChange={(e) => updateAnnotation(panelIdx, ai, "label", e.target.value)} />
              <select className="w-16 rounded border bg-white px-1 py-1 text-xs"
                value={ann.point_style || "filled"} disabled={isLoading}
                onChange={(e) => updateAnnotation(panelIdx, ai, "point_style", e.target.value)}>
                {POINT_STYLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <input className="w-16 rounded border bg-white px-1 py-1 text-xs"
                type="color" value={ann.color || "#b91c1c"} disabled={isLoading}
                onChange={(e) => updateAnnotation(panelIdx, ai, "color", e.target.value)} />
              <button type="button" className="rounded p-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                disabled={isLoading} onClick={() => removeAnnotation(panelIdx, ai)}>
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button type="button" className="text-xs text-[var(--color-primary)] hover:underline disabled:opacity-50"
        disabled={isLoading || annotations.length >= 20} onClick={() => addAnnotation(panelIdx)}>
        + 添加注释
      </button>
    </div>
  );
}

// ── Sub-component: Reference Lines Editor ──

function RefLinesEditor({
  panel, panelIdx, isLoading, orientation, updateRefLine, addRefLine, removeRefLine,
}: {
  panel: GraphSpecPanel;
  panelIdx: number;
  isLoading: boolean;
  orientation: "vertical" | "horizontal";
  updateRefLine: (panelIdx: number, orientation: "vertical" | "horizontal", lineIdx: number, field: string, value: unknown) => void;
  addRefLine: (panelIdx: number, orientation: "vertical" | "horizontal") => void;
  removeRefLine: (panelIdx: number, orientation: "vertical" | "horizontal", lineIdx: number) => void;
}) {
  const key = orientation === "vertical" ? "vertical_lines" : "horizontal_lines";
  const label = orientation === "vertical" ? "垂直参考线" : "水平参考线";
  const lines: GraphSpecRefLine[] = (panel as Record<string, unknown>)[key] as GraphSpecRefLine[] || [];

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-[var(--color-text-secondary)]">{label}（{lines.length}）</p>
      {lines.length > 0 && (
        <div className="mb-1 space-y-1.5">
          {lines.map((line, li) => (
            <div key={li} className="flex items-center gap-1.5 rounded-lg bg-gray-50/60 p-1.5">
              <DataTableNumberInput value={line.value} onChange={(v) => updateRefLine(panelIdx, orientation, li, "value", v)}
                placeholder="值" disabled={isLoading} className="w-20" />
              <input className="flex-1 rounded border bg-white px-2 py-1 text-xs"
                placeholder="标签（可选）" value={line.label || ""} disabled={isLoading}
                onChange={(e) => updateRefLine(panelIdx, orientation, li, "label", e.target.value)} />
              <select className="w-16 rounded border bg-white px-1 py-1 text-xs"
                value={line.style || "dashed"} disabled={isLoading}
                onChange={(e) => updateRefLine(panelIdx, orientation, li, "style", e.target.value)}>
                {LINE_STYLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button type="button" className="rounded p-1 text-red-500 hover:bg-red-50 disabled:opacity-30"
                disabled={isLoading} onClick={() => removeRefLine(panelIdx, orientation, li)}>
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button type="button" className="text-xs text-[var(--color-primary)] hover:underline disabled:opacity-50"
        disabled={isLoading} onClick={() => addRefLine(panelIdx, orientation)}>
        + 添加{label}
      </button>
    </div>
  );
}
