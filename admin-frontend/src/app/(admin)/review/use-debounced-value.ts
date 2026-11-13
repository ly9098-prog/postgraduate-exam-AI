"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Delay a rapidly changing value (e.g. a search keyword) before it reaches a
 * query. `onCommit` runs in the same timer tick as the debounced state update,
 * so callers can reset pagination in the same render instead of firing an
 * intermediate request for the old keyword.
 */
export function useDebouncedValue<T>(
  value: T,
  delayMs = 300,
  onCommit?: (value: T) => void,
): T {
  const [debounced, setDebounced] = useState(value);
  const onCommitRef = useRef(onCommit);

  useEffect(() => {
    onCommitRef.current = onCommit;
  }, [onCommit]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
      onCommitRef.current?.(value);
    }, delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
