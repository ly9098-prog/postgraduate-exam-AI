const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createStartSessionController,
} = require('../pages/pomodoro/utils/start-session-controller')

function createHarness(overrides = {}) {
  const calls = {
    reconciliations: 0,
    retries: 0,
    waits: [],
    posts: [],
    toasts: [],
    persistenceErrors: 0,
    fetched: 0,
    restores: [],
    records: [],
    countdowns: [],
    freeTimers: [],
    phases: [],
  }
  const page = {
    data: {
      phase: overrides.phase || 'idle',
      selectedSubjectId: Object.hasOwn(overrides, 'selectedSubjectId')
        ? overrides.selectedSubjectId
        : 4,
      selectedSubject: Object.hasOwn(overrides, 'selectedSubject')
        ? overrides.selectedSubject
        : { id: 4, name: '数据结构' },
      subjectsError: overrides.subjectsError || '',
      subjectsLoading: Boolean(overrides.subjectsLoading),
      selectedPreset: overrides.selectedPreset || 'standard',
      allocationMode: 'single',
      fromChapterId: '',
      workDuration: 25,
      breakDuration: 5,
      selectedTaskType: 'study',
    },
    _pageVisible: overrides.pageVisible !== false,
    _startInFlight: overrides.startInFlight || false,
    _startRequestSeq: overrides.startRequestSeq || 0,
    _reconcileUnknownStartAttempt() {
      calls.reconciliations += 1
      return overrides.reconcile
        ? overrides.reconcile()
        : Promise.resolve('none')
    },
    _getPendingPomodoroSyncQueue() {
      return overrides.pendingQueue === undefined ? [] : overrides.pendingQueue
    },
    async _retryPendingPomodoroSync() {
      calls.retries += 1
      return overrides.retrySynced !== false
    },
    _postPomodoroStartWithReconciliation(payload, startSeq) {
      calls.posts.push([payload, startSeq])
      if (overrides.postError) return Promise.reject(overrides.postError)
      return Promise.resolve(overrides.startResult || {
        handled: false,
        session: { id: 10, preset: payload.preset },
      })
    },
    _startFreeSession(startSeq) {
      return controller.startFree(startSeq)
    },
    _beginCountdown(session) {
      calls.countdowns.push(session)
    },
    _beginFreeTimer(session) {
      calls.freeTimers.push(session)
    },
    _fetchActiveSession() {
      calls.fetched += 1
      return Promise.resolve(overrides.activeSession)
    },
    _isPomodoroStorageError(value) {
      return !!(value && value.storageUnreadable)
    },
    _restoreSession(session) {
      calls.restores.push(session)
      return overrides.restoreResult === undefined ? true : overrides.restoreResult
    },
    _showPomodoroPersistenceError() {
      calls.persistenceErrors += 1
    },
    setData(update) {
      if (update.phase) calls.phases.push(update.phase)
      page.data = { ...page.data, ...update }
    },
  }
  const controller = createStartSessionController({
    page,
    phases: { IDLE: 'idle', RUNNING: 'running', CEREMONY: 'ceremony' },
    ceremonyDelayMs: 2500,
    debugCeremonyDelayMs: 1000,
    wait(ms) {
      calls.waits.push(ms)
      return overrides.wait ? overrides.wait(ms) : Promise.resolve()
    },
    showToast(payload) {
      calls.toasts.push(payload)
    },
    pomodoroTaskTypes: {
      recordSession(session, taskType) {
        calls.records.push([session.id, taskType])
      },
    },
  })
  return { controller, page, calls }
}

test('starts a countdown once with the normalized payload and lifecycle sequence', async () => {
  const { controller, page, calls } = createHarness()

  await controller.start()

  assert.equal(calls.reconciliations, 1)
  assert.deepEqual(calls.waits, [2500])
  assert.deepEqual(calls.posts, [[{
    subject_id: 4,
    allocation_mode: 'single',
    chapter_id: null,
    preset: 'standard',
    work_duration: 25,
    break_duration: 5,
  }, 1]])
  assert.deepEqual(calls.records, [[10, 'study']])
  assert.deepEqual(calls.countdowns, [{ id: 10, preset: 'standard' }])
  assert.deepEqual(calls.phases, ['ceremony'])
  assert.equal(page._startInFlight, false)
})

test('uses the debug ceremony delay without changing debug duration normalization', async () => {
  const { controller, calls } = createHarness({ selectedPreset: 'debug' })

  await controller.start()

  assert.deepEqual(calls.waits, [1000])
  assert.equal(calls.posts[0][0].work_duration, 1)
  assert.equal(calls.posts[0][0].break_duration, 1)
})

test('rejects a rapid second start while the first generation is in flight', async () => {
  let releaseReconcile
  const { controller, calls } = createHarness({
    reconcile: () => new Promise(resolve => { releaseReconcile = resolve }),
  })

  const first = controller.start()
  await Promise.resolve()
  await controller.start()
  releaseReconcile('none')
  await first

  assert.equal(calls.reconciliations, 1)
  assert.equal(calls.posts.length, 1)
})

test('free preset delegates through startFree and records the free timer', async () => {
  const { controller, calls } = createHarness({ selectedPreset: 'free' })

  await controller.start()

  assert.equal(calls.posts[0][0].preset, 'free')
  assert.equal(calls.posts[0][0].work_duration, 0)
  assert.equal(calls.posts[0][0].break_duration, 0)
  assert.deepEqual(calls.freeTimers, [{ id: 10, preset: 'free' }])
  assert.deepEqual(calls.countdowns, [])
})

test('free start preserves late-response reconciliation when no pending drain hides it', async () => {
  const { controller, calls } = createHarness({
    pageVisible: false,
    startResult: { handled: true, session: null },
  })

  await controller.startFree(5)

  assert.equal(calls.posts.length, 1)
  assert.equal(calls.posts[0][1], 5)
  assert.deepEqual(calls.freeTimers, [])
})

test('free start stops after a pending drain loses page visibility', async () => {
  const { controller, page, calls } = createHarness({
    pendingQueue: [{ action: 'complete', sessionId: 9 }],
  })
  page._retryPendingPomodoroSync = async () => {
    calls.retries += 1
    page._pageVisible = false
    return true
  }

  await controller.startFree()

  assert.equal(calls.retries, 1)
  assert.equal(calls.posts.length, 0)
})

test('unresolved offline start stops before pending or network side effects', async () => {
  const { controller, calls } = createHarness({ reconcile: async () => 'offline' })

  await controller.start()

  assert.equal(calls.posts.length, 0)
  assert.equal(calls.retries, 0)
  assert.deepEqual(calls.toasts, [{
    title: '上次启动结果待确认，请联网后重试',
    icon: 'none',
  }])
})

test('pending storage and drain failures stop before a new start', async () => {
  const missing = createHarness({ pendingQueue: null })
  await missing.controller.start()
  assert.equal(missing.calls.persistenceErrors, 1)
  assert.equal(missing.calls.posts.length, 0)

  const unsynced = createHarness({
    pendingQueue: [{ action: 'complete', sessionId: 9 }],
    retrySynced: false,
  })
  await unsynced.controller.start()
  assert.equal(unsynced.calls.retries, 1)
  assert.equal(unsynced.calls.posts.length, 0)
  assert.deepEqual(unsynced.calls.toasts, [{
    title: '上次专注尚未同步，请联网后重试',
    icon: 'none',
  }])
})

test('missing subject or subject-loading failure prevents the ceremony', async () => {
  const missing = createHarness({ selectedSubjectId: null, selectedSubject: null })
  await missing.controller.start()
  assert.deepEqual(missing.calls.phases, [])
  assert.deepEqual(missing.calls.toasts, [{ title: '请选择学习科目', icon: 'none' }])

  const failed = createHarness({ subjectsError: 'failed' })
  await failed.controller.start()
  assert.deepEqual(failed.calls.phases, [])
  assert.deepEqual(failed.calls.toasts, [{ title: '科目加载异常，请重试', icon: 'none' }])
})

test('subject loading blocks both countdown and free starts with an old selected subject', async () => {
  for (const selectedPreset of ['standard', 'free']) {
    const { controller, calls } = createHarness({ subjectsLoading: true, selectedPreset })
    await controller.start()
    assert.deepEqual(calls.posts, [])
    assert.deepEqual(calls.phases, [])
    assert.deepEqual(calls.toasts, [{ title: '科目加载中，请稍候', icon: 'none' }])
  }
})

test('a hidden page aborts after the ceremony wait without posting', async () => {
  const { controller, page, calls } = createHarness({
    wait: async () => { page._pageVisible = false },
  })

  await controller.start()

  assert.equal(calls.posts.length, 0)
  assert.equal(page._startInFlight, false)
})

test('active conflict restores the authoritative session and stops at false', async () => {
  const { controller, page, calls } = createHarness({
    postError: { statusCode: 409 },
    activeSession: { id: 88 },
    restoreResult: false,
  })

  await controller.start()

  assert.equal(calls.fetched, 1)
  assert.deepEqual(calls.restores, [{ id: 88 }])
  assert.deepEqual(calls.toasts, [{
    title: '已有进行中的专注，请先结束',
    icon: 'none',
  }])
  assert.equal(page.data.phase, 'idle')
})

test('active conflict storage failure is fail-closed and reports persistence', async () => {
  const { controller, page, calls } = createHarness({
    postError: { statusCode: 409 },
    activeSession: { storageUnreadable: true },
  })

  await controller.start()

  assert.equal(calls.persistenceErrors, 1)
  assert.deepEqual(calls.restores, [])
  assert.equal(page.data.phase, 'idle')
})

test('late active-conflict response is suppressed after page hide', async () => {
  const { controller, page, calls } = createHarness()
  page._postPomodoroStartWithReconciliation = async () => {
    page._pageVisible = false
    throw { statusCode: 409 }
  }

  await controller.start()

  assert.equal(calls.fetched, 0)
  assert.deepEqual(calls.toasts, [])
  assert.equal(page._startInFlight, false)
})

test('generic countdown failure resets idle while generic free failure keeps current phase', async () => {
  const countdown = createHarness({ postError: new Error('boom') })
  await countdown.controller.start()
  assert.deepEqual(countdown.calls.toasts, [{ title: '启动失败', icon: 'none' }])
  assert.equal(countdown.page.data.phase, 'idle')

  const free = createHarness({
    selectedPreset: 'free',
    postError: new Error('boom'),
  })
  free.page.data.phase = 'running'
  await free.controller.startFree()
  assert.deepEqual(free.calls.toasts, [{ title: '启动失败，请重试', icon: 'none' }])
  assert.equal(free.page.data.phase, 'running')
})
