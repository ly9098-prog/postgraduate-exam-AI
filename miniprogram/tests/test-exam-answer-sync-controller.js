const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createExamAnswerSyncController,
} = require('../subpackages/exam/utils/exam-answer-sync-controller')

function harness(overrides = {}) {
  const state = {
    pending: Object.create(null),
    patchCalls: [],
    patchResponses: [],
    persisted: 0,
    terminalSynced: false,
    errors: [],
    toasts: [],
  }
  const options = {
    getPendingItem: itemId => state.pending[String(itemId)],
    removePendingItem: itemId => { delete state.pending[String(itemId)] },
    getPendingItemIds: () => Object.keys(state.pending),
    isPendingItemUnchanged: (itemId, snapshot) => {
      const current = state.pending[String(itemId)]
      return !!current && JSON.stringify(current) === JSON.stringify(snapshot)
    },
    getMaxSyncPasses: () => 2,
    persistPending: () => { state.persisted += 1 },
    patchAnswer: async (itemId, snapshot) => {
      state.patchCalls.push({ itemId, snapshot })
      return state.patchResponses.shift() || { status: 'in_progress' }
    },
    onTerminalSync: () => { state.terminalSynced = true },
    resolveTerminalSyncConflict: async error => {
      state.errors.push(error)
      return false
    },
    showFlushError: () => { state.toasts.push('sync failed') },
    ...overrides,
  }
  return { options, state, get controller() { return createExamAnswerSyncController(options) } }
}

test('syncs and removes an unchanged pending snapshot', async () => {
  const h = harness()
  h.state.pending[101] = { selected_answer: 'A', used_time: 10 }

  await h.controller.syncItem(101)

  assert.deepEqual(h.state.patchCalls, [{
    itemId: '101',
    snapshot: { selected_answer: 'A', used_time: 10 },
  }])
  assert.equal(h.state.pending[101], undefined)
  assert.equal(h.state.persisted, 1)
  assert.equal(h.state.terminalSynced, false)
})

test('keeps a newer pending snapshot when it changes during PATCH', async () => {
  const h = harness()
  let patchCount = 0
  h.options.patchAnswer = async (itemId, snapshot) => {
    h.state.patchCalls.push({ itemId, snapshot })
    patchCount += 1
    if (patchCount === 1) h.state.pending[101] = { selected_answer: 'B', used_time: 20 }
    return { status: 'in_progress' }
  }
  h.state.pending[101] = { selected_answer: 'A', used_time: 10 }

  await h.controller.syncItem(101)

  assert.deepEqual(h.state.patchCalls.map(call => call.snapshot.selected_answer), ['A', 'B'])
  assert.equal(h.state.pending[101], undefined)
  assert.equal(h.state.persisted, 1)
})

test('terminal PATCH responses clear pending and invoke page navigation', async () => {
  const h = harness({
    patchAnswer: async () => ({ status: 'submitted' }),
  })
  h.state.pending[101] = { selected_answer: 'A' }

  await h.controller.syncItem(101)

  assert.equal(h.state.pending[101], undefined)
  assert.equal(h.state.persisted, 1)
  assert.equal(h.state.terminalSynced, true)
})

test('409 conflicts delegate to terminal reconciliation', async () => {
  const conflict = new Error('conflict')
  conflict.statusCode = 409
  const h = harness({
    patchAnswer: async () => { throw conflict },
    resolveTerminalSyncConflict: async error => {
      h.state.errors.push(error)
      return true
    },
  })
  h.state.pending[101] = { selected_answer: 'A' }

  await h.controller.syncItem(101)

  assert.deepEqual(h.state.errors, [conflict])
  assert.equal(h.state.pending[101], undefined || h.state.pending[101])
  assert.equal(h.state.terminalSynced, false)
})

test('non-conflict PATCH failures propagate after one attempt', async () => {
  const failure = new Error('network')
  const h = harness({ patchAnswer: async () => { throw failure } })
  h.state.pending[101] = { selected_answer: 'A' }

  await assert.rejects(() => h.controller.syncItem(101), failure)
  assert.deepEqual(h.state.pending[101], { selected_answer: 'A' })
})

test('reuses one in-flight sync per item', async () => {
  let releasePatch
  const h = harness()
  h.options.patchAnswer = (itemId, snapshot) => {
    h.state.patchCalls.push({ itemId, snapshot })
    return new Promise(resolve => { releasePatch = resolve })
  }
  h.state.pending[101] = { selected_answer: 'A' }

  const controller = h.controller
  const first = controller.syncItem(101)
  const second = controller.syncItem(101)
  releasePatch({ status: 'in_progress' })
  await Promise.all([first, second])

  assert.equal(h.state.patchCalls.length, 1)
})

test('flush rescans pending IDs until the queue is empty', async () => {
  const h = harness()
  h.options.patchAnswer = async (itemId, snapshot) => {
    h.state.patchCalls.push({ itemId, snapshot })
    if (itemId === '101') h.state.pending[102] = { selected_answer: 'B' }
    return { status: 'in_progress' }
  }
  h.state.pending[101] = { selected_answer: 'A' }

  assert.equal(await h.controller.flushAllPending({ quiet: true }), true)
  assert.deepEqual(h.state.patchCalls.map(call => call.itemId), ['101', '102'])
  assert.equal(Object.keys(h.state.pending).length, 0)
})

test('flush failure shows the user toast unless quiet', async () => {
  const failure = new Error('network')
  const h = harness()
  h.options.patchAnswer = async () => { throw failure }
  h.state.pending[101] = { selected_answer: 'A' }

  await assert.rejects(() => h.controller.flushAllPending(), failure)
  assert.deepEqual(h.state.toasts, ['sync failed'])

  const quiet = harness()
  quiet.options.patchAnswer = async () => { throw failure }
  quiet.state.pending[101] = { selected_answer: 'A' }
  await assert.rejects(() => quiet.controller.flushAllPending({ quiet: true }), failure)
  assert.deepEqual(quiet.state.toasts, [])
})
