/** Toggle all item IDs: select all if not all checked, deselect all otherwise. */
export function toggleAllSelection<T>(
  itemIds: T[],
  allChecked: boolean,
): Set<T> {
  if (allChecked) return new Set();
  return new Set(itemIds);
}

/** Toggle a single ID in a selection set, returning a new set. */
export function toggleSingleSelection<T>(
  selectedIds: Set<T>,
  id: T,
): Set<T> {
  const next = new Set(selectedIds);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
