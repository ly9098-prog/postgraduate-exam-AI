/**
 * Formats the human-readable study-day range label for a given day-start
 * minute.  Pure: the caller supplies the minute-to-time formatter.
 */
function formatStudyDayRangeText(dsm, minuteToTimeText) {
  const minute = Math.max(0, Math.min(1439, Number(dsm) || 0))
  if (!minute) return '统计日从 00:00 开始'
  const t = minuteToTimeText(minute)
  return '统计周期 ' + t + ' - 次日 ' + t
}

module.exports = {
  formatStudyDayRangeText,
}
