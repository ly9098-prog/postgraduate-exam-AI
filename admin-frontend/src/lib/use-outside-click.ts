import { useEffect, type RefObject } from "react";

export function useOutsideClick(
  ref: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onClose: () => void,
  eventType: "mousedown" | "pointerdown" = "mousedown",
): void {
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener(eventType, handler);
    return () => document.removeEventListener(eventType, handler);
  }, [ref, isOpen, onClose, eventType]);
}
