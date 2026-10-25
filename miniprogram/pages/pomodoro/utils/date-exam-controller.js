function createDateExamController(options) {
  return {
    dateText: () => dateText(options),
    examDays: () => examDays(options),
  }
}

function dateText(options) {
  const parts = options.getChinaWallParts(options.now())
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  return `${parts.month}月${parts.day}日 星期${weekdays[parts.weekday]}`
}

function examDays(options) {
  const parts = options.getChinaWallParts(options.now())
  const today = options.getChinaDayStartUtcMs(`${parts.year}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`)
  let examStart = examDayUtcMs(options, parts.year)
  if (examStart < today) examStart = examDayUtcMs(options, parts.year + 1)
  return Math.max(0, Math.round((examStart - today) / (24 * 60 * 60 * 1000)))
}

function examDayUtcMs(options, year) {
  const december31Ms = options.utc({ year, month: 11, day: 31 })
  const dayOfWeek = options.getUtcDay(december31Ms)
  const lastSaturday = 31 - ((dayOfWeek - 6 + 7) % 7)
  const targetDay = lastSaturday - 7
  return options.utc({ year, month: 11, day: targetDay }) - 8 * 60 * 60 * 1000
}

module.exports = { createDateExamController }
