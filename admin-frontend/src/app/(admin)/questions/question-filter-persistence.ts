import type { QuestionListFilters } from "./question-list-state";

const SAVED_FILTER_KEY = "admin-question-saved-filter";

export type FilterStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type FilterStorageProvider = () => FilterStorage;

export type SaveFilterResult =
  | { ok: true }
  | { ok: false; message: string };

export type ApplySavedFilterResult =
  | { ok: true; filters: Partial<QuestionListFilters> }
  | { ok: false; message: string; closeMenu: boolean };

export function saveCurrentFilters(
  getStorage: FilterStorageProvider,
  filters: QuestionListFilters,
): SaveFilterResult {
  try {
    getStorage().setItem(SAVED_FILTER_KEY, JSON.stringify(filters));
    return { ok: true };
  } catch {
    return { ok: false, message: "筛选保存失败，请检查浏览器存储权限。 " };
  }
}

export function loadSavedFilters(
  getStorage: FilterStorageProvider,
): ApplySavedFilterResult {
  try {
    const raw = getStorage().getItem(SAVED_FILTER_KEY);
    if (!raw) {
      return { ok: false, message: "暂无已保存的筛选条件。 ", closeMenu: true };
    }
    const parsed = JSON.parse(raw) as Partial<QuestionListFilters>;
    // Older saved presets used an empty is_active value to mean "all".
    // Treat that legacy value as active-only so soft-deleted questions stay hidden.
    return {
      ok: true,
      filters: {
        ...parsed,
        is_active: parsed.is_active === "false" ? "false" : "true",
      },
    };
  } catch {
    return { ok: false, message: "已保存的筛选条件无法读取。 ", closeMenu: true };
  }
}
