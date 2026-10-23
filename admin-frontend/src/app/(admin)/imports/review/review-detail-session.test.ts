import { describe, expect, it } from "vitest";
import {
  beginReviewDetailSession,
  createReviewDetailSession,
  endReviewDetailSession,
  isReviewDetailReady,
  settleReviewDetailSession,
} from "./review-detail-session";

describe("review detail session", () => {
  it("requires the current open session to fetch before enabling edit", () => {
    const initial = createReviewDetailSession();
    const opened = beginReviewDetailSession(initial, 7);

    expect(isReviewDetailReady(opened, 7, 7)).toBe(false);
    const settled = settleReviewDetailSession(opened, opened.token);
    expect(isReviewDetailReady(settled, 7, 7)).toBe(true);
    expect(isReviewDetailReady(settled, null, 7)).toBe(false);
    expect(isReviewDetailReady(settled, 8, 7)).toBe(false);
  });

  it("ignores late responses from a closed or replaced session", () => {
    const first = beginReviewDetailSession(createReviewDetailSession(), 7);
    const second = beginReviewDetailSession(first, 8);
    const closed = endReviewDetailSession(second);

    expect(settleReviewDetailSession(second, first.token)).toBe(second);
    expect(settleReviewDetailSession(closed, second.token)).toBe(closed);
    expect(isReviewDetailReady(closed, null, 8)).toBe(false);
  });

  it("does not let a ready session authorize different detail data", () => {
    const opened = beginReviewDetailSession(createReviewDetailSession(), 7);
    const settled = settleReviewDetailSession(opened, opened.token);

    expect(isReviewDetailReady(settled, 7, undefined)).toBe(false);
    expect(isReviewDetailReady(settled, 7, 8)).toBe(false);
  });
});
