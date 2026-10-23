const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createDistributionLoadController,
} = require('../subpackages/productivity/pomodoro-stats/distribution-load-controller')

async function flushMicrotasks() {
  for (let i = 0; i < 10; i++) await Promise.resolve()
}

function createHarness(overrides = {}) {
  const state = {
    alive: true,
    selectedDate: '2024-06-01',
    daySubjectsRaw: [{ subject: 1, duration_sec: 60 }],
    distributionPeriod: 'day',
    distributionRangeStart: '',
    distributionRangeEnd: '',
    requestSeq: 0,
    dataPatches: [],
    commits: [],
    errors: [],
    toasts: [],
    rangeSummary: { subjects: [{ subject: 2, duration_sec: 30 }] },
  }
  const options = {
    isAlive: () => state.alive,
    getSelectedDate: () => state.selectedDate,
    getDaySubjectsRaw: () => state.daySubjectsRaw,
    getDistributionPeriod: () => state.distributionPeriod,
    getDistributionRangeStart: () => state.distributionRangeStart,
    getDistributionRangeEnd: () => state.distributionRangeEnd,
    getRequestSeq: () => state.requestSeq,
    setRequestSeq: value => { state.requestSeq = value },
    resolveDistributionRange: (period, anchor) => {
      if (period === 'day') return { start: anchor, end: anchor }
      return { start: '2024-01-01', end: '2024-06-01' }
    },
    ensureSubjectMeta: async () => {},
    getRangeSummary: async () => state.rangeSummary,
    commitDistributionSubjects: (subjects, animate) => state.commits.push({ subjects, animate }),
    setData: patch => {
      state.dataPatches.push(patch)
      if (patch.distributionPeriod) state.distributionPeriod = patch.distributionPeriod
      if (patch.distributionRangeStart) state.distributionRangeStart = patch.distributionRangeStart
      if (patch.distributionRangeEnd) state.distributionRangeEnd = patch.distributionRangeEnd
    },
    showToast: title => state.toasts.push(title),
    logError: (message, e) => state.errors.push({ message, e }),
    ...overrides,
  }
  return { controller: createDistributionLoadController(options), state, options }
}

test('commits day subjects immediately without a network request', async () => {
  const h = createHarness()
  await h.controller.load('day', true)

  assert.deepEqual(h.state.dataPatches[0], {
    distributionPeriod: 'day',
    distributionRangeStart: '2024-06-01',
    distributionRangeEnd: '2024-06-01',
  })
  assert.deepEqual(h.state.commits, [{ subjects: h.state.daySubjectsRaw, animate: true }])
  assert.equal(h.state.requestSeq, 0)
})

test('fetches and commits range subjects for non-day periods', async () => {
  const h = createHarness()
  await h.controller.load('week', true)

  assert.equal(h.state.requestSeq, 1)
  assert.ok(h.state.dataPatches[0].pieLoading)
  assert.deepEqual(h.state.commits, [{ subjects: h.state.rangeSummary.subjects, animate: true }])
})

test('normalizes an unknown period to day', async () => {
  const h = createHarness()
  await h.controller.load('bogus', true)
  assert.deepEqual(h.state.commits, [{ subjects: h.state.daySubjectsRaw, animate: true }])
})

test('discards a stale response when a newer request supersedes it', async () => {
  const h = createHarness()
  let resolveFirst
  h.options.getRangeSummary = () => new Promise(resolve => { resolveFirst = resolve })
  const first = h.controller.load('week', true)
  await flushMicrotasks()
  h.state.requestSeq = 99
  resolveFirst({ subjects: [] })
  await first
  assert.equal(h.state.commits.length, 0)
})

test('discards a response when the distribution period or range changed', async () => {
  const h = createHarness()
  let resolveFirst
  h.options.getRangeSummary = () => new Promise(resolve => { resolveFirst = resolve })
  const first = h.controller.load('week', true)
  await flushMicrotasks()
  h.state.distributionPeriod = 'month'
  resolveFirst({ subjects: [] })
  await first
  assert.equal(h.state.commits.length, 0)
})

test('shows an error toast and clears loading on failure', async () => {
  const h = createHarness({ getRangeSummary: async () => { throw new Error('network') } })
  await h.controller.load('week', true)

  assert.equal(h.state.toasts[0], '分布统计加载失败')
  assert.ok(h.state.dataPatches.some(p => p.pieLoading === false))
  assert.equal(h.state.errors.length, 1)
})

test('skips error handling when the page is dead', async () => {
  const h = createHarness({ getRangeSummary: async () => { throw new Error('network') } })
  const promise = h.controller.load('week', true)
  h.state.alive = false
  await promise
  assert.equal(h.state.errors.length, 0)
  assert.equal(h.state.toasts.length, 0)
})

test('skips an invalid range', async () => {
  const h = createHarness({
    resolveDistributionRange: () => ({ start: '', end: '' }),
  })
  await h.controller.load('week', true)
  assert.deepEqual(h.state.dataPatches, [])
  assert.deepEqual(h.state.commits, [])
})
