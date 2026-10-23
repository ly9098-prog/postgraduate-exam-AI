const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createUnknownStartController,
} = require('../pages/pomodoro/utils/unknown-start-controller')
const {
  buildUnknownStartAttempt,
  buildUnknownStartPayload,
  matchesUnknownStartAttempt,
  startCancellationAt,
} = require('../pages/pomodoro/utils/unknown-start-helpers')

const STORAGE_KEY = 'pomodoro_unknown_start'

function unknownStartAttempt(overrides = {}) {
  return {
    requestedAt: 1000,
    cancelIfFound: false,
    cancelAt: null,
    clientStartId: 'attempt-1',
    subjectId: 4,
    chapterId: null,
    preset: 'standard',
    workDuration: 25,
    breakDuration: 5,
    allocationMode: 'single',
    notificationEnabled: false,
    taskType: 'study',
    ...overrides,
  }
}

function shouldFail(specification, ...args) {
  if (typeof specification === 'function') return specification(...args)
  return specification === true
}

function createHarness(overrides = {}) {
  const calls = {
    events: [],
    reads: [],
    writes: [],
    removes: [],
    posts: [],
    pending: [],
    retries: 0,
    errors: 0,
    resets: 0,
    records: [],
    restores: [],
  }
  const state = {
    stored: Object.hasOwn(overrides, 'storedAttempt') ? overrides.storedAttempt : null,
  }
  const page = {
    data: {
      selectedSubjectId: 4,
      selectedPreset: 'standard',
      allocationMode: 'single',
      fromChapterId: '',
      workDuration: 25,
      breakDuration: 5,
      selectedTaskType: 'study',
    },
    _pageVisible: overrides.pageVisible !== false,
    _startRequestSeq: overrides.startRequestSeq || 3,
    _safeGetPomodoroStorage(key, context) {
      calls.reads.push([key, context])
      if (overrides.readFailure) return { ok: false, value: null }
      return { ok: true, value: state.stored }
    },
    _safeSetPomodoroStorage(key, value, context) {
      calls.events.push(`write:${context}`)
      calls.writes.push([key, value, context])
      const ok = !shouldFail(overrides.writeFailure, value, context)
      if (ok) state.stored = value
      return ok
    },
    _safeRemovePomodoroStorage(key, context) {
      calls.events.push(`remove:${context}`)
      calls.removes.push([key, context])
      const ok = !shouldFail(overrides.removeFailure, context)
      if (ok) state.stored = null
      return ok
    },
    _setPendingPomodoroSync(action, sessionId, clientActionAt) {
      calls.pending.push([action, sessionId, clientActionAt])
      return overrides.pendingResult === undefined
        ? { action, sessionId, clientActionAt }
        : overrides.pendingResult
    },
    _retryPendingPomodoroSync() {
      calls.retries += 1
      return Promise.resolve(true)
    },
    _resetToIdle() {
      calls.resets += 1
    },
    _showPomodoroPersistenceError() {
      calls.errors += 1
    },
    _restoreSession(session) {
      calls.restores.push(session)
      return overrides.restoreResult === undefined ? true : overrides.restoreResult
    },
  }
  function post(path, payload) {
    calls.events.push('post')
    calls.posts.push([path, payload])
    if (overrides.postError) return Promise.reject(overrides.postError)
    if (overrides.post) return overrides.post(path, payload, calls)
    return Promise.resolve({
      id: 10,
      status: 'running',
      client_start_id: payload.client_start_id,
      start_time: 1000,
      ...overrides.session,
    })
  }
  const controller = createUnknownStartController({
    page,
    storageKey: STORAGE_KEY,
    post,
    createClientStartId: () => overrides.generatedClientStartId || 'generated-attempt',
    now: () => overrides.now || 5000,
    parseServerTime: value => overrides.parseServerTime
      ? overrides.parseServerTime(value)
      : Number(value),
    buildAttempt: buildUnknownStartAttempt,
    buildPayload: overrides.buildPayload || buildUnknownStartPayload,
    matches: matchesUnknownStartAttempt,
    startCancellationAt,
    recordSession(session, taskType) {
      calls.records.push([session.id, taskType])
    },
    reconcile: attempt => controller.reconcile(attempt),
  })
  return {
    controller,
    page,
    calls,
    state,
    setStored(value) {
      state.stored = value
    },
  }
}

test('postStart persists a generated idempotency key before the request', async () => {
  const harness = createHarness({
    session: { status: 'completed' },
  })

  const result = await harness.controller.postStart({
    subject_id: 4,
    allocation_mode: 'single',
    chapter_id: null,
    preset: 'standard',
    work_duration: 25,
    break_duration: 5,
  }, 3)

  assert.equal(result.handled, false)
  assert.equal(result.session.id, 10)
  assert.equal(harness.calls.posts.length, 1)
  assert.equal(harness.calls.posts[0][0], '/pomodoro/start')
  assert.equal(harness.calls.posts[0][1].client_start_id, 'generated-attempt')
  assert.equal(harness.calls.writes[0][1].clientStartId, 'generated-attempt')
  assert.ok(
    harness.calls.events.indexOf('write:before pomodoro start') <
    harness.calls.events.indexOf('post')
  )
})

test('postStart does not issue a request when the recovery marker cannot persist', async () => {
  const harness = createHarness({ writeFailure: true })

  const result = await harness.controller.postStart({ preset: 'standard' }, 3)

  assert.deepEqual(result, { handled: true, session: null })
  assert.equal(harness.calls.posts.length, 0)
  assert.equal(harness.calls.errors, 1)
  assert.equal(harness.calls.resets, 1)
})

test('reconcile fails closed on unreadable storage', async () => {
  const harness = createHarness({ readFailure: true })

  assert.equal(await harness.controller.reconcile(), 'storage_error')
  assert.equal(harness.calls.posts.length, 0)
  assert.equal(harness.calls.removes.length, 0)
})

test('reconcile removes invalid attempts and invalid request payloads', async () => {
  const invalidAttempt = createHarness({
    storedAttempt: { clientStartId: '' },
  })
  assert.equal(await invalidAttempt.controller.reconcile(), 'none')
  assert.deepEqual(invalidAttempt.calls.removes[0][1], 'invalid unknown start')
  assert.equal(invalidAttempt.calls.posts.length, 0)

  const invalidPayload = createHarness({
    storedAttempt: unknownStartAttempt(),
    buildPayload: () => null,
  })
  assert.equal(await invalidPayload.controller.reconcile(), 'none')
  assert.deepEqual(invalidPayload.calls.removes[0][1], 'invalid unknown start payload')
  assert.equal(invalidPayload.calls.posts.length, 0)
})

test('reconcile prefers the latest stored attempt for a matching idempotency key', async () => {
  const stored = unknownStartAttempt({
    subjectId: 7,
    taskType: 'review',
    cancelIfFound: true,
    cancelAt: 1500,
  })
  const harness = createHarness({
    storedAttempt: stored,
    session: { status: 'completed' },
  })

  assert.equal(
    await harness.controller.reconcile(unknownStartAttempt({
      taskType: 'study',
      subjectId: 4,
    })),
    'settled'
  )
  assert.equal(harness.calls.posts[0][1].subject_id, 7)
  assert.deepEqual(harness.calls.records, [[10, 'review']])
})

test('reconcile uses an explicit attempt when it differs from the stored attempt', async () => {
  const harness = createHarness({
    storedAttempt: unknownStartAttempt({ clientStartId: 'older-attempt', subjectId: 7 }),
    session: {
      status: 'completed',
      client_start_id: 'explicit-attempt',
    },
  })

  assert.equal(
    await harness.controller.reconcile(unknownStartAttempt({
      clientStartId: 'explicit-attempt',
      subjectId: 4,
    })),
    'settled'
  )
  assert.equal(harness.calls.posts[0][1].client_start_id, 'explicit-attempt')
  assert.equal(harness.calls.posts[0][1].subject_id, 4)
})

test('reconcile rejects a response whose idempotency key does not match', async () => {
  const harness = createHarness({
    storedAttempt: unknownStartAttempt(),
    session: {
      status: 'running',
      client_start_id: 'different-attempt',
    },
  })

  assert.equal(await harness.controller.reconcile(), 'none')
  assert.deepEqual(harness.calls.removes[0][1], 'mismatched unknown start')
  assert.equal(harness.calls.records.length, 0)
})

test('offline and server failures retain the uncertain start for replay', async () => {
  for (const statusCode of [0, 500, 503]) {
    const harness = createHarness({
      storedAttempt: unknownStartAttempt(),
      postError: { statusCode },
    })

    assert.equal(await harness.controller.reconcile(), 'offline')
    assert.equal(harness.state.stored.clientStartId, 'attempt-1')
    assert.equal(harness.calls.removes.length, 0)
  }
})

test('permanent request failures settle the marker or fail closed on cleanup errors', async () => {
  const permanent = createHarness({
    storedAttempt: unknownStartAttempt(),
    postError: { statusCode: 422 },
  })
  assert.equal(await permanent.controller.reconcile(), 'none')
  assert.deepEqual(permanent.calls.removes[0][1], 'settled failed start')
  assert.equal(permanent.state.stored, null)

  const cleanupFailure = createHarness({
    storedAttempt: unknownStartAttempt(),
    postError: { statusCode: 422 },
    removeFailure: context => context === 'settled failed start',
  })
  assert.equal(await cleanupFailure.controller.reconcile(), 'storage_error')
  assert.equal(cleanupFailure.state.stored.clientStartId, 'attempt-1')
})

test('an active cancellation is durably queued before the marker is cleared', async () => {
  const harness = createHarness({
    storedAttempt: unknownStartAttempt({
      cancelIfFound: true,
      cancelAt: 2000,
    }),
    session: {
      status: 'running',
      start_time: 1000,
    },
  })

  assert.equal(await harness.controller.reconcile(), 'cancelled')
  assert.deepEqual(harness.calls.pending, [['interrupt', 10, 2000]])
  assert.deepEqual(harness.calls.removes[0][1], 'interrupt queued for unknown start')
  assert.equal(harness.calls.retries, 1)
  assert.equal(harness.calls.resets, 1)
  assert.deepEqual(harness.calls.records, [[10, 'study']])
})

test('a failed cancellation queue preserves the exact cancel credential', async () => {
  const harness = createHarness({
    storedAttempt: unknownStartAttempt({
      cancelIfFound: true,
      cancelAt: 2000,
    }),
    pendingResult: null,
  })

  assert.equal(await harness.controller.reconcile(), 'storage_error')
  assert.equal(harness.calls.removes.length, 0)
  assert.equal(harness.calls.retries, 0)
  assert.equal(harness.calls.writes.at(-1)[2], 'retain cancelled unknown start')
  assert.equal(harness.state.stored.clientStartId, 'attempt-1')
  assert.equal(harness.state.stored.cancelIfFound, true)
  assert.equal(harness.state.stored.cancelAt, 2000)
})

test('an active matching session is restored only after the marker is cleared', async () => {
  const visible = createHarness({
    storedAttempt: unknownStartAttempt(),
  })
  assert.equal(await visible.controller.reconcile(), 'restored')
  assert.deepEqual(visible.calls.removes[0][1], 'resolved active start')
  assert.deepEqual(visible.calls.restores, [{
    id: 10,
    status: 'running',
    client_start_id: 'attempt-1',
    start_time: 1000,
  }])

  const restoreFailure = createHarness({
    storedAttempt: unknownStartAttempt(),
    restoreResult: false,
  })
  assert.equal(await restoreFailure.controller.reconcile(), 'storage_error')

  const hidden = createHarness({
    storedAttempt: unknownStartAttempt(),
    pageVisible: false,
  })
  assert.equal(await hidden.controller.reconcile(), 'restored')
  assert.equal(hidden.calls.restores.length, 0)
})

test('a terminal matching session is recorded and settled', async () => {
  const harness = createHarness({
    storedAttempt: unknownStartAttempt(),
    session: { status: 'completed' },
  })

  assert.equal(await harness.controller.reconcile(), 'settled')
  assert.deepEqual(harness.calls.records, [[10, 'study']])
  assert.deepEqual(harness.calls.removes[0][1], 'resolved terminal start')
})

test('a late start response interrupts the latest stored cancellation intent', async () => {
  let harness
  harness = createHarness({
    pageVisible: false,
    post: async (path, payload) => {
      harness.setStored(unknownStartAttempt({
        clientStartId: payload.client_start_id,
        cancelIfFound: true,
        cancelAt: 9000,
      }))
      return {
        id: 10,
        status: 'running',
        client_start_id: payload.client_start_id,
        start_time: 8000,
      }
    },
  })

  const result = await harness.controller.postStart({ preset: 'standard' }, 3)

  assert.deepEqual(result, { handled: true, session: null })
  assert.deepEqual(harness.calls.pending, [['interrupt', 10, 9000]])
  assert.deepEqual(harness.calls.removes.at(-1)[1], 'start cancelled after response')
  assert.equal(harness.calls.retries, 1)
})

test('a late response retains its cancel credential when queueing fails', async () => {
  let harness
  harness = createHarness({
    pageVisible: false,
    pendingResult: null,
    post: async (path, payload) => {
      harness.setStored(unknownStartAttempt({
        clientStartId: payload.client_start_id,
        taskType: 'review',
      }))
      return {
        id: 10,
        status: 'running',
        client_start_id: payload.client_start_id,
        start_time: 8000,
      }
    },
  })

  const result = await harness.controller.postStart({ preset: 'standard' }, 3)

  assert.deepEqual(result, { handled: true, session: null })
  assert.equal(harness.calls.removes.length, 0)
  assert.equal(harness.calls.writes.at(-1)[2], 'retain cancelled start after response')
  assert.equal(harness.calls.writes.at(-1)[1].cancelIfFound, true)
  assert.equal(harness.calls.writes.at(-1)[1].cancelAt, 8000)
})

test('accepted start cleanup failures fail closed instead of handing back a ghost session', async () => {
  const harness = createHarness({
    storedAttempt: null,
    removeFailure: context => context === 'accepted pomodoro start',
  })

  const result = await harness.controller.postStart({ preset: 'standard' }, 3)

  assert.deepEqual(result, { handled: true, session: null })
  assert.equal(harness.calls.errors, 1)
  assert.equal(harness.calls.resets, 1)
  assert.notEqual(harness.state.stored, null)
})
