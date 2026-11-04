const assert = require('node:assert/strict')
const { test } = require('node:test')

const memory = new Map()
global.wx = {
  getStorageSync: key => memory.get(key),
  setStorageSync: (key, value) => memory.set(key, structuredClone(value)),
  removeStorageSync: key => memory.delete(key),
  getStorageInfoSync: () => ({ keys: [...memory.keys()] }),
  reLaunch: () => {},
}
const storage = require('../utils/storage-core')
const storePath = '../utils/launch-session-store'
const launchPath = '../utils/launch-resume'
const loadStore = () => {
  try { return require(storePath) } catch { return {} }
}

function reset() {
  memory.clear()
  memory.set('user', { id: 11 })
  memory.set('token', 'token')
}

test('resume store provides user-scoped snapshot and active marker operations', () => {
  reset()
  const store = loadStore()
  assert.equal(typeof store.savePractice, 'function')
  store.savePractice({ requestId: 'r', batchToken: 'b', questions: [{ id: 1 }],
    currentIndex: 0, elapsedMs: 1200 }, 100)
  assert.equal(store.readPractice(200).requestId, 'r')
  assert.equal(store.readActive(200).kind, 'practice')
  memory.set('user', { id: 12 })
  assert.equal(store.readPractice(200), null)
  assert.equal(store.readActive(200), null)
  memory.set('user', { id: 11 })
  store.clearPractice()
  assert.equal(store.readPractice(200), null)
  assert.equal(store.readActive(200), null)
})

test('practice expiry is fixed at batch creation and corrupt snapshots are removed', () => {
  reset()
  const store = loadStore()
  assert.equal(typeof store.savePractice, 'function')
  const snapshot = { requestId: 'r', batchToken: 'b', questions: [{ id: 1 }], currentIndex: 0, elapsedMs: 1 }
  store.savePractice(snapshot, 100)
  store.savePractice({ ...snapshot, elapsedMs: 2000 }, 200)
  assert.equal(store.readPractice(100 + 86400000), null)
  assert.equal(store.readActive(100 + 86400000), null)
  for (const changes of [
    { currentIndex: 9 }, { elapsedMs: -1 }, { elapsedMs: NaN }, { batchToken: {} },
    { questions: [{ id: 1 }, { id: 1 }] }, { owner: 'another-user' },
  ]) {
    memory.set('practice_resume_v1:11', { ...snapshot, version: 1, createdAt: 100, owner: '11', ...changes })
    assert.equal(store.readPractice(200), null)
    assert.equal(memory.has('practice_resume_v1:11'), false)
  }
})

test('a future pending timestamp is not discarded as expired', () => {
  reset()
  const store = loadStore()
  const now = 1000
  memory.set('practice_pending_submission_v1:11', {
    version: 1, status: 'pending', updatedAt: now + 1000, submission: { requestId: 'r' },
  })
  assert.equal(store.readPending(now).status, 'pending')
  assert.equal(memory.has('practice_pending_submission_v1:11'), true)
})

test('clock rollback preserves practice answers, original expiry and launch routing', async () => {
  reset()
  const store = loadStore()
  const { resolveLaunchTarget } = require(launchPath)
  const createdAt = 100000
  const snapshot = { requestId: 'r', batchToken: 'b', questions: [{ id: 1 }],
    currentIndex: 0, elapsedMs: 1200, answerMap: { 1: 'A' } }
  store.savePractice(snapshot, createdAt)
  const restored = store.readPractice(createdAt - 1000)
  assert.deepEqual(restored.answerMap, { 1: 'A' })
  assert.match(await resolveLaunchTarget({ now: createdAt - 1000 }), /practice\?resume=1$/)
  assert.equal(store.savePractice({ ...restored, elapsedMs: 2000 }, createdAt - 1000), true)
  assert.equal(store.readPractice(createdAt).createdAt, createdAt)
  assert.equal(store.readPractice(createdAt + 86400000), null)
  assert.equal(store.readActive(createdAt + 86400000), null)
})

test('review marker uses the single active slot and expires across China dates', () => {
  reset()
  const store = loadStore()
  assert.equal(typeof store.markReview, 'function')
  store.markReview('2026-11-05')
  assert.equal(store.readActive(Date.parse('2026-11-05T15:59:59Z')).kind, 'review-today')
  assert.equal(store.readActive(Date.parse('2026-11-05T16:00:00Z')), null)
  store.markReview('2026-11-05')
  store.clearActive('practice')
  assert.equal(store.readActive(Date.parse('2026-11-05T12:00:00Z')).kind, 'review-today')
  store.clearActive('review-today')
  assert.equal(store.readActive(Date.parse('2026-11-05T12:00:00Z')), null)
})

test('logout clears both new dynamic prefixes', () => {
  reset()
  memory.set('study_active_v1:11', {})
  memory.set('practice_resume_v1:11', {})
  global.wx.getStorageInfoSync = () => ({ keys: [...memory.keys()] })
  storage.clearSession()
  assert.equal(memory.has('study_active_v1:11'), false)
  assert.equal(memory.has('practice_resume_v1:11'), false)
})

test('launch resolver exists with explicit cold-entry policy', () => {
  let launch
  try { launch = require(launchPath) } catch { launch = {} }
  assert.equal(typeof launch.resolveLaunchTarget, 'function')
  assert.equal(typeof launch.createLoginResume, 'function')
})

test('local practice and pending/blocked records take precedence without requesting pomodoro', async () => {
  reset()
  const store = loadStore(), { resolveLaunchTarget } = require(launchPath)
  const now = Date.now()
  const getActive = () => { throw Error('must not request') }
  store.savePractice({ requestId: 'r', batchToken: 'b', questions: [{ id: 1 }],
    currentIndex: 0, elapsedMs: 1 }, now)
  assert.match(await resolveLaunchTarget({ getActive, now }), /practice\?resume=1$/)
  memory.set('pomodoro_completion', { id: 1 })
  assert.match(await resolveLaunchTarget({ getActive, now }), /practice\?resume=1$/)
  memory.delete('pomodoro_completion')
  store.markReview('2026-11-05')
  for (const status of ['pending', 'blocked']) {
    memory.set('practice_pending_submission_v1:11',
      { version: 1, status, updatedAt: now, submission: { requestId: 'r' } })
    assert.match(await resolveLaunchTarget({ getActive, now }), /practice\?resume=1$/)
  }
  memory.set('practice_pending_submission_v1:11',
    { version: 1, status: 'submitted', updatedAt: now, submission: {} })
  assert.match(await resolveLaunchTarget({ getActive, now: Date.parse('2026-11-05T12:00:00Z') }),
    /review-today\?autostart=1$/)
})

test('active server countdown, paused and free timers resume, terminal or absent sessions do not', async () => {
  reset()
  const { resolveLaunchTarget } = require(launchPath)
  for (const preset of ['standard', 'free']) {
    for (const status of ['running', 'paused']) {
      assert.equal(await resolveLaunchTarget({ getActive: async () =>
        ({ id: 1, status, preset, start_time: '2020-01-01' }) }), '/pages/pomodoro/pomodoro')
    }
  }
  for (const response of [null, { status: 'completed' }, { status: 'cancelled' }]) {
    assert.equal(await resolveLaunchTarget({ getActive: async () => response }), '/pages/home/home')
  }
  memory.set('pomodoro_break', { id: 1 })
  assert.equal(await resolveLaunchTarget({ getActive: async () =>
    ({ id: 1, status: 'running', preset: 'standard' }) }), '/pages/home/home')
  memory.set('pomodoro_break', null)
  memory.set('pomodoro_completion', { id: 1 })
  assert.equal(await resolveLaunchTarget({ getActive: async () =>
    ({ id: 1, status: 'paused', preset: 'free' }) }), '/pages/home/home')
})

test('network failure falls back only to an owned active local snapshot', async () => {
  reset()
  const { resolveLaunchTarget } = require(launchPath)
  const getActive = async () => { throw Error('network') }
  const local = { ownerId: '11', sessionId: 42, sessionStartTime: 123, isPaused: true }
  memory.set('pomodoro_running_state', local)
  assert.equal(await resolveLaunchTarget({ getActive }), '/pages/pomodoro/pomodoro')
  for (const key of ['pomodoro_break', 'pomodoro_completion']) {
    memory.set(key, { id: 42 })
    assert.equal(await resolveLaunchTarget({ getActive }), '/pages/home/home')
    memory.delete(key)
  }
  memory.set('user', { id: 12 })
  assert.equal(await resolveLaunchTarget({ getActive }), '/pages/home/home')
  memory.set('user', { id: 11 })
  memory.set('pomodoro_running_state', { ...local, ownerId: undefined })
  assert.equal(await resolveLaunchTarget({ getActive }), '/pages/home/home')
})

test('the 1500ms deadline falls back without waiting for a hanging API', async () => {
  reset()
  const { resolveLaunchTarget } = require(launchPath)
  let deadline, callback
  const realSetTimeout = global.setTimeout, realClearTimeout = global.clearTimeout
  global.setTimeout = (fn, delay) => { callback = fn; deadline = delay; return 123 }
  global.clearTimeout = () => {}
  try {
    const promise = resolveLaunchTarget({ getActive: () => new Promise(() => {}) })
    assert.equal(deadline, 1500)
    callback()
    assert.equal(await promise, '/pages/home/home')
  } finally {
    global.setTimeout = realSetTimeout
    global.clearTimeout = realClearTimeout
  }
})

test('pomodoro snapshot writer stamps the authenticated owner without altering other storage', async () => {
  reset()
  const { writeStorage } = require('../pages/pomodoro/utils/session-storage')
  const local = { sessionId: 44, sessionStartTime: 100, isFreeTimer: true }
  assert.equal(writeStorage(global.wx, 'pomodoro_running_state', local), true)
  assert.equal(memory.get('pomodoro_running_state').ownerId, '11')
  assert.equal(local.ownerId, undefined)
  const { resolveLaunchTarget } = require(launchPath)
  assert.equal(await resolveLaunchTarget({ getActive: async () => { throw Error('offline') } }),
    '/pages/pomodoro/pomodoro')
  writeStorage(global.wx, 'other', local)
  assert.deepEqual(memory.get('other'), local)
})

test('manual pomodoro reconciliation also rejects a preserved snapshot from another user', async () => {
  reset()
  const { readStorage, writeStorage, removeStorage } = require('../pages/pomodoro/utils/session-storage')
  const { buildCachedActiveSession } = require('../pages/pomodoro/utils/cached-session-builder')
  const { createPomodoroActiveSessionReconciler } = require('../pages/pomodoro/utils/active-session-reconciler')
  writeStorage(global.wx, 'pomodoro_running_state', { sessionId: 42, sessionStartTime: 1000 })
  memory.set('user', { id: 12 })
  const reconciler = createPomodoroActiveSessionReconciler({
    safeGetPomodoroStorage: key => readStorage(global.wx, key),
    safeRemovePomodoroStorage: key => removeStorage(global.wx, key),
    buildCachedActiveSession: local => buildCachedActiveSession(local, ms => new Date(ms).toISOString()),
    getActive: async () => { throw Error('offline') },
  })
  assert.equal(await reconciler.fetchActive(), null)
  assert.equal(memory.has('pomodoro_running_state'), false)
})

test('an unauthenticated late onHide cannot overwrite the last owned pomodoro snapshot', () => {
  reset()
  const { readStorage, writeStorage } = require('../pages/pomodoro/utils/session-storage')
  writeStorage(global.wx, 'pomodoro_running_state', { sessionId: 42, sessionStartTime: 1000 })
  memory.delete('user')
  assert.equal(writeStorage(global.wx, 'pomodoro_running_state', { sessionId: 99 }), false)
  assert.equal(readStorage(global.wx, 'pomodoro_running_state').value, null)
  assert.equal(memory.get('pomodoro_running_state').ownerId, '11')
})

test('late API results after account switch or logout cannot redirect to a previous user session', async () => {
  reset()
  const { resolveLaunchTarget } = require(launchPath)
  let finish
  const promise = resolveLaunchTarget({ getActive: () => new Promise(resolve => { finish = resolve }) })
  await Promise.resolve()
  memory.set('user', { id: 12 })
  finish({ status: 'running' })
  assert.equal(await promise, '/pages/home/home')
})

test('explicit paths, share/QR scenes and nonempty queries bypass cold routing', async () => {
  reset()
  const { isDefaultEntry, createLoginResume } = require(launchPath)
  assert.equal(isDefaultEntry({ path: 'pages/login/login', scene: 1001, query: {} }), true)
  for (const entry of [
    { path: 'pages/home/home', scene: 1001 },
    { path: 'pages/login/login', scene: 1007 },
    { path: 'pages/login/login', scene: 1011 },
    ...[1031, 1032, 1044, 1065, 1081, 1124, 1125, 1126, 1160, 1167, 1231]
      .map(scene => ({ path: 'pages/login/login', scene })),
    { path: 'pages/login/login', scene: 1001, query: { target: 'practice' } },
  ]) {
    assert.equal(isDefaultEntry(entry), false)
    const login = createLoginResume({ getLaunchOptionsSync: () => entry })
    assert.equal(await login.resolve(), '/pages/home/home')
  }
})

test('experience-version, search and desktop default entries restore practice and pomodoro', async () => {
  const api = require('../utils/api')
  const originalGet = api.get
  try {
    for (const scene of [1005, 1006, 1017, 1023, 1027]) {
      reset()
      delete require.cache[require.resolve(launchPath)]
      const { createLoginResume, isDefaultEntry } = require(launchPath)
      const entry = { path: 'pages/login/login', scene, query: {} }
      assert.equal(isDefaultEntry(entry), true, String(scene))
      const platform = { getLaunchOptionsSync: () => entry, getEnterOptionsSync: () => entry }
      const store = loadStore()
      store.savePractice({ requestId: 'r', batchToken: 'b', questions: [{ id: 1 }],
        currentIndex: 0, elapsedMs: 1000, answerMap: { 1: 'A' } })
      assert.match(await createLoginResume(platform).resolve(), /practice\?resume=1$/)
      assert.deepEqual(store.readPractice().answerMap, { 1: 'A' })

      store.clearPractice()
      let requests = 0
      api.get = async path => {
        assert.equal(path, '/pomodoro/active')
        requests++
        return { id: 8, status: 'running' }
      }
      const login = createLoginResume(platform)
      assert.equal(await login.resolve(), '/pages/pomodoro/pomodoro')
      assert.equal(requests, 1)
      login.complete()
      assert.equal(await createLoginResume(platform).resolve(), '/pages/home/home')

      assert.equal(isDefaultEntry({ ...entry, query: { target: 'practice' } }), false)
      assert.equal(isDefaultEntry({ ...entry, path: 'pages/dashboard/dashboard' }), false)
    }
  } finally {
    api.get = originalGet
    delete require.cache[require.resolve(launchPath)]
  }
})

test('default cold entry is consumed once and hot login reentry does not resume', async () => {
  reset()
  const { createLoginResume } = require(launchPath), store = loadStore()
  store.markReview(require('../utils/china-time').getChinaDate(0))
  const entry = { path: 'pages/login/login', scene: 1001 }
  const platform = { getLaunchOptionsSync: () => entry, getEnterOptionsSync: () => entry }
  const cold = createLoginResume(platform)
  assert.match(await cold.resolve(), /review-today/)
  platform.getEnterOptionsSync = () => ({ path: 'pages/dashboard/index', scene: 1007 })
  assert.equal(await cold.resolve(), null)
  platform.getEnterOptionsSync = () => entry
  assert.equal(await cold.resolve(), '/pages/home/home')
  assert.equal(await createLoginResume(platform).resolve(), '/pages/home/home')
  cold.complete()
  assert.equal(await createLoginResume(platform).resolve(), '/pages/home/home')
})

test('auth invalidation re-login can resume the preserved session once', async () => {
  reset()
  const { createLoginResume } = require(launchPath)
  const store = loadStore()
  const apiAuth = require('../utils/api-auth')
  store.markReview(require('../utils/china-time').getChinaDate(0))
  const entry = { path: 'pages/login/login', scene: 1001 }
  const platform = { getLaunchOptionsSync: () => entry, getEnterOptionsSync: () => entry }

  createLoginResume(platform).complete()
  const before = apiAuth.getAuthInvalidationSeq()
  apiAuth.resetRedirecting()
  await assert.rejects(apiAuth.forceRefreshToken())
  assert.equal(apiAuth.getAuthInvalidationSeq(), before + 1)

  memory.set('user', { id: 11 })
  memory.set('token', 'token')
  const reentry = createLoginResume(platform)
  assert.match(await reentry.resolve(), /review-today/)
  reentry.complete()
  assert.equal(await createLoginResume(platform).resolve(), '/pages/home/home')
  apiAuth.resetRedirecting()
})

test('automatic auth invalidation can preserve owned recovery state; explicit logout still clears it', () => {
  reset()
  const entries = {
    'practice_resume_v1:11': { owner: '11' },
    'study_active_v1:11': { owner: '11' },
    'practice_pending_submission_v1:11': { submission: {} },
    'review_today_draft_v1:11:2026-11-05': { answers: {} },
    pomodoro_running_state: { ownerId: '11', sessionId: 1 },
  }
  for (const [key, value] of Object.entries(entries)) memory.set(key, value)
  global.wx.getStorageInfoSync = () => ({ keys: [...memory.keys()] })
  storage.clearSession({ preserveLaunchResume: true })
  assert.equal(memory.has('token'), false)
  assert.equal(memory.has('user'), false)
  for (const key of Object.keys(entries)) assert.equal(memory.has(key), true, key)
  storage.clearSession()
  for (const key of Object.keys(entries)) assert.equal(memory.has(key), false, key)
})
