"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const MESSAGE_AUTO_CLOSE_MS = 3800;

type FeedbackTimer = (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;

export function useQuestionFeedback(
  scheduleTimer: FeedbackTimer = (callback, delay) => setTimeout(callback, delay),
  cancelTimer: (timer: ReturnType<typeof setTimeout>) => void = clearTimeout,
) {
  const [message, setMessage] = useState<string | null>(null);
  const scheduleTimerRef = useRef(scheduleTimer);
  const cancelTimerRef = useRef(cancelTimer);

  useEffect(() => {
    scheduleTimerRef.current = scheduleTimer;
    cancelTimerRef.current = cancelTimer;
  }, [cancelTimer, scheduleTimer]);

  useEffect(() => {
    if (!message) return;
    const schedule = scheduleTimerRef.current;
    const timer = schedule(() => setMessage(null), MESSAGE_AUTO_CLOSE_MS);
    return () => {
      const cancel = cancelTimerRef.current;
      cancel(timer);
    };
  }, [message]);

  const clearMessage = useCallback(() => setMessage(null), []);

  return { message, setMessage, clearMessage };
}
