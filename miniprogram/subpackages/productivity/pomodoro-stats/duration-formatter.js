function formatDuration(sec) {
  var s = Math.max(0, sec || 0)
  var totalMin = Math.floor(s / 60)
  var hours = Math.floor(totalMin / 60)
  var mins = totalMin % 60
  if (hours > 0) return hours + '时' + mins + '分'
  return mins + '分钟'
}

function formatHourMinute(sec) {
  const s = Math.max(0, sec || 0)
  const m = Math.floor(s / 60)
  const h = Math.floor(m / 60)
  const mins = m % 60
  return `${h}时${mins}分`
}

function formatMin(sec) {
  const s = Math.max(0, sec || 0)
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}分钟`
  return `${Math.floor(m / 60)}时${m % 60}分`
}

function buildDurationSegments(text) {
  const normalized = String(text || '').trim() || '0分钟'
  const parts = []
  const regex = /(\d+)|(小时|分钟|时|分)/g
  let match = null
  while ((match = regex.exec(normalized))) {
    if (match[1]) parts.push({ type: 'num', text: match[1] })
    else if (match[2]) parts.push({ type: 'unit', text: match[2] })
  }
  if (!parts.length) return [{ type: 'num', text: normalized }]
  return parts
}

module.exports = {
  formatDuration,
  formatHourMinute,
  formatMin,
  buildDurationSegments,
}
