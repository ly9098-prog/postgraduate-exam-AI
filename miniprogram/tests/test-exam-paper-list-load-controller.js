const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createPaperListLoadController,
} = require('../subpackages/exam/utils/paper-list-load-controller')

function harness(overrides = {}) {
  const state = {
    generation: 0,
    pageAlive: true,
    loadedOnce: false,
    data: { loading: true, errorText: '' },
    rows: [{ id: 1 }],
    error: null,
    commits: [],
    toasts: [],
    sets: [],
  }
  const options = {
    nextGeneration: () => ++state.generation,
    getGeneration: () => state.generation,
    isPageAlive: () => state.pageAlive,
    wasLoadedOnce: () => state.loadedOnce,
    markLoadedOnce: () => { state.loadedOnce = true },
    getErrorText: () => state.data.errorText,
    setData: data => { state.sets.push(data); Object.assign(state.data, data) },
    getPapers: async () => {
      if (state.error) throw state.error
      return state.rows
    },
    getErrorMessage: error => `msg:${error && error.message}`,
    showToast: options => state.toasts.push(options),
    buildPapers: rows => [{ ...rows[0], mapped: true }],
    commitPapers: (papers, commitOptions) => {
      state.commits.push({ papers, commitOptions })
    },
    ...overrides.options,
  }
  return { state, options, get controller() { return createPaperListLoadController(options) } }
}

test('first load shows loading, maps rows, marks loaded and commits non-silent', async () => {
  const h = harness()
  assert.equal(await h.controller.load(), undefined)
  assert.deepEqual(h.state.sets, [{ loading: true, errorText: '' }])
  assert.equal(h.state.loadedOnce, true)
  assert.deepEqual(h.state.commits, [{
    papers: [{ id: 1, mapped: true }],
    commitOptions: { silent: false },
  }])
})

test('silent first load does not show loading and preserves silent commit', async () => {
  const h = harness()
  await h.controller.load({ silent: true })
  assert.deepEqual(h.state.sets, [])
  assert.deepEqual(h.state.commits[0].commitOptions, { silent: true })
})

test('subsequent load commits silent even when not requested', async () => {
  const h = harness()
  await h.controller.load()
  await h.controller.load()
  assert.deepEqual(h.state.commits[1].commitOptions, { silent: true })
})

test('in-flight load is reused unless force is set', async () => {
  const h = harness()
  const controller = h.controller
  let release
  h.options.getPapers = () => new Promise(resolve => { release = resolve })
  const first = controller.load()
  const second = controller.load()
  // load() returns an awaitable wrapper each call, but the second call must
  // not start a second request; it awaits the same in-flight request.
  release([{ id: 1 }])
  await Promise.all([first, second])
  assert.equal(h.state.commits.length, 1)

  let releaseForce
  h.options.getPapers = () => new Promise(resolve => { releaseForce = resolve })
  const third = controller.load({ force: true })
  releaseForce([{ id: 2 }])
  await third
  assert.equal(h.state.commits.length, 2)
})

test('force during in-flight load discards the older response and commits the newer one', async () => {
  const h = harness()
  const controller = h.controller
  let releaseOld
  let releaseNew
  let call = 0
  h.options.getPapers = () => {
    call += 1
    return call === 1
      ? new Promise(resolve => { releaseOld = resolve })
      : new Promise(resolve => { releaseNew = resolve })
  }
  const oldRequest = controller.load()
  const newRequest = controller.load({ force: true })
  assert.notEqual(newRequest, oldRequest)
  releaseNew([{ id: 2 }])
  await newRequest
  assert.equal(h.state.commits.length, 1)
  assert.equal(h.state.commits[0].papers[0].id, 2)
  releaseOld([{ id: 1 }])
  await oldRequest
  assert.equal(h.state.commits.length, 1) // older generation response discarded
  assert.equal(h.state.commits[0].papers[0].id, 2)
})

test('stale generation responses are discarded', async () => {
  const h = harness()
  const controller = h.controller
  let release
  h.options.getPapers = () => new Promise(resolve => { release = resolve })
  const first = controller.load()
  h.state.generation = 99 // simulate a newer request or unload
  release([{ id: 1 }])
  await first
  assert.deepEqual(h.state.commits, [])
  assert.equal(h.state.loadedOnce, false)
})

test('dead page responses are discarded', async () => {
  const h = harness()
  h.state.pageAlive = false
  await h.controller.load()
  assert.deepEqual(h.state.commits, [])
})

test('first-load error writes loading=false and errorText', async () => {
  const h = harness()
  h.state.error = new Error('network')
  await h.controller.load()
  assert.deepEqual(h.state.sets.at(-1), { loading: false, errorText: 'msg:network' })
  assert.deepEqual(h.state.toasts, [])
})

test('silent error on loaded page shows toast unless suppressed', async () => {
  const h = harness()
  await h.controller.load()
  h.state.error = new Error('offline')
  await h.controller.load({ silent: true })
  assert.deepEqual(h.state.toasts, [{ title: 'msg:offline', icon: 'none' }])
  assert.equal(h.state.data.errorText, '')

  h.state.toasts.length = 0
  await h.controller.load({ silent: true, suppressErrorToast: true })
  assert.deepEqual(h.state.toasts, [])
})

test('non-silent error after a successful load shows toast when errorText is empty', async () => {
  const h = harness()
  const controller = h.controller
  await controller.load()
  h.state.error = new Error('retry failed')
  await controller.load() // retryLoad() path: non-silent, loadedOnce=true, errorText=''
  assert.deepEqual(h.state.toasts, [{ title: 'msg:retry failed', icon: 'none' }])
  assert.equal(h.state.data.errorText, '')
  // The toast branch returns without touching loading; the prior successful
  // load already set loading=false via commitPapers in production.
  assert.deepEqual(h.state.sets, [{ loading: true, errorText: '' }])
})

test('silent error with existing error text does not toast but overwrites text', async () => {
  const h = harness()
  const controller = h.controller
  await controller.load()
  h.state.data.errorText = 'previous error'
  h.state.error = new Error('offline')
  await controller.load({ silent: true })
  assert.deepEqual(h.state.toasts, [])
  assert.equal(h.state.data.errorText, 'msg:offline')
})

test('stale errors and dead-page errors are discarded', async () => {
  const h = harness()
  const controller = h.controller
  let reject
  h.options.getPapers = () => new Promise((_, rejectPromise) => { reject = rejectPromise })
  const first = controller.load()
  h.state.generation = 99
  reject(new Error('network'))
  await first
  // The initial loading setData happened before the request; no error write occurs.
  assert.deepEqual(h.state.sets, [{ loading: true, errorText: '' }])
  assert.deepEqual(h.state.toasts, [])
})
