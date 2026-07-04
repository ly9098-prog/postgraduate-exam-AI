export function renderValue(value: unknown, indent = 0): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[序列化异常]";
  }
}

export function renderOptions(options: unknown): string {
  if (!options) return "—";
  if (typeof options === "string") return options;
  if (Array.isArray(options)) {
    return options.map((opt, i) => {
      if (typeof opt === "string") return `${String.fromCharCode(65 + i)}. ${opt}`;
      if (typeof opt === "object" && opt !== null) {
        const key = opt.key || String.fromCharCode(65 + i);
        const text = opt.text || opt.value || opt.label || JSON.stringify(opt);
        return `${key}. ${text}`;
      }
      return `${String.fromCharCode(65 + i)}. ${String(opt)}`;
    }).join("\n");
  }
  if (typeof options === "object" && options !== null) {
    const obj = options as Record<string, unknown>;
    return Object.entries(obj)
      .map(([key, val]) => `${key}. ${typeof val === "string" ? val : JSON.stringify(val)}`)
      .join("\n");
  }
  return JSON.stringify(options);
}
