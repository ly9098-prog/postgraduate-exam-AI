export type ReviewDetailSession = {
  activeId: number | null;
  token: number;
  readyToken: number | null;
};

export function createReviewDetailSession(): ReviewDetailSession {
  return { activeId: null, token: 0, readyToken: null };
}

export function beginReviewDetailSession(
  state: ReviewDetailSession,
  id: number,
): ReviewDetailSession {
  const token = state.token + 1;
  return { activeId: id, token, readyToken: null };
}

export function settleReviewDetailSession(
  state: ReviewDetailSession,
  token: number,
): ReviewDetailSession {
  if (state.token !== token || state.activeId === null) return state;
  return { ...state, readyToken: token };
}

export function endReviewDetailSession(state: ReviewDetailSession): ReviewDetailSession {
  return { activeId: null, token: state.token + 1, readyToken: null };
}

export function isReviewDetailReady(
  state: ReviewDetailSession,
  previewId: number | null,
  detailId: number | undefined,
): boolean {
  return previewId !== null &&
    state.activeId === previewId &&
    state.readyToken === state.token &&
    detailId === previewId;
}
