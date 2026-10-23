function parseDateStr(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''))
  if (!m) return null
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

function formatDateParts(parts) {
  if (!parts) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${parts[0]}-${pad(parts[1])}-${pad(parts[2])}`
}

function shiftDate(value, deltaDays) {
  const parts = parseDateStr(value)
  if (!parts) return value || ''
  const utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + Number(deltaDays || 0)))
  return formatDateParts([utc.getUTCFullYear(), utc.getUTCMonth() + 1, utc.getUTCDate()])
}

function startOfWeek(value) {
  const parts = parseDateStr(value)
  if (!parts) return value || ''
  const utc = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]))
  const weekday = utc.getUTCDay()
  const offset = weekday === 0 ? -6 : 1 - weekday
  return shiftDate(value, offset)
}

function monthStart(value) {
  const parts = parseDateStr(value)
  return parts ? formatDateParts([parts[0], parts[1], 1]) : (value || '')
}

function monthEnd(value) {
  const parts = parseDateStr(value)
  if (!parts) return value || ''
  const utc = new Date(Date.UTC(parts[0], parts[1], 0))
  return formatDateParts([utc.getUTCFullYear(), utc.getUTCMonth() + 1, utc.getUTCDate()])
}

function minDate(a, b) {
  if (!a) return b || ''
  if (!b) return a || ''
  return a <= b ? a : b
}

function resolveDistributionRange(period, anchorDate, context) {
  const anchor = anchorDate || (context && context.selectedDate) || (context && context.todayDate)
  const today = (context && context.todayDate) || anchor
  if (period === 'week') {
    const start = startOfWeek(anchor)
    return { start, end: minDate(shiftDate(start, 6), today) }
  }
  if (period === 'month') {
    return { start: monthStart(anchor), end: minDate(monthEnd(anchor), today) }
  }
  if (period === 'custom') {
    let start = (context && context.customRangeStartDate) || anchor
    if (start > anchor) start = anchor
    return { start, end: anchor }
  }
  return { start: anchor, end: anchor }
}

module.exports = {
  parseDateStr,
  formatDateParts,
  shiftDate,
  startOfWeek,
  monthStart,
  monthEnd,
  minDate,
  resolveDistributionRange,
}
