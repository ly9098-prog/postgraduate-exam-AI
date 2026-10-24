const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createSubjectMetaController,
} = require('../subpackages/productivity/pomodoro-stats/subject-meta-controller')

function createHarness(overrides = {}) {
  const state = {
    loaded: false,
    meta: null,
    promise: null,
    trees: [{ subject_id: 1, subject_name: '408' }],
    errors: [],
  }
  const options = {
    isLoaded: () => state.loaded,
    getMeta: () => state.meta,
    setMeta: value => { state.meta = value },
    getPromise: () => state.promise,
    setPromise: value => { state.promise = value },
    markLoaded: () => { state.loaded = true },
    getSubjectTree: async () => {
      if (state.trees instanceof Error) throw state.trees
      return state.trees
    },
    buildSubjectMeta: tree => ({ byId: tree[0].subject_id, tree }),
    logError: (message, error) => state.errors.push({ message, error }),
    ...overrides,
  }
  return { controller: createSubjectMetaController(options), state }
}

test('loads, caches, and returns subject metadata', async () => {
  const h = createHarness()
  const meta = await h.controller.ensure()

  assert.equal(meta.byId, 1)
  assert.equal(h.state.loaded, true)
  assert.equal(h.state.promise, null)
})

test('reuses the loaded metadata without another request', async () => {
  const h = createHarness()
  await h.controller.ensure()
  h.state.trees = new Error('must not refetch')

  const meta = await h.controller.ensure()
  assert.equal(meta.byId, 1)
  assert.deepEqual(h.state.errors, [])
})

test('reuses an in-flight request', async () => {
  const h = createHarness()
  const first = h.controller.ensure()
  const second = h.controller.ensure()
  assert.equal(second, first)
  assert.equal(await first, await second)
})

test('marks a failed load as complete and returns null', async () => {
  const h = createHarness()
  const failure = new Error('network')
  h.state.trees = failure

  assert.equal(await h.controller.ensure(), null)
  assert.equal(h.state.meta, null)
  assert.equal(h.state.loaded, true)
  assert.equal(h.state.promise, null)
  assert.deepEqual(h.state.errors, [{ message: '加载科目树失败', error: failure }])
})
