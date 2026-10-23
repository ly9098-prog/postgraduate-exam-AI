import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { useQuestionDeleteDialog } from "./use-question-delete-dialog";

function renderHook(selectedIds: Set<number>, selectedQuestionId: number | null) {
  const actions = {
    clearSelection: vi.fn(),
    setSelectedQuestionId: vi.fn(),
    closeDetailDrawer: vi.fn(),
    onMessage: vi.fn(),
  };
  let result!: ReturnType<typeof useQuestionDeleteDialog>;
  function Probe() {
    result = useQuestionDeleteDialog(selectedIds, selectedQuestionId, actions);
    return null;
  }
  const client = new QueryClient();
  renderToStaticMarkup(createElement(
    QueryClientProvider,
    { client },
    createElement(Probe),
  ));
  return { actions, result };
}

describe("question delete dialog", () => {
  it("starts without a confirmation and exposes each action", () => {
    const { result } = renderHook(new Set([1]), 1);

    expect(result.confirmState).toBeNull();
    expect(result.deleteDescription).toBe(
      "删除后该题目将从题库永久移除，此操作不可撤销。",
    );
    expect(typeof result.requestBatchDelete).toBe("function");
    expect(typeof result.requestDelete).toBe("function");
    expect(typeof result.cancelDelete).toBe("function");
    expect(typeof result.confirmDelete).toBe("function");
  });
});
