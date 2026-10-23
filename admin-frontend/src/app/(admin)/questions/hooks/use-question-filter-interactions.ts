"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DEFAULT_QUESTION_FILTERS, type QuestionListFilters } from "../question-list-state";
import { loadSavedFilters, saveCurrentFilters, type FilterStorage } from "../question-filter-persistence";

const KEYWORD_DEBOUNCE_MS = 300;
const IMPORT_BATCH_DEBOUNCE_MS = 450;

type FilterInteractionsOptions = {
  initialFilters: QuestionListFilters;
  onFilterChanged: (key: keyof QuestionListFilters, value: string) => void;
  onFilterPresetApplied: (filters: QuestionListFilters) => void;
  onPageSizeChanged: (pageSize: number) => void;
  onMessage: (message: string) => void;
  getStorage: () => FilterStorage;
};

export function useQuestionFilterInteractions({
  initialFilters,
  onFilterChanged,
  onFilterPresetApplied,
  onPageSizeChanged,
  onMessage,
  getStorage,
}: FilterInteractionsOptions) {
  const [keywordInput, setKeywordInput] = useState(initialFilters.keyword);
  const [importBatchInput, setImportBatchInput] = useState(initialFilters.import_batch_id);
  const [searchDebouncing, setSearchDebouncing] = useState(false);
  const keywordTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importBatchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const filtersRef = useRef(initialFilters);
  const onFilterChangedRef = useRef(onFilterChanged);

  useEffect(() => {
    filtersRef.current = initialFilters;
    onFilterChangedRef.current = onFilterChanged;
  }, [initialFilters, onFilterChanged]);

  useEffect(() => () => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
  }, []);

  const clearInputs = useCallback(() => {
    setKeywordInput("");
    setImportBatchInput("");
    setSearchDebouncing(false);
  }, []);

  const clearInputsRef = useRef(clearInputs);
  useEffect(() => {
    clearInputsRef.current = clearInputs;
  }, [clearInputs]);

  const updateFilter = useCallback((key: keyof QuestionListFilters, value: string) => {
    onFilterChangedRef.current(key, value);
  }, []);

  const clearFilterTimers = useCallback(() => {
    if (keywordTimer.current) clearTimeout(keywordTimer.current);
    keywordTimer.current = null;
    if (importBatchTimer.current) clearTimeout(importBatchTimer.current);
    importBatchTimer.current = null;
  }, []);

  const handleKeywordChange = useCallback((value: string) => {
    setKeywordInput(value);
    clearFilterTimers();
    const next = value.trim();
    if (next === filtersRef.current.keyword) {
      setSearchDebouncing(false);
      return;
    }
    setSearchDebouncing(true);
    keywordTimer.current = setTimeout(() => {
      updateFilter("keyword", next);
      keywordTimer.current = null;
      setSearchDebouncing(false);
    }, next === "" ? 100 : KEYWORD_DEBOUNCE_MS);
  }, [clearFilterTimers, updateFilter]);

  const handleImportBatchChange = useCallback((value: string) => {
    setImportBatchInput(value);
    clearFilterTimers();
    if (value.trim() === "") {
      updateFilter("import_batch_id", "");
      return;
    }
    importBatchTimer.current = setTimeout(() => {
      updateFilter("import_batch_id", value.trim());
      importBatchTimer.current = null;
    }, IMPORT_BATCH_DEBOUNCE_MS);
  }, [clearFilterTimers, updateFilter]);

  const handleResetFilters = useCallback(() => {
    clearFilterTimers();
    clearInputs();
    onFilterPresetApplied({ ...DEFAULT_QUESTION_FILTERS });
  }, [clearFilterTimers, clearInputs, onFilterPresetApplied]);

  useEffect(() => {
    if (!initialFilters.keyword && !initialFilters.import_batch_id) clearInputsRef.current();
  }, [initialFilters.import_batch_id, initialFilters.keyword]);

  const handlePageSizeChange = useCallback((value: string) => {
    onPageSizeChanged(Number(value) || 20);
  }, [onPageSizeChanged]);

  const applyFilterPreset = useCallback((patch: Partial<QuestionListFilters>) => {
    clearFilterTimers();
    const next: QuestionListFilters = { ...DEFAULT_QUESTION_FILTERS, ...patch };
    setKeywordInput(next.keyword);
    setSearchDebouncing(false);
    setImportBatchInput(next.import_batch_id);
    onFilterPresetApplied(next);
  }, [clearFilterTimers, onFilterPresetApplied]);

  const handleSaveCurrentFilters = useCallback((filters: QuestionListFilters) => {
    const result = saveCurrentFilters(getStorage, filters);
    onMessage(result.ok ? "当前筛选条件已保存到本机。 " : result.message);
  }, [getStorage, onMessage]);

  const handleApplySavedFilters = useCallback(() => {
    const result = loadSavedFilters(getStorage);
    if (result.ok) {
      applyFilterPreset(result.filters);
      return;
    }
    onMessage(result.message);
  }, [applyFilterPreset, getStorage, onMessage]);

  return {
    keywordInput,
    importBatchInput,
    searchDebouncing,
    updateFilter,
    handleKeywordChange,
    handleImportBatchChange,
    handleResetFilters,
    handlePageSizeChange,
    applyFilterPreset,
    handleSaveCurrentFilters,
    handleApplySavedFilters,
  };
}
