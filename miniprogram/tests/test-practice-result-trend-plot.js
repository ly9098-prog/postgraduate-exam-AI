const assert = require('node:assert/strict')
const { test } = require('node:test')
const path = require('node:path')
const { buildTrendPlot } = require(process.env.STUDY_RESULT_BASELINE
  ? path.join(process.env.STUDY_RESULT_BASELINE, 'trend-plot-builder.js')
  : '../subpackages/study/practice-result/utils/trend-plot-builder')

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
  const result = buildTrendPlot([
    { date: '2024-01-01', accuracy: 150 },
    { date: '2024-01-02', accuracy: -20 },
  ])
  assert.equal(result.points[0].accuracy, 100)
  assert.equal(result.points[1].accuracy, 0)
})

test('buildTrendPlot: empty and single-point shapes retain distinct areaStyle contracts', () => {
  assert.deepEqual(buildTrendPlot({}), { points: [], segments: [], lastPoint: null })
  const result = buildTrendPlot([{ accuracy: 0 }])
  assert.deepEqual(Object.keys(result), ['points', 'segments', 'lastPoint', 'areaStyle'])
  assert.equal(result.lastPoint, result.points[0])
  assert.deepEqual(result.points[0], {
    key: 'day-0', accuracy: 0, leftPct: 50, topPct: 100, badgeTopPct: 100,
    dateLabel: '1', isLast: true,
  })
  assert.equal(result.areaStyle, '')
})

test('buildTrendPlot: horizontal geometry and polygon ordering stay exact', () => {
  const result = buildTrendPlot([{ date: '2024-03-01', accuracy: 80 }, { accuracy: '80' }])
  assert.deepEqual(result.segments, [{
    key: 'segment-0', leftPct: 0, topPct: 20, widthPct: 100, angleDeg: 0,
  }])
  assert.equal(result.areaStyle, 'clip-path: polygon(0% 100%, 0% 20%, 100% 20%, 100% 100%);')
  assert.equal(result.points[0].isLast, false)
  assert.equal(result.points[1].isLast, true)
  assert.equal(result.points[1].dateLabel, '2')
  assert.equal(result.lastPoint, result.points[1])
})

test('buildTrendPlot: vertical scaling uses the plot aspect before rounding', () => {
  const result = buildTrendPlot([
    { date: '2024-03-01', accuracy: 50 },
    { date: '2024-03-02', accuracy: 80 },
  ])
  assert.deepEqual(result.segments, [{
    key: 'segment-0', leftPct: 0, topPct: 50, widthPct: 100.566, angleDeg: -6.082,
  }])
})

test('buildTrendPlot: point evaluation keeps accuracy coercion before date and original references', () => {
  const reads = []
  const input = {
    get accuracy() {
      reads.push('accuracy')
      return { valueOf() { reads.push('valueOf'); return 75 } }
    },
    get date() { reads.push('date'); return '2024-03-01' },
  }
  const result = buildTrendPlot([input])
  assert.deepEqual(reads, ['accuracy', 'valueOf', 'date'])
  assert.equal(result.points[0].accuracy, 75)
  assert.notEqual(result.points[0], input)
  assert.equal(result.lastPoint, result.points[0])
})

test('buildTrendPlot: invalid accuracy retains NaN instead of inventing zero', () => {
  const result = buildTrendPlot([{ accuracy: 'invalid' }, null])
  assert.ok(Number.isNaN(result.points[0].accuracy))
  assert.ok(Number.isNaN(result.points[0].topPct))
  assert.ok(Number.isNaN(result.segments[0].widthPct))
  assert.equal(result.points[1].accuracy, 0)
  assert.equal(result.areaStyle, 'clip-path: polygon(0% 100%, 0% NaN%, 100% 100%, 100% 100%);')
})

test('buildTrendPlot: date getter failures keep identity and stop later point reads', () => {
  const failure = new Error('date sentinel')
  const first = { accuracy: 50, get date() { throw failure } }
  const later = { get accuracy() { throw Error('late accuracy') } }
  assert.throws(() => buildTrendPlot([first, later]), error => error === failure)
})

test('buildTrendPlot: sparse lists preserve the original segment construction failure', () => {
  assert.throws(() => buildTrendPlot([, { accuracy: 50 }]), TypeError)
})
