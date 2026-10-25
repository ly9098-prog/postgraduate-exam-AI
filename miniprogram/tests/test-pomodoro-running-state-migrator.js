const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPomodoroRunningStateMigrator,
} = require('../pages/pomodoro/utils/running-state-migrator')

function createHarness(overrides = {}) {
  const state = {
    storage: new Map(),
    removed: [],
    set: [],
    subjects: [{ code: 'advanced_math', id: 7, name: '高等数学' }],
    storageFails: false,
    setFails: false,
    removeFails: false,
  }
  state.storage.set('pomodoro_running_state', {
    ok: true,
    value: { selectedSubjectCode: 'advanced_math' },
  })

  const controller = createPomodoroRunningStateMigrator({
    safeGetPomodoroStorage: (key, context) => {
      state.getContexts = state.getContexts || []
      state.getContexts.push({ key, context })
      return state.storageFails
        ? { ok: false, value: null }
        : (state.storage.get(key) || { ok: true, value: null })
    },
    safeSetPomodoroStorage: (key, value, context) => {
      state.set.push({ key, value, context })
      return !state.setFails
    },
    safeRemovePomodoroStorage: (key, context) => {
      state.removed.push({ key, context })
      return !state.removeFails
    },
    ...overrides,
  })
  return { controller, state }
}

test('already migrated cache (with id) short-circuits without writes', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', {
    ok: true,
    value: { selectedSubjectId: 7, selectedSubjectCode: 'advanced_math' },
  })

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.deepEqual(state.set, [])
  assert.deepEqual(state.removed, [])
})

test('missing local snapshot short-circuits without writes', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', { ok: true, value: null })

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.deepEqual(state.set, [])
  assert.deepEqual(state.removed, [])
})

test('missing selectedSubjectCode short-circuits without writes', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', { ok: true, value: {} })

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.deepEqual(state.set, [])
  assert.deepEqual(state.removed, [])
})

test('matching subject writes refreshed id and missing name, returns true', () => {
  const { controller, state } = createHarness()

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.deepEqual(state.set, [
    {
      key: 'pomodoro_running_state',
      value: {
        selectedSubjectCode: 'advanced_math',
        selectedSubjectId: 7,
        selectedSubjectName: '高等数学',
      },
      context: 'running snapshot refresh',
    },
  ])
  assert.deepEqual(state.removed, [])
})

test('matching subject preserves existing name when present', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', {
    ok: true,
    value: { selectedSubjectCode: 'advanced_math', selectedSubjectName: '旧名称' },
  })

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.equal(state.set[0].value.selectedSubjectName, '旧名称')
})

test('unmatched code clears stale running snapshot and returns removal result', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', {
    ok: true,
    value: { selectedSubjectCode: 'obsolete_code' },
  })

  const result = controller.migrate(state.subjects)

  assert.equal(result, true)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'stale running snapshot' },
  ])
  assert.deepEqual(state.set, [])
})

test('empty subject list treats code as unmatched and clears snapshot', () => {
  const { controller, state } = createHarness()

  const result = controller.migrate([])

  assert.equal(result, true)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'stale running snapshot' },
  ])
})

test('null subject list treats code as unmatched and clears snapshot', () => {
  const { controller, state } = createHarness()

  const result = controller.migrate(null)

  assert.equal(result, true)
  assert.deepEqual(state.removed, [
    { key: 'pomodoro_running_state', context: 'stale running snapshot' },
  ])
})

test('storage read failure returns false without further writes', () => {
  const { controller, state } = createHarness()
  state.storageFails = true

  const result = controller.migrate(state.subjects)

  assert.equal(result, false)
  assert.deepEqual(state.set, [])
  assert.deepEqual(state.removed, [])
})

test('storage set failure on refresh returns false and skips removal', () => {
  const { controller, state } = createHarness()
  state.setFails = true

  const result = controller.migrate(state.subjects)

  assert.equal(result, false)
  assert.deepEqual(state.removed, [])
})

test('storage remove failure on stale cleanup returns false', () => {
  const { controller, state } = createHarness()
  state.storage.set('pomodoro_running_state', {
    ok: true,
    value: { selectedSubjectCode: 'obsolete_code' },
  })
  state.removeFails = true

  const result = controller.migrate(state.subjects)

  assert.equal(result, false)
})
