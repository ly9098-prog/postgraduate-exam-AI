const { getChinaDate, getChinaDayStartUtcMs } = require('../../utils/china-time')

const DATE_PRESETS = [
  { value: '', label: '不限' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '近7天' },
  { value: 'month', label: '近30天' },
  { value: 'custom', label: '自定义' },
]

function isValidDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return false
  const start = getChinaDayStartUtcMs(value)
  return Number.isFinite(start) && getChinaDate(0, start) === value
}

function presetRange(preset, now) {
  const days = { today: 1, week: 7, month: 30 }[preset]
  return days ? { dateFrom: getChinaDate(1 - days, now), dateTo: getChinaDate(0, now) }
    : { dateFrom: '', dateTo: '' }
}

function validateRange(dateFrom, dateTo) {
  if (!isValidDate(dateFrom) || !isValidDate(dateTo)) return '请选择开始和结束日期'
  return dateFrom > dateTo ? '开始日期不能晚于结束日期' : ''
}

function rangeLabel(dateFrom, dateTo) {
  if (!dateFrom && !dateTo) return ''
  if (dateFrom === dateTo) return dateFrom.replace(/-/g, '.')
  return `${dateFrom.replace(/-/g, '.')} - ${dateTo.replace(/-/g, '.')}`
}

module.exports = { DATE_PRESETS, presetRange, validateRange, rangeLabel }
