"use client";

import { MixedLatexRenderer } from "@/components/ui/mixed-latex-renderer";
import { decodeApiText } from "@/lib/math-text";

type FunctionPropertiesPanelProps = {
  properties: Record<string, unknown>;
  className?: string;
};

const TEMPLATE_LABELS: Record<string, string> = {
  cartesian_2d: "二维直角坐标系",
  polar_2d: "二维极坐标系",
  parametric_2d: "二维参数方程",
};

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0;
  return true;
}

function PropertyRow({ label, value }: { label: string; value: unknown }) {
  if (!hasValue(value)) return null;

  return (
    <div className="grid gap-1 border-b border-[var(--color-border-light)] py-2 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
      <dt className="font-semibold text-[var(--ink)]">{label}</dt>
      <dd className="min-w-0 leading-7 text-[var(--color-text-secondary)]">
        <MixedLatexRenderer text={decodeApiText(value)} />
      </dd>
    </div>
  );
}

function ArrayPropertyRow({ label, value }: { label: string; value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return null;

  return (
    <div className="grid gap-1 border-b border-[var(--color-border-light)] py-2 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
      <dt className="font-semibold text-[var(--ink)]">{label}</dt>
      <dd className="min-w-0">
        <ul className="space-y-1.5 text-[var(--color-text-secondary)]">
          {value.map((item, index) => (
            <li key={index} className="flex gap-2 leading-7">
              <span aria-hidden className="mt-[0.72rem] h-1 w-1 shrink-0 rounded-full bg-current opacity-50" />
              <span className="min-w-0"><MixedLatexRenderer text={decodeApiText(item)} /></span>
            </li>
          ))}
        </ul>
      </dd>
    </div>
  );
}

function TransformationsRow({ value }: { value: unknown }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => hasValue(item));
  if (!entries.length) return null;

  return (
    <div className="grid gap-1 border-b border-[var(--color-border-light)] py-2 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
      <dt className="font-semibold text-[var(--ink)]">等价形式</dt>
      <dd className="min-w-0 space-y-1.5 text-[var(--color-text-secondary)]">
        {entries.map(([name, expression]) => (
          <div key={name} className="leading-7">
            <span className="mr-2 text-xs font-semibold text-[var(--color-text-hint)]">{name}</span>
            <MixedLatexRenderer text={decodeApiText(expression)} />
          </div>
        ))}
      </dd>
    </div>
  );
}

export function FunctionPropertiesPanel({ properties, className = "" }: FunctionPropertiesPanelProps) {
  const templateType = decodeApiText(properties.graph_template_type);

  return (
    <section className={`rounded-[1.6rem] border border-[var(--color-primary-light)] bg-[var(--porcelain)] p-4 ${className}`}>
      <p className="font-semibold text-[var(--ink)]">函数属性</p>
      <dl className="mt-2 text-sm">
        <PropertyRow label="表达式" value={properties.function_expression} />
        {templateType && (
          <div className="grid gap-1 border-b border-[var(--color-border-light)] py-2 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)]">
            <dt className="font-semibold text-[var(--ink)]">坐标模板</dt>
            <dd className="leading-7 text-[var(--color-text-secondary)]">
              {TEMPLATE_LABELS[templateType] ?? templateType}
            </dd>
          </div>
        )}
        <PropertyRow label="定义域" value={properties.domain} />
        <PropertyRow label="值域" value={properties.range} />
        <PropertyRow label="奇偶性" value={properties.parity} />
        <PropertyRow label="周期" value={properties.period} />
        <ArrayPropertyRow label="单调区间" value={properties.monotonic_intervals} />
        <PropertyRow label="极值" value={properties.extrema} />
        <PropertyRow label="零点" value={properties.zeros} />
        <PropertyRow label="渐近线" value={properties.asymptotes} />
        <ArrayPropertyRow label="凹凸区间" value={properties.concavity_intervals} />
        <ArrayPropertyRow label="拐点" value={properties.inflection_points} />
        <PropertyRow label="导数" value={properties.derivative_summary} />
        <PropertyRow label="图像特征" value={properties.one_line_feature} />
        <TransformationsRow value={properties.transformations} />
      </dl>
    </section>
  );
}
