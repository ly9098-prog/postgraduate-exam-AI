import { useCallback, useEffect, useRef, useState } from "react";
import { useOutsideClick } from "@/lib/use-outside-click";

export type QuestionMenus = {
  isCommonFilterOpen: boolean;
  isMoreFilterOpen: boolean;
  isExportOpen: boolean;
};

export type QuestionMenuKind = keyof QuestionMenus;

const QUESTION_MENU_KINDS = ["isCommonFilterOpen", "isMoreFilterOpen", "isExportOpen"] as const;

export function toggleQuestionMenu(
  current: QuestionMenus,
  kind: QuestionMenuKind,
): QuestionMenus {
  const next = {} as QuestionMenus;
  for (const menuKind of QUESTION_MENU_KINDS) {
    next[menuKind] = menuKind === kind ? !current[kind] : false;
  }
  return next;
}

export function closeQuestionMenus(): QuestionMenus {
  return {
    isCommonFilterOpen: false,
    isMoreFilterOpen: false,
    isExportOpen: false,
  };
}

export function closeQuestionMenu(
  current: QuestionMenus,
  kind: QuestionMenuKind,
): QuestionMenus {
  return current[kind] ? { ...current, [kind]: false } : current;
}

export function useQuestionMenus() {
  const [menus, setMenus] = useState<QuestionMenus>(closeQuestionMenus);
  const commonFilterMenuRef = useRef<HTMLDivElement | null>(null);
  const moreFilterRef = useRef<HTMLDivElement | null>(null);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);

  const toggleMenu = useCallback((kind: QuestionMenuKind) => {
    setMenus(current => toggleQuestionMenu(current, kind));
  }, []);
  const closeCommonFilterMenu = useCallback(() => {
    setMenus(current => closeQuestionMenu(current, "isCommonFilterOpen"));
  }, []);
  const closeAllMenus = useCallback(() => setMenus(closeQuestionMenus), []);

  useEffect(() => {
    if (!Object.values(menus).some(Boolean)) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      closeAllMenus();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closeAllMenus, menus]);

  useOutsideClick(commonFilterMenuRef, menus.isCommonFilterOpen, closeCommonFilterMenu, "pointerdown");
  useOutsideClick(moreFilterRef, menus.isMoreFilterOpen, closeAllMenus, "pointerdown");
  useOutsideClick(exportMenuRef, menus.isExportOpen, closeAllMenus, "pointerdown");

  return {
    menus,
    commonFilterMenuRef,
    moreFilterRef,
    exportMenuRef,
    toggleMenu,
    closeCommonFilterMenu,
    closeAllMenus,
  };
}
