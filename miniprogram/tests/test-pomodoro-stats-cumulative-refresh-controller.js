const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createCumulativeRefreshController,
} = require('../subpackages/productivity/pomodoro-stats/cumulative-refresh-controller')

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    todayDate: '2024-06-01',
    cumulativeStartDate: '2024-01-01',
    requestSeq: 0,
    dataPatches: [],
    summaries: [],
    errors: [],
    toasts: [],
  }
  const options = {
    isAlive: () => state.alive,
    getTodayDate: () => state.todayDate,
    getCumulativeStartDate: () => state.cumulativeStartDate,
    getRequestSeq: () => state.requestSeq,
    setRequestSeq: value => { state.requestSeq = value },
    getRangeSummary: async (start, end) => ({ start_date: start, end_date: end, sessions: 5 }),
    buildSummaryPatch: (summary, start) => ({ cumulativeStartDate: start, cumulativeSessions: summary.sessions }),
    setData: patch => state.dataPatches.push(patch),
    showToast: title => state.toasts.push(title),
    logError: (message, e) => state.errors.push({ message, e }),
    ...overrides,
  }
  return { controller: createCumulativeRefreshController(options), state, options }
}

test('fetches and writes the summary patch', async () => {
  const h = createHarness()
  await h.controller.refresh('2024-01-01', false)

  assert.equal(h.state.requestSeq, 1)
  assert.deepEqual(h.state.dataPatches[0], { cumulativeLoading: true })
  assert.deepEqual(h.state.dataPatches[1], { cumulativeStartDate: '2024-01-01', cumulativeSessions: 5 })
  assert.equal(h.state.toasts.length, 0)
})

test('skips the loading patch when silent', async () => {
  const h = createHarness()
  await h.controller.refresh('2024-01-01', true)
  assert.equal(h.state.dataPatches.some(p => p.cumulativeLoading), false)
})

test('ignores an empty start or missing today', async () => {
  const h = createHarness()
  await h.controller.refresh('', false)
  assert.deepEqual(h.state.dataPatches, [])

  const noToday = createHarness()
  noToday.state.todayDate = ''
  await noToday.controller.refresh('2024-01-01', false)
  assert.deepEqual(noToday.state.dataPatches, [])
})

test('discards a stale response when a newer request supersedes it', async () => {
  const h = createHarness()
  let resolveFirst
  h.options.getRangeSummary = () => new Promise(resolve => { resolveFirst = resolve })
  const first = h.controller.refresh('2024-01-01', false)
  // Simulate a second request bumping the seq before the first resolves.
  h.state.requestSeq = 99
  resolveFirst({ sessions: 5 })
  await first
  assert.equal(h.state.dataPatches.some(p => p.cumulativeSessions === 5), false)
})

test('discards a response when the cumulative start date changed', async () => {
  const h = createHarness()
  await h.controller.refresh('2024-01-01', false)
  // Reset and run again but change the start mid-flight.
  let resolveSecond
  h.options.getRangeSummary = () => new Promise(resolve => { resolveSecond = resolve })
  const second = h.controller.refresh('2024-02-01', false)
  h.state.cumulativeStartDate = '2024-01-01'
  resolveSecond({ sessions: 10 })
  await second
  assert.equal(h.state.dataPatches.some(p => p.cumulativeSessions === 10), false)
})

test('shows an error toast and clears loading on failure', async () => {
  const h = createHarness({ getRangeSummary: async () => { throw new Error('network') } })
  await h.controller.refresh('2024-01-01', false)

  assert.equal(h.state.toasts[0], '累计统计加载失败')
  assert.ok(h.state.dataPatches.some(p => p.cumulativeLoading === false))
  assert.equal(h.state.errors.length, 1)
})

test('suppresses the toast in silent mode on failure', async () => {
  const h = createHarness({ getRangeSummary: async () => { throw new Error('network') } })
  await h.controller.refresh('2024-01-01', true)
  assert.equal(h.state.toasts.length, 0)
  assert.ok(h.state.dataPatches.some(p => p.cumulativeLoading === false))
})

test('skips error handling when the page is dead', async () => {
  const h = createHarness({ getRangeSummary: async () => { throw new Error('network') } })
  const promise = h.controller.refresh('2024-01-01', false)
  h.state.alive = false
  await promise
  assert.equal(h.state.errors.length, 0)
  assert.equal(h.state.toasts.length, 0)
})
