function buildLoadViewState(options) {
  const {
    stats,
    summary,
    lifetime,
    trends,
    effectiveHistory,
    effectiveDate,
    authoritativeToday,
    willAnimate,
    displayDaySubjects,
  } = options

  const daySessions = (effectiveHistory && effectiveHistory.items) || []
  const subjectBreakdown = (summary && summary.subjects) || []
  const selectedDurationSec = Number(summary && summary.duration_sec) || 0
  const selectedSessionCount = Number(summary && summary.sessions) || 0
  const lifetimeStart = lifetime.start_date
    || options.currentLifetimeStartDate
    || effectiveDate
    || authoritativeToday

  const historyPatch = willAnimate
    ? { history: [], historyTotal: effectiveHistory.total || 0, historyReady: false }
    : {
        history: daySessions.map(options.formatSession),
        historyTotal: effectiveHistory.total || 0,
        historyReady: true,
      }
  const state = {
    daySessions,
    subjectBreakdown,
    selectedDurationSec,
    selectedSessionCount,
    hasBleedInSubjects: options.hasCrossDayBleedInSubjects(subjectBreakdown),
    lifetimeStart,
  }
  const dataPatch = {
    todaySessions: selectedSessionCount,
    todayDurationText: options.formatMin(selectedDurationSec),
    selectedDurationLabel: options.formatSelectedDurationLabel(effectiveDate),
    weekSessions: stats.week_sessions || 0,
    weekDurationText: options.formatMin(stats.week_duration_sec || 0),
    trends,
    trendHasData: options.hasDistributionData(trends),
    subjects: displayDaySubjects
      ? options.buildSubjectItems(subjectBreakdown)
      : options.currentSubjects,
    distributionHasData: displayDaySubjects
      ? options.hasDistributionData(subjectBreakdown)
      : options.currentDistributionHasData,
    pieDateLabel: options.formatPieDateLabel(effectiveDate),
    distributionRangeStart: displayDaySubjects ? effectiveDate : options.currentRangeStart,
    distributionRangeEnd: displayDaySubjects ? effectiveDate : options.currentRangeEnd,
    canGoNextDate: !!(effectiveDate && authoritativeToday && effectiveDate < authoritativeToday),
    _crossDayBleedIn: options.hasCrossDayBleedInSubjects(subjectBreakdown),
    pieLoading: false,
    loading: false,
    contentReady: true,
    errorText: '',
    _dispTodaySessions: willAnimate ? 0 : selectedSessionCount,
    ...options.getDurationDisplayPatch(willAnimate ? '0分钟' : options.formatMin(selectedDurationSec)),
    durationValueAnimating: willAnimate,
    _dispWeekSessions: willAnimate ? 0 : (stats.week_sessions || 0),
    _dispWeekDurationText: willAnimate ? '0分钟' : options.formatMin(stats.week_duration_sec || 0),
    ...options.buildCumulativePatch(lifetime, lifetimeStart),
    ...historyPatch,
  }
  return { ...state, historyPatch, dataPatch }
}

module.exports = {
  buildLoadViewState,
}
