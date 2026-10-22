import type { ReviewActionState } from "./review-action-requests";

export type ReviewActionDialogState = {
  selectedIds: Set<number>;
  confirmState: ReviewActionState | null;
  rejectReason: string;
  message: string | null;
};

export type ReviewActionDialogAction =
  | { type: "open"; action: ReviewActionState }
  | { type: "cancel" }
  | { type: "reject-reason"; reason: string }
  | { type: "selected-ids"; selectedIds: Set<number> }
  | {
      type: "update-selected-ids";
      update: (current: Set<number>) => Set<number>;
    }
  | { type: "message"; message: string | null }
  | { type: "reset" };

export function createReviewActionDialogState(): ReviewActionDialogState {
  return {
    selectedIds: new Set(),
    confirmState: null,
    rejectReason: "",
    message: null,
  };
}

export function reduceReviewActionDialogState(
  state: ReviewActionDialogState,
  action: ReviewActionDialogAction,
): ReviewActionDialogState {
  switch (action.type) {
    case "open":
      return { ...state, confirmState: action.action };
    case "cancel":
      return { ...state, confirmState: null };
    case "reject-reason":
      return { ...state, rejectReason: action.reason };
    case "selected-ids":
      return { ...state, selectedIds: action.selectedIds };
    case "update-selected-ids":
      return {
        ...state,
        selectedIds: action.update(state.selectedIds),
      };
    case "message":
      return { ...state, message: action.message };
    case "reset":
      return {
        ...state,
        selectedIds: new Set(),
        confirmState: null,
        rejectReason: "",
      };
  }
}
