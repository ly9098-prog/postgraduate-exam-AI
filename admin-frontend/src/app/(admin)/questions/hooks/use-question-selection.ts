import { useCallback, useState } from "react";
import { toggleAllSelection, toggleSingleSelection } from "@/lib/selection-ops";

export function useQuestionSelection({
  items,
}: {
  items: Array<{ id: number }>;
}) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const allChecked =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedIds(() => toggleAllSelection(items.map((item) => item.id), allChecked));
  }, [allChecked, items]);

  const toggleOne = useCallback((id: number) => {
    setSelectedIds((current) => toggleSingleSelection(current, id));
  }, []);

  return { selectedIds, allChecked, clearSelection, toggleAll, toggleOne };
}
