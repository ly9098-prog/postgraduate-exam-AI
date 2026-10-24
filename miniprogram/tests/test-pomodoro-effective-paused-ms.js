const { test } = require('node:test')
const assert = require('node:assert')

const { buildEffectivePausedMs } = require('../pages/pomodoro/utils/effective-paused-ms')

test('effective paused ms: base only when not actively paused', () => {
  const session = { id: 1, total_paused_sec: 30, paused_at: null }
  const result = buildEffectivePausedMs(session, {
    parseServerTime: () => 0,
    now: () => 1000,
    mergeLocalAdjustment: (_id, ms) => ms,
  })
  assert.strictEqual(result, 30000)
})

test('effective paused ms: adds active pause duration', () => {
  const session = { id: 1, total_paused_sec: 10, paused_at: '2024-01-01T00:00:00Z' }
  const result = buildEffectivePausedMs(session, {
    parseServerTime: () => 5000,
    now: () => 8000,
    mergeLocalAdjustment: (_id, ms) => ms,
  })
  // 10*1000 +%1000-500" 10000 + 3000 = 13000
  assert.strictEqual(result, 13000)
})

test('effective paused ms: clamps negative active pause to zero', () => {
  const session = { id: 1, total_paused_sec: 5, paused_at: '2024-01-01T00:00:00Z' }
  const result = buildEffectivePausedMs(session, {
    parseServerTime: () => 10000,
    now: () => 5000,
    mergeLocalAdjustment: (_id, ms) => ms,
  })
  // now < pausedAt → max(0, -5000) = 0 → 5000
  assert.strictEqual(result, 5000)
})

test('effective paused ms: delegates to mergeLocalAdjustment', () => {
  const session = { id: 42, total_paused_sec: 0, paused_at: null }
  let capturedId = null
  let capturedMs = null
  buildEffectivePausedMs(session, {
    parseServerTime: () => 0,
    now: () => 0,
    mergeLocalAdjustment: (id, ms) => { capturedId = id; capturedMs = ms; return 999 },
  })
  assert.strictEqual(capturedId, 42)
  assert.strictEqual(capturedMs, 0)
})

test('effective paused ms: handles missing total_paused_sec', () => {
  const session = { id: 1, paused_at: null }
  const result = buildEffectivePausedMs(session, {
    parseServerTime: () => 0,
    now: () => 0,
    mergeLocalAdjustment: (_id, ms) => ms,
  })
  assert.strictEqual(result, 0)
})
