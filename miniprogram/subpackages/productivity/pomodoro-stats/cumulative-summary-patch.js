/**
 * Builds the view patch for a cumulative-focus summary.  All inputs are
 * explicit so the module never touches Page state.
 */
function buildCumulativeSummaryPatch(summary, requestedStart, todayDate, formatMin) {
  const data = summary || {}
  const startDate = requestedStart || data.start_date || todayDate || ''
  const sessions = Math.max(0, Number(data.sessions) || 0)
  const durationSec = Math.max(0, Number(data.duration_sec) || 0)
  const activeDays = Math.max(0, Number(data.active_days) || 0)
  const averageSec = activeDays > 0 ? Math.floor(durationSec / activeDays) : 0
  return {
    cumulativeStartDate: startDate,
    cumulativeSessions: sessions,
    cumulativeDurationText: formatMin(durationSec),
    cumulativeAverageText: formatMin(averageSec),
    cumulativeActiveDays: activeDays,
    cumulativeLoading: false,
  }
}

module.exports = {
  buildCumulativeSummaryPatch,
}
