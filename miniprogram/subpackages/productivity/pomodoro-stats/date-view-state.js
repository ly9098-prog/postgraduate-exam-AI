function buildDateViewState(options) {
  const {
    summary,
    effectiveHistory,
    effectiveDate,
    todayDate,
    showDayDistribution,
  } = options

  const daySessions = (effectiveHistory && effectiveHistory.items) || []
  const subjectBreakdown = (summary && summary.subjects) || []
  const selectedDurationSec = Number(summary && summary.duration_sec) || 0
  const selectedSessionCount = Number(summary && summary.sessions) || 0
  const previousDurationSec = Number.isFinite(options.currentDisplayDurationSec)
    ? options.currentDisplayDurationSec
    : (Number(options.currentRawDurationSec) || 0)
  const previousSessionCount = Math.max(0, Number(options.currentDisplaySessions) || 0)

  const dataPatch = buildDateDataPatch(options, {
    showDayDistribution, subjectBreakdown, selectedDurationSec, selectedSessionCount,
    effectiveDate, todayDate, effectiveHistory, daySessions,
  })

  return {
    daySessions,
    subjectBreakdown,
    selectedDurationSec,
    selectedSessionCount,
    previousDurationSec,
    previousSessionCount,
    dataPatch,
  }
}

function buildDateDataPatch(options, ctx) {
  const { showDayDistribution, subjectBreakdown, selectedDurationSec, selectedSessionCount,
    effectiveDate, todayDate, effectiveHistory, daySessions } = ctx
  return {
    todaySessions: selectedSessionCount,
    subjects: showDayDistribution
      ? options.buildSubjectItems(subjectBreakdown)
      : options.currentSubjects,
    distributionHasData: showDayDistribution
      ? options.hasDistributionData(subjectBreakdown)
      : options.currentDistributionHasData,
    todayDurationText: options.formatMin(selectedDurationSec),
    selectedDurationLabel: options.formatSelectedDurationLabel(effectiveDate),
    history: daySessions.slice(0, 20).map(options.formatSession),
    historyTotal: (effectiveHistory && effectiveHistory.total) || 0,
    historyReady: true,
    pieDateLabel: options.formatPieDateLabel(effectiveDate),
    distributionRangeStart: showDayDistribution ? effectiveDate : options.currentRangeStart,
    distributionRangeEnd: showDayDistribution ? effectiveDate : options.currentRangeEnd,
    canGoNextDate: !!(effectiveDate && todayDate && effectiveDate < todayDate),
    _crossDayBleedIn: options.hasCrossDayBleedInSubjects(subjectBreakdown),
    pieLoading: false,
    selectedSubjectDetail: null,
    _selectedSubject: null,
  }
}

module.exports = {
  buildDateViewState,
}
