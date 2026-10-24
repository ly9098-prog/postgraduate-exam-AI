/**
 * Pure helper for building trend plot data,
 * extracted from practice-result/index.js.
 */

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

/**
 * Build trend plot points, segments, and area polygon from daily accuracy data.
 */
function buildTrendPlot(data) {
  var list = Array.isArray(data) ? data : []
  if (!list.length) return { points: [], segments: [], lastPoint: null }

  var plotWidthRpx = 580
  var plotHeightRpx = 206
  var aspect = plotHeightRpx / plotWidthRpx
  var denominator = Math.max(1, list.length - 1)

  var points = list.map(function(item, index) {
    var accuracy = clamp(item && item.accuracy, 0, 100)
    var leftPct = list.length === 1 ? 50 : (index / denominator) * 100
    var topPct = 100 - accuracy
    var rawDate = String((item && item.date) || '')
    var dateLabel = rawDate.slice(5).replace('-', '/') || String(index + 1)
    return {
      key: (rawDate || 'day') + '-' + index,
      accuracy: accuracy,
      leftPct: Number(leftPct.toFixed(3)),
      topPct: Number(topPct.toFixed(3)),
      badgeTopPct: Number(Math.max(0, topPct).toFixed(3)),
      dateLabel: dateLabel,
      isLast: index === list.length - 1
    }
  })

  var segments = []
  for (var index = 0; index < points.length - 1; index += 1) {
    var from = points[index]
    var to = points[index + 1]
    var dxPct = to.leftPct - from.leftPct
    var dyPct = to.topPct - from.topPct
    var scaledDy = dyPct * aspect
    var widthPct = Math.sqrt(dxPct * dxPct + scaledDy * scaledDy)
    var angleDeg = Math.atan2(scaledDy, dxPct) * 180 / Math.PI
    segments.push({
      key: 'segment-' + index,
      leftPct: from.leftPct,
      topPct: from.topPct,
      widthPct: Number(widthPct.toFixed(3)),
      angleDeg: Number(angleDeg.toFixed(3))
    })
  }

  var areaPolygon = points.length > 1
    ? ['0% 100%'].concat(points.map(function(point) { return point.leftPct + '% ' + point.topPct + '%' }), ['100% 100%'])
    : []

  return {
    points: points,
    segments: segments,
    lastPoint: points[points.length - 1] || null,
    areaStyle: areaPolygon.length ? 'clip-path: polygon(' + areaPolygon.join(', ') + ');' : ''
  }
}

module.exports = { buildTrendPlot }
