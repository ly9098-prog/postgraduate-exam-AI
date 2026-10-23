const { parseDateStr } = require('./date-utils')

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3)
}

function easeInOutCubic(t) {
  return t < 0.5
    ? 4 * t * t * t
    : 1 - Math.pow(-2 * t + 2, 3) / 2
}

function formatPieDateLabel(value, todayDate) {
  if (!value) return '今日'
  if (value === todayDate) return '今日'
  const today = parseDateStr(todayDate)
  const target = parseDateStr(value)
  if (today && target) {
    // Use UTC calendar days to avoid device timezone drift.
    const diffDays = Math.round(
      (Date.UTC(today[0], today[1] - 1, today[2]) - Date.UTC(target[0], target[1] - 1, target[2])) / 86400000
    )
    if (diffDays === 1) return '昨日'
    return `${target[1]}月${target[2]}日`
  }
  return value
}

function formatSelectedDurationLabel(value, todayDate) {
  const dateLabel = formatPieDateLabel(value, todayDate)
  return dateLabel === '今日' ? '今日学习' : `${dateLabel}学习`
}

function hasDistributionData(subjects) {
  return Array.isArray(subjects) && subjects.some(item => Number(item && item.duration_sec) > 0)
}

function shadeColor(hex, amount) {
  const safeHex = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : '#3B82F6'
  const num = parseInt(safeHex.slice(1), 16)
  const clamp = value => Math.max(0, Math.min(255, value))
  const r = clamp((num >> 16) + amount)
  const g = clamp(((num >> 8) & 0xff) + amount)
  const b = clamp((num & 0xff) + amount)
  return `rgb(${r}, ${g}, ${b})`
}

module.exports = {
  easeOutCubic,
  easeInOutCubic,
  formatPieDateLabel,
  formatSelectedDurationLabel,
  hasDistributionData,
  shadeColor,
}
