/**
 * Pure helpers for practice result display, extracted from practice-result/index.js.
 */

var ERROR_COLORS = ['#7ED8B5', '#55C89B', '#3DA880', '#2F8066', '#8BCDB8', '#B7EBD9']

/**
 * Build a local error distribution from wrong items, grouped by knowledge point.
 * Top 4 groups are shown; the rest are merged into "其他".
 */
function buildLocalErrorDistribution(wrongItems) {
  if (!wrongItems || !wrongItems.length) return []
  var map = {}
  wrongItems.forEach(function(item) {
    var label = item.knowledgePoint || '其他'
    map[label] = (map[label] || 0) + 1
  })
  var sorted = Object.keys(map)
    .map(function(label) { return { label: label, count: map[label] } })
    .sort(function(a, b) { return b.count - a.count })
  var display = sorted.slice(0, 4)
  if (sorted.length > 4) {
    var rest = sorted.slice(4).reduce(function(sum, item) { return sum + item.count }, 0)
    display.push({ label: '其他', count: rest })
  }
  var total = display.reduce(function(sum, item) { return sum + item.count }, 0)
  return display.map(function(item, index) {
    return {
      label: item.label,
      count: item.count,
      percent: total ? Math.round(item.count / total * 100) : 0,
      color: ERROR_COLORS[index % ERROR_COLORS.length],
    }
  })
}

/**
 * Get a result tip message based on accuracy and error counts.
 */
function getResultTip(accuracy, wrongCount, skippedCount, partialCount, totalCount) {
  if (wrongCount === 0 && skippedCount === 0 && partialCount === 0 && Number(totalCount) > 0) {
    return '本组表现稳定，可以继续挑战更高难度。'
  }
  if (wrongCount === 0 && (skippedCount > 0 || partialCount > 0)) {
    var parts = []
    if (partialCount > 0) parts.push(partialCount + ' 题未完成')
    if (skippedCount > 0) parts.push(skippedCount + ' 题跳过')
    return '本组有 ' + parts.join('、') + '，建议补看答案与解析后再继续。'
  }
  if (accuracy >= 80) return '整体掌握较好，建议快速复盘错题后继续练习。'
  if (accuracy >= 60) return '基础已掌握，优先复盘错题对应知识点。'
  return '本组错题较多，建议先定位错误原因，再进行同类题巩固。'
}

module.exports = {
  buildLocalErrorDistribution,
  getResultTip,
  ERROR_COLORS,
}
