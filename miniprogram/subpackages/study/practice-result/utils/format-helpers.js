/**
 * Pure format helpers for practice result page,
 * extracted from practice-result/index.js.
 */

var ERROR_COLORS = ['#7ED8B5', '#55C89B', '#3DA880', '#2F8066', '#8BCDB8', '#B7EBD9']

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

/**
 * Normalize a percentage value: 0-1 floats are scaled to 0-100,
 * other numbers are clamped to 0-100.
 */
function normalizePercent(value) {
  var n = Number(value)
  if (!Number.isFinite(n)) return 0
  if (n >= 0 && n <= 1) return Math.round(n * 100)
  return Math.round(clamp(n, 0, 100))
}

/**
 * Compute question list height in rpx.
 */
function getQuestionListHeightRpx(count) {
  var total = Math.max(0, Number(count) || 0)
  return total > 0 ? total * 86 : 96
}

/**
 * Format duration in seconds as HH:MM:SS or MM分SS秒.
 */
function formatDuration(seconds) {
  var total = Math.max(0, Math.round(Number(seconds) || 0))
  var h = Math.floor(total / 3600)
  var m = Math.floor((total % 3600) / 60)
  var s = total % 60
  if (h > 0) return pad2(h) + ':' + pad2(m) + ':' + pad2(s)
  return pad2(m) + '分' + pad2(s) + '秒'
}

/**
 * Build a conic-gradient CSS string for an error distribution donut chart.
 */
function buildErrorDonutGradient(distribution) {
  var list = Array.isArray(distribution)
    ? distribution.filter(function(item) { return Number(item && item.count) > 0 })
    : []
  var total = list.reduce(function(sum, item) { return sum + Number(item.count || 0) }, 0)
  if (!total) return '#EEF2EF'
  var cursor = 0
  var stops = []
  list.forEach(function(item, index) {
    var ratio = Number(item.count || 0) / total * 100
    var start = cursor
    var end = index === list.length - 1 ? 100 : cursor + ratio
    stops.push((item.color || ERROR_COLORS[index % ERROR_COLORS.length]) + ' ' + start.toFixed(3) + '% ' + end.toFixed(3) + '%')
    cursor = end
  })
  return 'conic-gradient(' + stops.join(', ') + ')'
}

module.exports = {
  normalizePercent,
  getQuestionListHeightRpx,
  formatDuration,
  buildErrorDonutGradient,
  ERROR_COLORS,
}
