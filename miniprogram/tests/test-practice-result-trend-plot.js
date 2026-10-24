const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildTrendPlot } = require('../subpackages/study/practice-result/utils/trend-plot-builder')

test('buildTrendPlot: returns empty for empty data', () => {
  const result = buildTrendPlot([])
  assert.deepEqual(result.points, [])
  assert.equal(result.lastPoint, null)
})

test('buildTrendPlot: returns empty for null', () => {
  const result = buildTrendPlot(null)
  assert.deepEqual(result.points, [])
})

test('buildTrendPlot: builds points for single data point', () => {
  const result = buildTrendPlot([{ date: '2024-01-01', accuracy: 80 }])
  assert.equal(result.points.length, 1)
  assert.equal(result.points[0].accuracy, 80)
  assert.equal(result.points[0].leftPct, 50)
  assert.equal(result.points[0].isLast, true)
  assert.equal(result.lastPoint.accuracy, 80)
})

test('buildTrendPlot: builds segments for multiple points', () => {
  const result = buildTrendPlot([
    { date: '2024-01-01', accuracy: 60 },
    { date: '2024-01-02', accuracy: 80 },
  ])
  assert.equal(result.points.length, 2)
  assert.equal(result.segments.length, 1)
  assert.equal(result.segments[0].key, 'segment-0')
})

test('buildTrendPlot: computes topPct from accuracy', () => {
  const result = buildTrendPlot([{ date: '2024-01-01', accuracy: 75 }])
  assert.equal(result.points[0].topPct, 25)
})

test('buildTrendPlot: builds area polygon for multiple points', () => {
  const result = buildTrendPlot([
    { date: '2024-01-01', accuracy: 50 },
    { date: '2024-01-02', accuracy: 80 },
  ])
  assert.ok(result.areaStyle)
  assert.ok(result.areaStyle.includes('clip-path: polygon'))
})

test('buildTrendPlot: no areaStyle for single point', () => {
  const result = buildTrendPlot([{ date: '2024-01-01', accuracy: 50 }])
  assert.equal(result.areaStyle, '')
})

test('buildTrendPlot: extracts date label', () => {
  const result = buildTrendPlot([{ date: '2024-03-15', accuracy: 50 }])
  assert.equal(result.points[0].dateLabel, '03/15')
})

test('buildTrendPlot: clamps accuracy to 0-100', () => {
  const result = buildTrendPlot([{ date: '2024-01-01', accuracy: 150 }])
  assert.equal(result.points[0].accuracy, 100)
})
