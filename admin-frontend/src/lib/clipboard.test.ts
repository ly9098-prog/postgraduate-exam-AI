import { afterEach, describe, expect, it, vi } from "vitest";
import { copyTextToClipboard } from "@/lib/clipboard";

afterEach(() => vi.unstubAllGlobals());

function fallbackDocument(copied: boolean) {
  const range = {};
  const selection = {
    rangeCount: 1,
    getRangeAt: vi.fn(() => ({ cloneRange: () => range })),
    removeAllRanges: vi.fn(),
    addRange: vi.fn(),
  };
  class Element {
    focus = vi.fn();
  }
  const activeElement = new Element();
  const textarea = {
    value: "",
    readOnly: false,
    style: { cssText: "" },
    focus: vi.fn(),
    select: vi.fn(),
    remove: vi.fn(),
  };
  const document = {
    activeElement,
    getSelection: () => selection,
    createElement: vi.fn(() => textarea),
    body: { appendChild: vi.fn() },
    execCommand: vi.fn(() => copied),
  };
  vi.stubGlobal("HTMLElement", Element);
  vi.stubGlobal("document", document);
  return { document, textarea, activeElement, selection, range };
}

describe("copyTextToClipboard", () => {
  it("writes exact text to the modern clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const text = String.raw`题目：$\frac{1}{2}$`;
    await copyTextToClipboard(text);
    expect(writeText).toHaveBeenCalledWith(text);
  });

  it.each(["unavailable", "rejected"])(
    "falls back when the clipboard API is %s and restores focus/selection", async (mode) => {
      vi.stubGlobal("navigator", mode === "unavailable"
        ? {}
        : { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("Permission denied")) } });
      const { document, textarea, activeElement, selection, range } = fallbackDocument(true);
      await copyTextToClipboard("题目：\n文本");
      expect(textarea.value).toBe("题目：\n文本");
      expect(document.execCommand).toHaveBeenCalledWith("copy");
      expect(textarea.remove).toHaveBeenCalledOnce();
      expect(activeElement.focus).toHaveBeenCalledWith({ preventScroll: true });
      expect(selection.addRange).toHaveBeenCalledWith(range);
    },
  );

  it("reports failure and removes the temporary field when fallback copying is denied", async () => {
    vi.stubGlobal("navigator", {});
    const { textarea, activeElement } = fallbackDocument(false);
    await expect(copyTextToClipboard("文本")).rejects.toThrow("Clipboard copy failed");
    expect(textarea.remove).toHaveBeenCalledOnce();
    expect(activeElement.focus).toHaveBeenCalledOnce();
  });
});
