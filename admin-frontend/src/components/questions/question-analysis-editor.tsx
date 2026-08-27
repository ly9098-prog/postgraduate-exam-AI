"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";

type AnalysisObject = Record<string, unknown>;

type AnalysisModule = {
  key: string;
  value: unknown;
};

type PresetModule = {
  key: string;
  title: string;
  description: string;
  placeholder: string;
};

const PRESET_MODULES: PresetModule[] = [
  {
    key: "mistake_diagnosis",
    title: "失误诊断",
    description: "填写本题容易出错的判断、条件或思维环节。",
    placeholder: "例如：容易只看到题干关键词，而忽略限定条件……",
  },
  {
    key: "knowledge_patch",
    title: "知识补丁",
    description: "补充本题对应的规则、概念、边界条件和判断依据。",
    placeholder: "例如：循环队列入队/出队时需要检查的关键条件……",
  },
  {
    key: "review_task",
    title: "复盘任务",
    description: "填写下次复习时建议执行的检查或练习动作。",
    placeholder: "例如：遮住选项，独立写出规则并逐项验证……",
  },
  {
    key: "explanation",
    title: "解题说明",
    description: "补充题目整体思路与关键推导。",
    placeholder: "填写解题思路……",
  },
  {
    key: "solution",
    title: "解题步骤",
    description: "按步骤记录完整解题过程。",
    placeholder: "填写解题步骤……",
  },
  {
    key: "key_point",
    title: "关键点",
    description: "记录本题最需要优先关注的信息。",
    placeholder: "填写关键点……",
  },
];

function normalizeKey(key: string) {
  return key.toLowerCase().replace(/[\s_-]+/g, "");
}

function canonicalKey(key: string) {
  const normalized = normalizeKey(key);
  if (normalized === "mistakediagnosis" || normalized === "errordiagnosis") return "mistakediagnosis";
  if (normalized === "knowledgepatch" || normalized === "knowledgepoint") return "knowledgepatch";
  if (normalized === "reviewtask" || normalized === "reviewask") return "reviewtask";
  if (normalized === "keypoint") return "keypoint";
  return normalized;
}

function findPreset(key: string): PresetModule | undefined {
  const canonical = canonicalKey(key);
  return PRESET_MODULES.find((item) => canonicalKey(item.key) === canonical);
}

function stripCodeFence(value: string) {
  const trimmed = value.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1].trim() : trimmed;
}

function parseAnalysis(value?: string | null): AnalysisModule[] {
  const raw = String(value ?? "").trim();
  if (!raw) return [];

  const candidate = stripCodeFence(raw);
  try {
    let parsed = JSON.parse(candidate) as unknown;
    if (typeof parsed === "string") {
      const nested = stripCodeFence(parsed);
      if (nested.startsWith("{")) parsed = JSON.parse(nested) as unknown;
    }
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return Object.entries(parsed as AnalysisObject).map(([key, item]) => ({
        key,
        value: item,
      }));
    }
  } catch {
    // Legacy/plain text analysis is represented as an editable explanation
    // module instead of exposing a raw JSON editor.
  }

  return [{ key: "explanation", value: raw }];
}

function valueAsText(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function modulesToAnalysis(modules: AnalysisModule[]) {
  if (modules.length === 0) return "";
  return JSON.stringify(
    Object.fromEntries(modules.map((module) => [module.key, module.value])),
  );
}

function titleFromKey(key: string) {
  const preset = findPreset(key);
  if (preset) return preset.title;
  return (
    key
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .trim()
      .replace(/^./, (char) => char.toUpperCase()) || "自定义模块"
  );
}

export function QuestionAnalysisEditor({
  value,
  onChange,
}: {
  value?: string | null;
  onChange: (value: string) => void;
}) {
  const modules = useMemo(() => parseAnalysis(value), [value]);
  const [moduleToAdd, setModuleToAdd] = useState(PRESET_MODULES[0].key);
  const [customKey, setCustomKey] = useState("");
  const [removingKey, setRemovingKey] = useState<string | null>(null);
  const [enteringKey, setEnteringKey] = useState<string | null>(null);
  const timersRef = useRef<number[]>([]);
  const modulesRef = useRef(modules);
  modulesRef.current = modules;

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  const schedule = (callback: () => void, delay: number) => {
    const timer = window.setTimeout(callback, delay);
    timersRef.current.push(timer);
  };

  const existingKeys = useMemo(
    () => new Set(modules.map((module) => canonicalKey(module.key))),
    [modules],
  );

  const availablePresets = PRESET_MODULES.filter(
    (preset) => !existingKeys.has(canonicalKey(preset.key)),
  );
  const selectedPresetKey = availablePresets.some((item) => item.key === moduleToAdd)
    ? moduleToAdd
    : availablePresets[0]?.key ?? "";
  const presetOptions = availablePresets.map((preset) => ({
    value: preset.key,
    label: preset.title,
    suffix: preset.key,
  }));

  const updateModule = (key: string, nextValue: string) => {
    onChange(
      modulesToAnalysis(
        modules.map((module) =>
          module.key === key ? { ...module, value: nextValue } : module,
        ),
      ),
    );
  };

  const deleteModule = (key: string) => {
    if (removingKey) return;
    setRemovingKey(key);
    schedule(() => {
      onChange(modulesToAnalysis(modulesRef.current.filter((module) => module.key !== key)));
      setRemovingKey(null);
    }, 170);
  };

  const addPreset = () => {
    const key = selectedPresetKey;
    if (!key) return;

    setEnteringKey(key);
    onChange(modulesToAnalysis([...modules, { key, value: "" }]));
    const remaining = availablePresets.find((item) => item.key !== key);
    if (remaining) setModuleToAdd(remaining.key);
    schedule(() => setEnteringKey(null), 220);
  };

  const addCustomModule = () => {
    const key = customKey.trim();
    if (!key || existingKeys.has(canonicalKey(key))) return;
    setEnteringKey(key);
    onChange(modulesToAnalysis([...modules, { key, value: "" }]));
    setCustomKey("");
    schedule(() => setEnteringKey(null), 220);
  };

  return (
    <section className="border-t border-slate-200 pt-6">
      <style>{`
        @keyframes questionAnalysisModuleEnter {
          from { opacity: 0; transform: translateY(-8px) scale(.985); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes questionAnalysisModuleExit {
          from { opacity: 1; transform: translateY(0) scale(1); }
          to { opacity: 0; transform: translateY(-6px) scale(.985); }
        }
        .question-analysis-module-enter { animation: questionAnalysisModuleEnter 190ms cubic-bezier(.2,.8,.2,1); }
        .question-analysis-module-exit { animation: questionAnalysisModuleExit 170ms ease-in forwards; pointer-events: none; }
        @media (prefers-reduced-motion: reduce) {
          .question-analysis-module-enter, .question-analysis-module-exit { animation: none !important; }
        }
      `}</style>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-950">解析</p>
          <p className="mt-1.5 text-[11px] leading-5 text-slate-400">
            将解析拆分为独立模块，保持内容结构清晰、便于维护。
          </p>
        </div>
        {modules.length > 0 ? (
          <span className="shrink-0 rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium tabular-nums text-slate-500">
            {modules.length} 个模块
          </span>
        ) : null}
      </div>

      {modules.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {modules.map((module, index) => {
            const preset = findPreset(module.key);
            return (
              <section
                key={`${module.key}-${index}`}
                className={`border-b border-slate-200 p-4 last:border-b-0 transition-colors hover:bg-slate-50/40 ${
                  enteringKey === module.key ? "question-analysis-module-enter" : ""
                } ${removingKey === module.key ? "question-analysis-module-exit" : ""}`}
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-900">
                        {titleFromKey(module.key)}
                      </p>
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-normal text-slate-400">
                        {module.key}
                      </code>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-slate-400">
                      {preset?.description ?? "自定义解析模块"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => deleteModule(module.key)}
                    disabled={removingKey !== null}
                    className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-slate-400 transition hover:bg-red-50 hover:text-red-500 disabled:cursor-default disabled:opacity-40"
                    aria-label={`删除${titleFromKey(module.key)}`}
                    title="删除模块"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </button>
                </div>
                <textarea
                  className="min-h-28 w-full resize-y rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2.5 text-sm leading-6 text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
                  value={valueAsText(module.value)}
                  placeholder={preset?.placeholder ?? "填写该模块内容……"}
                  onChange={(event) => updateModule(module.key, event.target.value)}
                />
              </section>
            );
          })}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center">
          <p className="text-sm font-medium text-slate-600">暂无解析模块</p>
          <p className="mt-1 text-xs text-slate-400">可在下方添加失误诊断、知识补丁、复盘任务等模块。</p>
        </div>
      )}

      <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-3.5">
        <p className="mb-2 text-xs font-semibold text-slate-600">添加模块</p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="min-w-0 flex-1">
            <CustomSelect
              value={selectedPresetKey}
              onChange={setModuleToAdd}
              options={presetOptions}
              placeholder={availablePresets.length > 0 ? "选择要添加的模块" : "预设模块已全部添加"}
              disabled={availablePresets.length === 0}
              clearable={false}
              className="h-10 border-slate-200 bg-white shadow-none"
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            className="shrink-0 border-slate-200 bg-white shadow-none"
            onClick={addPreset}
            disabled={availablePresets.length === 0 || !selectedPresetKey}
          >
            <Plus className="h-4 w-4" />
            添加模块
          </Button>
        </div>

        <div className="my-3 flex items-center gap-3 text-[10px] text-slate-400">
          <span className="h-px flex-1 bg-slate-200" />
          或自定义模块
          <span className="h-px flex-1 bg-slate-200" />
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 font-mono text-xs text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            value={customKey}
            placeholder="自定义模块标识，例如 common_mistake"
            onChange={(event) => setCustomKey(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addCustomModule();
              }
            }}
          />
          <Button
            type="button"
            variant="secondary"
            className="shrink-0 border-slate-200 bg-white shadow-none"
            onClick={addCustomModule}
            disabled={
              !customKey.trim() || existingKeys.has(canonicalKey(customKey.trim()))
            }
          >
            <Plus className="h-4 w-4" />
            添加自定义模块
          </Button>
        </div>
        {customKey.trim() && existingKeys.has(canonicalKey(customKey.trim())) ? (
          <p className="mt-1.5 text-[11px] text-red-500">该模块标识已存在，请换一个名称。</p>
        ) : null}
      </div>
    </section>
  );
}
