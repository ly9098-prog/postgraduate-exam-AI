const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStatsController,
} = require('../pages/pomodoro/utils/stats-controller')

function createHarness(overrides = {}) {
  const calls = { paths: [], durationSec: [], setData: [] }
  const pending = []
  const options = {
    get(path) {
      calls.paths.push(path)
      if (overrides.get) return overrides.get(path, pending)
      return Promise.resolve(overrides.stats === undefined ? {} : overrides.stats)
    },
    setTodayDurationSec(value) {
      calls.durationSec.push(value)
    },
    setData(data) {
      calls.setData.push(data)
    },
  }
  return { controller: createStatsController(options), calls, pending }
}

test('load requests today stats and writes minute-formatted totals', async () => {
  const harness = createHarness({ stats: { today_sessions: 3, today_duration_sec: 1500 } })

  await harness.controller.load()

  assert.deepEqual(harness.calls.paths, ['/pomodoro/stats'])
  assert.deepEqual(harness.calls.durationSec, [1500])
  assert.deepEqual(harness.calls.setData, [{ todaySessions: 3, todayDurationText: '25分钟' }])
})

test('load formats hour-long totals and defaults missing fields to zero', async () => {
  const long = createHarness({ stats: { today_sessions: 5, today_duration_sec: 3900 } })
  await long.controller.load()
  assert.deepEqual(long.calls.setData, [{ todaySessions: 5, todayDurationText: '1时5分' }])

  const empty = createHarness({ stats: {} })
  await empty.controller.load()
  assert.deepEqual(empty.calls.durationSec, [0])
  assert.deepEqual(empty.calls.setData, [{ todaySessions: 0, todayDurationText: '0分钟' }])
})

test('slower older responses cannot overwrite newer totals', async () => {
  const harness = createHarness({ get: () => new Promise(resolve => harness.pending.push(resolve)) })

  const first = harness.controller.load()
  const second = harness.controller.load()
  harness.pending[1]({ today_sessions: 8, today_duration_sec: 3600 })
  await second
  harness.pending[0]({ today_sessions: 7, today_duration_sec: 3000 })
  await first

  assert.deepEqual(harness.calls.setData, [{ todaySessions: 8, todayDurationText: '1时0分' }])
})

test('invalidate discards an in-flight response', async () => {
  const harness = createHarness({ get: () => new Promise(resolve => harness.pending.push(resolve)) })

  const inflight = harness.controller.load()
  harness.controller.invalidate()
  harness.pending[0]({ today_sessions: 9, today_duration_sec: 1200 })
  await inflight

  assert.deepEqual(harness.calls.setData, [])
  assert.deepEqual(harness.calls.durationSec, [])
})

test('a rejected request is swallowed without writing the view', async () => {
  const harness = createHarness({ get: () => Promise.reject(new Error('offline')) })

  await harness.controller.load()

  assert.deepEqual(harness.calls.setData, [])
  assert.deepEqual(harness.calls.durationSec, [])
})
