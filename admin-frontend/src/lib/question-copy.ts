import {
  normalizeQuestionOptions,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
  type NormalizedQuestionOption,
} from "@/lib/question-options";
import { canonicalizeQuestionType } from "@/lib/question-types";
import { looksLikeProgrammingCode } from "@/lib/math-text";
import { isTableSegment, normalizeStructuredTableSegment } from "@/lib/structured-table";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

// Decode text entities without parsing HTML or touching LaTeX backslashes.
function copyText(value: string): string {
  const entities: Record<string, string> = {
    amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
  };
  return value.replace(/\r\n?/g, "\n").replace(
    /&(?:#(x[\da-f]+|\d+)|(amp|lt|gt|quot|apos|nbsp));/gi,
    (entity, numeric: string | undefined, named: string | undefined) => {
      if (named) return entities[named.toLowerCase()] ?? entity;
      const code = numeric?.toLowerCase().startsWith("x")
        ? Number.parseInt(numeric.slice(1), 16)
        : Number(numeric);
      return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff)
        ? String.fromCodePoint(code)
        : entity;
    },
  );
}

function stemText(content: unknown): string {
  if (typeof content === "string") return content;
  const record = asRecord(content);
  if (!record) return "";
  const canonical = [record.stem, record.text, record.question, record.title]
    .find((value): value is string => typeof value === "string" && value.length > 0) ?? "";
  const segments = Array.isArray(record.segments)
    ? record.segments.map(asRecord).filter(
      (segment): segment is Record<string, unknown> => segment !== null && !segment.option_key,
    )
    : [];
  const typeOf = (segment: Record<string, unknown>) => String(segment.type ?? "").trim().toLowerCase();
  if (!segments.length) return canonical;
  if (canonical && segments.every((segment) => ["text", "newline"].includes(typeOf(segment)))
    && looksLikeProgrammingCode(canonical)) return canonical;

  const blocks: string[] = [];
  let text = "";
  let hasText = false;
  const flush = () => {
    if (text) blocks.push(text);
    text = "";
  };
  for (const segment of segments) {
    const type = typeOf(segment);
    if (type === "text" || type === "newline") {
      text += type === "newline" ? "\n" : String(segment.text ?? "");
      hasText = true;
      continue;
    }
    flush();
    if (type === "code") {
      blocks.push([segment.caption, segment.code ?? segment.text]
        .filter((value) => typeof value === "string" && value.length > 0).join("\n"));
    } else if (isTableSegment(segment)) {
      const table = normalizeStructuredTableSegment(segment);
      if (table) blocks.push([table.caption, table.markdown].filter(Boolean).join("\n"));
    } else if (!["image", "math_image", "table_image", "code_image"].includes(type)) {
      if (typeof segment.text === "string") blocks.push(segment.text);
    }
  }
  flush();
  if (!hasText && canonical.trim() && !blocks.some((block) => block.trim() === canonical.trim())) {
    blocks.unshift(canonical);
  }
  return blocks.filter(Boolean).join("\n");
}

function optionLines(options: NormalizedQuestionOption[]): string {
  return options.map((option) => {
    const text = option.text ? copyText(option.text) : option.imageUrl ? "（图片选项）" : "";
    return `${option.key}.${text}`;
  }).join("\n");
}

/** Copy source text rather than KaTeX DOM, which repeats formulas and loses LaTeX syntax. */
export function buildQuestionCopyText(question: Record<string, unknown>): string {
  const stem = copyText(stemText(question.content)).trim();
  const type = canonicalizeQuestionType(String(question.question_type ?? ""));
  let options = "";
  if (type === "multi_blank_choice" || type === "multi_blank_multiple_choice") {
    options = resolveQuestionBlankOptionGroups(question)
      .map((group) => `${group.id}：\n${optionLines(group.options)}`).join("\n\n");
  } else {
    options = optionLines(normalizeQuestionOptions(resolveQuestionOptions(question)));
  }
  return [`题目：\n${stem}`, options ? `选项：\n${options}` : ""].filter(Boolean).join("\n\n");
}
