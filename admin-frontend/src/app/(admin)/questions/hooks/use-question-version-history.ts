"use client";

import { useCallback, useEffect, useState } from "react";
import type { QuestionVersionSelection } from "@/components/questions/question-version-picker";
import { useQuestionVersion, useQuestionVersions } from "./use-question-queries";

export function useQuestionVersionHistory(questionId: number | null) {
  const [baseVersion, setBaseVersion] = useState<QuestionVersionSelection>("current");
  const [compareVersion, setCompareVersion] = useState<QuestionVersionSelection | null>(null);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);

  const versions = useQuestionVersions(questionId);
  const baseVersionDetail = useQuestionVersion(questionId, baseVersion);
  const compareVersionDetail = useQuestionVersion(questionId, compareVersion);

  useEffect(() => {
    if (!versionHistoryOpen || compareVersion !== null) return;
    const latestHistoricalVersion = versions.data?.items?.[0]?.version;
    if (latestHistoricalVersion !== undefined) {
      setCompareVersion(latestHistoricalVersion);
    }
  }, [compareVersion, versionHistoryOpen, versions.data?.items]);

  useEffect(() => {
    setVersionHistoryOpen(false);
    setBaseVersion("current");
    setCompareVersion(null);
  }, [questionId]);

  const toggleVersionHistory = useCallback(() => {
    setVersionHistoryOpen((open) => !open);
  }, []);

  const swapVersions = useCallback(() => {
    if (compareVersion === null) return;
    const previousBase = baseVersion;
    setBaseVersion(compareVersion);
    setCompareVersion(previousBase);
  }, [baseVersion, compareVersion]);

  return {
    versions,
    baseVersionDetail,
    compareVersionDetail,
    baseVersion,
    compareVersion,
    versionHistoryOpen,
    setBaseVersion,
    setCompareVersion,
    toggleVersionHistory,
    swapVersions,
  };
}
