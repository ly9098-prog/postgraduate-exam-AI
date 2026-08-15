"use client";

import { useEffect, useMemo, useState } from "react";

const PALETTE = [
  { topStart: "#78aaff", topEnd: "#2f74df", sideStart: "#2a69ca", sideEnd: "#194c9f", dot: "#2f74df" },
  { topStart: "#ffc46f", topEnd: "#f59e0b", sideStart: "#dd8b08", sideEnd: "#a96305", dot: "#f59e0b" },
  { topStart: "#ff9696", topEnd: "#ef5b5b", sideStart: "#d74b4b", sideEnd: "#a73838", dot: "#ef5b5b" },
  { topStart: "#62d1b0", topEnd: "#15a37d", sideStart: "#118e6d", sideEnd: "#08694f", dot: "#15a37d" },
  { topStart: "#bca9f0", topEnd: "#8b6bd6", sideStart: "#7656c2", sideEnd: "#56399b", dot: "#8b6bd6" },
  { topStart: "#a9b7c8", topEnd: "#7b8da3", sideStart: "#65778d", sideEnd: "#46576c", dot: "#7b8da3" },
];

const STATUS_LABELS: Record<string, string> = {
  pending: "待审核",
  approved: "已审核",
  rejected: "已驳回",
  reviewing: "审核中",
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
  error: "异常",
};

type ReviewStatusDatum = { name: string; count: number };
type EnrichedDatum = ReviewStatusDatum & {
  rawName: string;
  pct: number;
  startAngle: number;
  endAngle: number;
  midAngle: number;
  paletteIndex: number;
};

type Point = { x: number; y: number };
type ArcSegment = { start: number; end: number };

const START_ANGLE = 16;
const DEPTH = 13;
const RADIUS_X = 112;
const RADIUS_Y = 66;
const CX = 165;
const CY = 105;
const ANIMATION_MS = 900;

function polarToCartesian(cx: number, cy: number, rx: number, ry: number, angle: number): Point {
  const rad = (Math.PI / 180) * angle;
  return {
    x: cx + rx * Math.cos(rad),
    y: cy + ry * Math.sin(rad),
  };
}

function describeArc(cx: number, cy: number, rx: number, ry: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, rx, ry, startAngle);
  const end = polarToCartesian(cx, cy, rx, ry, endAngle);
  const delta = Math.abs(endAngle - startAngle);
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${rx} ${ry} 0 ${delta > 180 ? 1 : 0} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

function describeTopSlice(cx: number, cy: number, rx: number, ry: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, rx, ry, startAngle);
  const end = polarToCartesian(cx, cy, rx, ry, endAngle);
  const delta = Math.abs(endAngle - startAngle);
  return [
    `M ${cx.toFixed(2)} ${cy.toFixed(2)}`,
    `L ${start.x.toFixed(2)} ${start.y.toFixed(2)}`,
    `A ${rx} ${ry} 0 ${delta > 180 ? 1 : 0} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

function getFrontSideSegments(startAngle: number, endAngle: number): ArcSegment[] {
  const segments: ArcSegment[] = [];
  const fromBand = Math.floor(startAngle / 360) - 1;
  const toBand = Math.ceil(endAngle / 360) + 1;

  for (let band = fromBand; band <= toBand; band += 1) {
    const frontStart = band * 360;
    const frontEnd = band * 360 + 180;
    const visibleStart = Math.max(startAngle, frontStart);
    const visibleEnd = Math.min(endAngle, frontEnd);
    if (visibleEnd > visibleStart) segments.push({ start: visibleStart, end: visibleEnd });
  }

  return segments;
}

function describeSideSurface(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  depth: number,
  startAngle: number,
  endAngle: number,
) {
  const topStart = polarToCartesian(cx, cy, rx, ry, startAngle);
  const topEnd = polarToCartesian(cx, cy, rx, ry, endAngle);
  const bottomEnd = polarToCartesian(cx, cy + depth, rx, ry, endAngle);
  const bottomStart = polarToCartesian(cx, cy + depth, rx, ry, startAngle);
  const delta = Math.abs(endAngle - startAngle);

  return [
    `M ${topStart.x.toFixed(2)} ${topStart.y.toFixed(2)}`,
    `A ${rx} ${ry} 0 ${delta > 180 ? 1 : 0} 1 ${topEnd.x.toFixed(2)} ${topEnd.y.toFixed(2)}`,
    `L ${bottomEnd.x.toFixed(2)} ${bottomEnd.y.toFixed(2)}`,
    `A ${rx} ${ry} 0 ${delta > 180 ? 1 : 0} 0 ${bottomStart.x.toFixed(2)} ${bottomStart.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

function formatValue(value: number) {
  return value.toLocaleString("zh-CN");
}

function easeOutQuint(value: number) {
  return 1 - Math.pow(1 - value, 5);
}

export function ReviewStatusChart({ data, animationKey }: { data: ReviewStatusDatum[]; animationKey?: number }) {
  const [activeName, setActiveName] = useState<string | null>(null);
  const [animationProgress, setAnimationProgress] = useState(0);

  const total = useMemo(() => data.reduce((sum, item) => sum + Math.max(0, item.count), 0), [data]);
  const enriched = useMemo<EnrichedDatum[]>(() => {
    const filtered = data.filter((item) => item.count > 0);
    if (!filtered.length || total <= 0) return [];

    let currentAngle = START_ANGLE;
    return filtered.map((item, index) => {
      const pct = (item.count / total) * 100;
      const sliceAngle = (item.count / total) * 360;
      const startAngle = currentAngle;
      const endAngle = currentAngle + sliceAngle;
      currentAngle = endAngle;
      return {
        ...item,
        rawName: item.name,
        name: STATUS_LABELS[item.name] ?? item.name,
        pct,
        startAngle,
        endAngle,
        midAngle: startAngle + sliceAngle / 2,
        paletteIndex: index % PALETTE.length,
      };
    });
  }, [data, total]);

  const dataSignature = useMemo(() => enriched.map((item) => `${item.rawName}:${item.count}`).join("|"), [enriched]);

  useEffect(() => {
    setActiveName(null);
    if (!enriched.length) {
      setAnimationProgress(0);
      return;
    }

    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setAnimationProgress(1);
      return;
    }

    let frame = 0;
    let startedAt = 0;
    setAnimationProgress(0);

    const tick = (timestamp: number) => {
      if (!startedAt) startedAt = timestamp;
      const raw = Math.min(1, (timestamp - startedAt) / ANIMATION_MS);
      setAnimationProgress(easeOutQuint(raw));
      if (raw < 1) frame = window.requestAnimationFrame(tick);
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [animationKey, dataSignature, enriched.length]);

  const activeEntry = useMemo(() => enriched.find((item) => item.name === activeName) ?? null, [activeName, enriched]);
  const animatedSweep = 360 * animationProgress;
  const animationFinished = animationProgress >= 0.999;
  const singleSlice = enriched.length === 1;

  const getVisibleEnd = (entry: EnrichedDatum) => {
    const offsetFromStart = entry.startAngle - START_ANGLE;
    const ownSweep = entry.endAngle - entry.startAngle;
    const visibleSweep = Math.min(ownSweep, Math.max(0, animatedSweep - offsetFromStart));
    return entry.startAngle + visibleSweep;
  };

  return (
    <div className="grid h-full min-h-[230px] grid-cols-1 items-center gap-1 px-4 pb-4 pt-2 sm:grid-cols-[minmax(250px,1fr)_minmax(210px,0.82fr)] sm:px-5">
      <div className="relative min-w-0">
        {activeEntry ? (
          <div className="pointer-events-none absolute left-3 top-3 z-10 translate-y-0 rounded-2xl border border-[var(--color-border-light)] bg-white/95 px-3.5 py-2.5 text-xs shadow-[0_12px_26px_rgba(37,61,89,0.12)] backdrop-blur transition-all duration-200">
            <p className="font-semibold text-[var(--ink)]">{activeEntry.name}</p>
            <p className="mt-1 text-[var(--color-text-secondary)]">
              {formatValue(activeEntry.count)}
              <span className="mx-1.5 text-[#b4c0cc]">•</span>
              {activeEntry.pct.toFixed(1)}%
            </p>
          </div>
        ) : null}

        <svg
          viewBox="0 0 342 232"
          className="h-[215px] w-full overflow-visible outline-none"
          aria-label="审核状态分布立体饼图"
          focusable="false"
          tabIndex={-1}
          style={{ outline: "none" }}
        >
          <defs>
            {PALETTE.map((palette, index) => (
              <linearGradient key={`pie-top-${index}`} id={`pie-top-${index}`} x1="0" y1="0" x2="0.9" y2="1">
                <stop offset="0%" stopColor={palette.topStart} />
                <stop offset="62%" stopColor={palette.topEnd} />
                <stop offset="100%" stopColor={palette.sideStart} />
              </linearGradient>
            ))}
            {PALETTE.map((palette, index) => (
              <linearGradient key={`pie-side-${index}`} id={`pie-side-${index}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={palette.sideStart} />
                <stop offset="100%" stopColor={palette.sideEnd} />
              </linearGradient>
            ))}
            <radialGradient id="pie-sheen" cx="32%" cy="25%" r="70%">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.27" />
              <stop offset="46%" stopColor="#ffffff" stopOpacity="0.07" />
              <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
            </radialGradient>
            <linearGradient id="pie-placeholder-top" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#edf3f8" />
              <stop offset="100%" stopColor="#dbe5ef" />
            </linearGradient>
          </defs>

          <ellipse cx={CX} cy={CY + DEPTH + 21} rx={RADIUS_X * 0.78} ry="13" fill="#31577f" opacity={0.055 * animationProgress} />

          {!enriched.length ? (
            <g opacity="0.85">
              <ellipse cx={CX} cy={CY + DEPTH} rx={RADIUS_X} ry={RADIUS_Y} fill="#c8d4df" />
              <ellipse cx={CX} cy={CY} rx={RADIUS_X} ry={RADIUS_Y} fill="url(#pie-placeholder-top)" stroke="#fff" strokeWidth="1.1" />
              <animate attributeName="opacity" values="0.58;0.88;0.58" dur="1.4s" repeatCount="indefinite" />
            </g>
          ) : singleSlice && animationFinished ? (
            <g
              transform={activeName === enriched[0].name ? "translate(0 -3)" : "translate(0 0)"}
              style={{ transition: "transform 180ms ease" }}
            >
              <animateTransform attributeName="transform" type="translate" from="0 -5" to="0 0" dur="240ms" additive="sum" />
              <ellipse cx={CX} cy={CY + DEPTH} rx={RADIUS_X} ry={RADIUS_Y} fill={`url(#pie-side-${enriched[0].paletteIndex})`} />
              <path
                d={describeArc(CX, CY + DEPTH, RADIUS_X, RADIUS_Y, 5, 175)}
                fill="none"
                stroke={PALETTE[enriched[0].paletteIndex].topStart}
                strokeOpacity="0.22"
                strokeWidth="1.4"
              />
              <ellipse
                cx={CX}
                cy={CY}
                rx={RADIUS_X}
                ry={RADIUS_Y}
                fill={`url(#pie-top-${enriched[0].paletteIndex})`}
                stroke="rgba(255,255,255,0.92)"
                strokeWidth="1.15"
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setActiveName(enriched[0].name)}
                onMouseLeave={() => setActiveName(null)}
              />
              <ellipse cx={CX - 17} cy={CY - 12} rx={RADIUS_X * 0.68} ry={RADIUS_Y * 0.43} fill="url(#pie-sheen)" pointerEvents="none" />
              {activeName === enriched[0].name ? (
                <ellipse cx={CX} cy={CY} rx={RADIUS_X + 3} ry={RADIUS_Y + 2} fill="none" stroke={PALETTE[enriched[0].paletteIndex].topStart} strokeOpacity="0.26" strokeWidth="3" />
              ) : null}
            </g>
          ) : (
            <>
              {enriched.flatMap((entry) => {
                const visibleEnd = getVisibleEnd(entry);
                if (visibleEnd <= entry.startAngle + 0.05) return [];
                const active = activeName === entry.name;
                const distance = active ? 6 : 0;
                const offsetX = Math.cos((entry.midAngle * Math.PI) / 180) * distance;
                const offsetY = Math.sin((entry.midAngle * Math.PI) / 180) * distance * 0.48;
                return getFrontSideSegments(entry.startAngle, visibleEnd).map((segment) => (
                  <path
                    key={`${entry.rawName}-side-${segment.start}-${segment.end}`}
                    d={describeSideSurface(CX + offsetX, CY + offsetY, RADIUS_X, RADIUS_Y, DEPTH, segment.start, segment.end)}
                    fill={`url(#pie-side-${entry.paletteIndex})`}
                    opacity={activeName && !active ? 0.56 : 1}
                    pointerEvents="none"
                  />
                ));
              })}

              {enriched.map((entry) => {
                const visibleEnd = getVisibleEnd(entry);
                if (visibleEnd <= entry.startAngle + 0.05) return null;
                const active = activeName === entry.name;
                const distance = active ? 6 : 0;
                const offsetX = Math.cos((entry.midAngle * Math.PI) / 180) * distance;
                const offsetY = Math.sin((entry.midAngle * Math.PI) / 180) * distance * 0.48;
                const inactive = activeName !== null && !active;

                return (
                  <g key={entry.rawName}>
                    <path
                      d={describeTopSlice(CX + offsetX, CY + offsetY, RADIUS_X, RADIUS_Y, entry.startAngle, visibleEnd)}
                      fill={`url(#pie-top-${entry.paletteIndex})`}
                      opacity={inactive ? 0.58 : 1}
                      stroke="#fff"
                      strokeWidth="1.05"
                      style={{ cursor: animationFinished ? "pointer" : "default", transition: "opacity 180ms ease" }}
                      onMouseEnter={() => animationFinished && setActiveName(entry.name)}
                      onMouseLeave={() => setActiveName(null)}
                    />
                    {active && animationFinished ? (
                      <path
                        d={describeArc(CX + offsetX, CY + offsetY, RADIUS_X + 2.5, RADIUS_Y + 1.5, entry.startAngle + 1, entry.endAngle - 1)}
                        fill="none"
                        stroke={PALETTE[entry.paletteIndex].topStart}
                        strokeOpacity="0.3"
                        strokeWidth="3"
                        pointerEvents="none"
                      />
                    ) : null}
                  </g>
                );
              })}

              <ellipse cx={CX - 18} cy={CY - 12} rx={RADIUS_X * 0.66} ry={RADIUS_Y * 0.4} fill="url(#pie-sheen)" opacity={0.72 * animationProgress} pointerEvents="none" />
            </>
          )}
        </svg>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 text-center">
          <span className="rounded-full border border-[var(--color-border-light)] bg-white/94 px-4 py-1 text-[11px] font-semibold text-[var(--color-text-hint)] shadow-sm">
            总题目 {formatValue(total)}
          </span>
        </div>
      </div>

      <div className="min-w-0 space-y-2 pt-2 sm:pt-0" style={{ opacity: 0.55 + animationProgress * 0.45 }}>
        {enriched.length ? (
          enriched.slice(0, 6).map((entry) => {
            const active = activeName === entry.name;
            const dimmed = activeName !== null && !active;
            return (
              <button
                type="button"
                key={entry.rawName}
                onMouseEnter={() => animationFinished && setActiveName(entry.name)}
                onMouseLeave={() => setActiveName(null)}
                className={`grid w-full grid-cols-[auto_1fr_auto] items-center gap-2 rounded-xl border px-2.5 py-2 text-left outline-none transition-all duration-200 ${
                  active
                    ? "border-[#d9e6f4] bg-[#f7faff] shadow-[0_5px_16px_rgba(47,116,223,0.08)]"
                    : "border-transparent hover:border-[var(--color-border-light)] hover:bg-[#f8fbff]"
                }`}
                style={{ opacity: dimmed ? 0.48 : 1 }}
              >
                <span
                  className="h-2.5 w-2.5 rounded-full shadow-sm transition-transform duration-200"
                  style={{ backgroundColor: PALETTE[entry.paletteIndex].dot, transform: active ? "scale(1.25)" : "scale(1)" }}
                />
                <span className="truncate text-sm font-semibold text-[var(--color-text-secondary)]">{entry.name}</span>
                <span className="whitespace-nowrap text-sm tabular-nums text-[var(--color-text-hint)]">
                  {formatValue(entry.count)}
                  <span className="mx-1.5 text-[#b4c0cc]">•</span>
                  {entry.pct.toFixed(1)}%
                </span>
              </button>
            );
          })
        ) : (
          <div className="rounded-xl border border-dashed border-[var(--color-border)] px-4 py-5 text-center text-xs text-[var(--color-text-hint)]">
            正在加载审核状态…
          </div>
        )}
      </div>
    </div>
  );
}
