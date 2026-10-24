const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamPendingCacheController,
} = require('../subpackages/exam/utils/exam-pending-cache-controller')

const DRAFT_TTL_MS = 60 * 60 * 1000
const SUBMIT_PENDING_TTL_MS = 7 * 24 * 60 * 60 * 1000

function harness(overrides = {}) {
  const state = {
    now: 2_000_000_000,
    storage: new Map(),
    retainPendingForSubmit: null,
    clearedAttemptIds: [],
  }
  const keys = {
    v3: attemptId => `exam_attempt_pending_v3:${attemptId}`,
    v2: attemptId => `exam_attempt_pending_v2:${attemptId}`,
    v1: attemptId => `exam_attempt_pending_v1:${attemptId}`,
  }

  function removeAllGenerations(attemptId) {
    Object.values(keys).forEach(buildKey => state.storage.delete(buildKey(attemptId)))
  }

  const options = {
    readStorage: key => (state.storage.has(key) ? state.storage.get(key) : ''),
    writeStorage: (key, value) => { state.storage.set(key, value) },
    removeStorage: key => { state.storage.delete(key) },
    cacheKey: keys.v3,
    v2CacheKey: keys.v2,
    legacyCacheKey: keys.v1,
    clearPendingAttempt: attemptId => {
      state.clearedAttemptIds.push(attemptId)
      removeAllGenerations(attemptId)
    },
    now: () => state.now,
    sanitizePendingItems: raw => {
      const source = raw && typeof raw === 'object' ? raw : {}
      const result = Object.create(null)
      Object.keys(source).forEach((key) => {
        if (!/^\d+$/.test(key) || !source[key] || typeof source[key] !== 'object') return
        result[key] = Object.assign({}, source[key])
      })
      return result
    },
    isPendingItemKey: value => /^\d+$/.test(String(value || '')),
    getSchemaVersion: () => 3,
    getDraftTtlMs: () => DRAFT_TTL_MS,
    getSubmitPendingTtlMs: () => SUBMIT_PENDING_TTL_MS,
    setRetainPendingForSubmit: value => { state.retainPendingForSubmit = value },
    ...overrides,
  }

  return {
    state,
    keys,
    get controller() { return createExamPendingCacheController(options) },
  }
}

test('loads a valid v3 cache and propagates submit-pending state', () => {
  const h = harness()
  const items = { 101: { selected_answer: 'A', marked_for_review: true, used_time: 12 } }
  h.state.storage.set(h.keys.v3(12), {
    schema_version: 3,
    saved_at: h.state.now - 1_000,
    submit_pending: true,
    items,
  })

  const loaded = h.controller.load(12)

  assert.deepEqual(loaded, Object.assign(Object.create(null), items))
  assert.equal(Object.getPrototypeOf(loaded), null)
  assert.equal(h.state.retainPendingForSubmit, true)
  assert.equal(h.state.storage.get(h.keys.v3(12)).schema_version, 3)
})

test('migrates v2 metadata-shaped caches using only numeric item keys', () => {
  const h = harness()
  h.state.storage.set(h.keys.v2(12), {
    schema_version: 2,
    saved_at: h.state.now - 1_000,
    items: {
      101: { selected_answer: 'A' },
      saved_at: 123,
      schema_version: 2,
    },
  })

  const loaded = h.controller.load(12)
  const migrated = h.state.storage.get(h.keys.v3(12))

  assert.deepEqual(Object.keys(loaded), ['101'])
  assert.equal(h.state.retainPendingForSubmit, false)
  assert.equal(migrated.schema_version, 3)
  assert.equal(migrated.saved_at, h.state.now - 1_000)
  assert.equal(migrated.submit_pending, false)
  assert.deepEqual(Object.keys(migrated.items), ['101'])
  assert.equal(h.state.storage.has(h.keys.v2(12)), false)
  assert.equal(h.state.storage.has(h.keys.v1(12)), false)
})

test('falls back to the v1 item map and migrates it to v3', () => {
  const h = harness()
  h.state.storage.set(h.keys.v1(12), {
    101: { selected_answer: 'B' },
    saved_at: h.state.now - 1_000,
  })

  const loaded = h.controller.load(12)
  const migrated = h.state.storage.get(h.keys.v3(12))

  assert.deepEqual(loaded, Object.assign(Object.create(null), { 101: { selected_answer: 'B' } }))
  assert.equal(migrated.schema_version, 3)
  assert.deepEqual(Object.keys(migrated.items), ['101'])
  assert.equal(h.state.storage.has(h.keys.v1(12)), false)
})

test('returns an empty null-prototype map for invalid caches', () => {
  const h = harness()
  h.state.storage.set(h.keys.v3(12), 'invalid')
  h.state.storage.set(h.keys.v2(12), 0)
  h.state.storage.set(h.keys.v1(12), null)

  const loaded = h.controller.load(12)

  assert.deepEqual(loaded, Object.create(null))
  assert.equal(Object.getPrototypeOf(loaded), null)
  assert.equal(h.state.retainPendingForSubmit, null)
  assert.equal(h.state.storage.has(h.keys.v3(12)), true)
})

test('expired drafts clear every compatible generation', () => {
  const h = harness()
  const expiredAt = h.state.now - DRAFT_TTL_MS - 1
  h.state.storage.set(h.keys.v3(12), {
    schema_version: 3,
    saved_at: expiredAt,
    submit_pending: false,
    items: { 101: { selected_answer: 'A' } },
  })
  h.state.storage.set(h.keys.v2(12), { 102: { selected_answer: 'B' } })
  h.state.storage.set(h.keys.v1(12), { 103: { selected_answer: 'C' } })

  const loaded = h.controller.load(12)

  assert.deepEqual(loaded, Object.create(null))
  assert.deepEqual(h.state.clearedAttemptIds, [12])
  assert.equal(h.state.storage.has(h.keys.v3(12)), false)
  assert.equal(h.state.storage.has(h.keys.v2(12)), false)
  assert.equal(h.state.storage.has(h.keys.v1(12)), false)
})

test('submit-pending caches use the longer seven-day retention window', () => {
  const h = harness()
  h.state.storage.set(h.keys.v3(12), {
    schema_version: 3,
    saved_at: h.state.now - DRAFT_TTL_MS - 1,
    submit_pending: true,
    items: { 101: { selected_answer: 'A' } },
  })

  const loaded = h.controller.load(12)

  assert.deepEqual(loaded, Object.assign(Object.create(null), { 101: { selected_answer: 'A' } }))
  assert.equal(h.state.retainPendingForSubmit, true)
  assert.equal(h.state.clearedAttemptIds.length, 0)
})

test('persist copies numeric items and writes the v3 schema', () => {
  const h = harness()
  const pending = {
    101: { selected_answer: 'A', marked_for_review: true, used_time: 20 },
    saved_at: 'must-not-persist',
  }

  h.controller.persist(pending, 12, true)
  const persisted = h.state.storage.get(h.keys.v3(12))
  pending[101].selected_answer = 'B'

  assert.equal(persisted.schema_version, 3)
  assert.equal(persisted.saved_at, h.state.now)
  assert.equal(persisted.submit_pending, true)
  assert.deepEqual(Object.keys(persisted.items), ['101'])
  assert.equal(persisted.items[101].selected_answer, 'A')
})

test('persisting an empty pending map clears all generations', () => {
  const h = harness()
  h.state.storage.set(h.keys.v3(12), { items: { 101: { selected_answer: 'A' } } })
  h.state.storage.set(h.keys.v2(12), { 102: { selected_answer: 'B' } })
  h.state.storage.set(h.keys.v1(12), { 103: { selected_answer: 'C' } })

  h.controller.persist({}, 12, false)

  assert.deepEqual(h.state.clearedAttemptIds, [12])
  assert.equal(h.state.storage.has(h.keys.v3(12)), false)
  assert.equal(h.state.storage.has(h.keys.v2(12)), false)
  assert.equal(h.state.storage.has(h.keys.v1(12)), false)
})

test('storage failures do not break load or persist behavior', () => {
  const readFailure = harness({ readStorage: () => { throw new Error('read failed') } })
  assert.deepEqual(readFailure.controller.load(12), Object.create(null))

  const writeFailure = harness({ writeStorage: () => { throw new Error('write failed') } })
  writeFailure.controller.persist({ 101: { selected_answer: 'A' } }, 12, false)

  const clearFailure = harness({
    clearPendingAttempt: () => { throw new Error('clear failed') },
  })
  clearFailure.controller.persist({}, 12, false)
  clearFailure.state.storage.set(clearFailure.keys.v3(12), {
    schema_version: 3,
    saved_at: clearFailure.state.now - DRAFT_TTL_MS - 1,
    submit_pending: false,
    items: { 101: { selected_answer: 'A' } },
  })
  assert.deepEqual(clearFailure.controller.load(12), Object.create(null))
})
