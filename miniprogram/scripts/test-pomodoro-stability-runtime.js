/**
 * Runtime-oriented regression checks for Pomodoro long-term stability guards.
 * Executes the real Page methods inside a small WeChat API sandbox instead of
 * only searching source strings.
 * Usage: node scripts/test-pomodoro-stability-runtime.js
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const source = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
const storage = new Map()
const toasts = []
let failSetStorageKey = ''
let failRemoveStorageKey = ''
let failReadStorageKey = ''
let nowMs = Date.parse('2026-08-23T08:00:00Z')
let scheduledDelay = null
let capturedPage = null

const api = {
  now: () => nowMs,
  get: async () => null,
  post: async () => ({ status: 'running' }),
  createClientStartId: () => 'runtime-test-start-id',
}

const wx = {
  getStorageSync(key) {
    if (key === failReadStorageKey) throw new Error('simulated storage read failure')
    return storage.get(key)
  },
  setStorageSync(key, value) {
    if (key === failSetStorageKey) throw new Error('simulated storage quota failure')
    storage.set(key, value)
  },
  removeStorageSync(key) {
    if (key === failRemoveStorageKey) throw new Error('simulated storage remove failure')
    storage.delete(key)
  },
  showToast(opts) { toasts.push(opts) },
  nextTick(fn) { if (fn) fn() },
  vibrateLong() {},
  onNetworkStatusChange() {},
  offNetworkStatusChange() {},
  setNavigationBarColor() {},
  setBackgroundColor() {},
  setBackgroundTextStyle() {},
}

const sandbox = {
  console,
  wx,
  Page(definition) { capturedPage = definition },
  require(request) {
    if (request === '../../utils/api') return api
    if (request === '../../config') return {}
    if (request === '../../utils/route-params') return { safeDecodeURIComponent: v => v }
    if (request === './utils/route-params') return { safeDecodeURIComponent: v => v }
    if (request === './utils/subject-scope') return { filter408SubjectTree: value => value }
    if (request === '../../utils/pomodoro-theme' || request === './utils/pomodoro-theme') {
      return {
        getTheme: () => 'light',
        normalizeTheme: v => v || 'light',
        applyNativeTheme() {},
        setTheme() {},
      }
    }
    if (request === '../../utils/china-time') {
      return {
        parseServerUtc: value => Date.parse(value),
        getChinaWallParts: () => ({}),
        getChinaDayStartUtcMs: () => 0,
      }
    }
    if (request === '../../utils/storage') {
      return {
        pomodoroTaskTypes: {
          DEFAULT_TYPE: 'new_questions',
          label(type) { return type === 'new_questions' ? '新题' : type },
          getSelected() { return 'new_questions' },
          setSelected(type) { return type },
          recordSession() {},
          typeForSession() { return '' },
          labelForSession() { return '' },
        },
      }
    }
    throw new Error('unexpected require: ' + request)
  },
  setTimeout(fn, delay) {
    scheduledDelay = delay
    return { fn, delay }
  },
  clearTimeout() {},
}
vm.runInNewContext(source, sandbox, { filename: 'pomodoro.js' })
assert.ok(capturedPage, 'Page definition was not captured')

function createPage() {
  const page = Object.assign({}, capturedPage)
  page.data = JSON.parse(JSON.stringify(capturedPage.data))
  page._timerState = page._createTimerState()
  page.setData = function setData(patch, callback) {
    Object.assign(this.data, patch)
    if (callback) callback()
  }
  page._clearTimer = () => { page._clearTimerCalls = (page._clearTimerCalls || 0) + 1 }
  page._initCanvas = () => {}
  page.drawRing = () => {}
  page._updateComputedFields = () => {}
  return page
}

let passed = 0
let failed = 0
async function test(name, fn) {
  try {
    await fn()
    passed++
    console.log('  ✓ ' + name)
  } catch (error) {
    failed++
    console.error('  ✗ ' + name + ' - ' + error.message)
  }
}

;(async () => {
  console.log('\n--- Pomodoro runtime stability ---')

  await test('pause stays fail-closed when pending intent cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.phase = 'running'
    page.data.isPaused = false
    page.data.actionLoading = false
    page._timerState.sessionId = 11
    page._timerState.sessionStartTime = nowMs - 30_000
    failSetStorageKey = 'pomodoro_pending_sync'
    await page._pauseSession()
    failSetStorageKey = ''
    assert.strictEqual(page.data.isPaused, false)
    assert.strictEqual(page._clearTimerCalls || 0, 0)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('resume stays paused when pending intent cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.phase = 'running'
    page.data.isPaused = true
    page.data.actionLoading = false
    page.data.workDuration = 25
    page.data.selectedPreset = 'standard'
    page._timerState.sessionId = 12
    page._timerState.sessionStartTime = nowMs - 60_000
    page._timerState.pauseStartTime = nowMs - 5_000
    storage.set('pomodoro_pause', { sessionId: 12, totalPausedMs: 0, pauseStartTime: nowMs - 5_000 })
    failSetStorageKey = 'pomodoro_pending_sync'
    await page._resumeSession()
    failSetStorageKey = ''
    assert.strictEqual(page.data.isPaused, true)
    assert.ok(storage.get('pomodoro_pause'))
  })

  await test('queue safety valve rejects toggles but preserves terminal capacity', async () => {
    storage.clear()
    const page = createPage()
    const queue = []
    for (let i = 0; i < 196; i++) {
      queue.push({
        action: i % 2 ? 'resume' : 'pause',
        sessionId: 21,
        savedAt: nowMs + i + 1,
        clientActionAt: nowMs + i + 1,
        nonce: 'n' + i,
      })
    }
    storage.set('pomodoro_pending_sync', queue)
    assert.strictEqual(page._setPendingPomodoroSync('pause', 21, nowMs + 500), null)
    const terminal = page._setPendingPomodoroSync('complete', 21, nowMs + 501)
    assert.ok(terminal)
    assert.strictEqual(storage.get('pomodoro_pending_sync').length, 197)
  })

  await test('503 schedules the first bounded retry at 2 seconds', async () => {
    storage.clear(); scheduledDelay = null
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'pause', sessionId: 31, savedAt: nowMs, clientActionAt: nowMs, nonce: 'retry-1',
    }])
    page._schedulePendingPomodoroSyncRetry({ statusCode: 503 })
    assert.strictEqual(scheduledDelay, 2000)
    assert.strictEqual(page._pendingSyncRetryAttempt, 1)
  })

  await test('cold restore remains paused across device-clock rollback', async () => {
    storage.clear()
    const page = createPage()
    storage.set('pomodoro_pause', {
      sessionId: 41,
      totalPausedMs: 0,
      pauseStartTime: nowMs + 60_000,
    })
    page._restoreSession({
      id: 41,
      preset: 'standard',
      work_duration: 25,
      break_duration: 5,
      start_time: new Date(nowMs - 30_000).toISOString(),
      total_paused_sec: 0,
      subject_id: null,
      subject_code: '',
      subject_name: '未分类',
    })
    assert.strictEqual(page.data.isPaused, true)
    assert.ok(page._timerState.totalPausedMs >= 0)
  })

  await test('pending storage read failure is not treated as an empty queue', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    const original = [{
      action: 'pause', sessionId: 51, savedAt: nowMs, clientActionAt: nowMs, nonce: 'keep-me',
    }]
    storage.set('pomodoro_pending_sync', original)
    failReadStorageKey = 'pomodoro_pending_sync'
    assert.strictEqual(page._getPendingPomodoroSyncQueue(), null)
    assert.strictEqual(page._setPendingPomodoroSync('resume', 51, nowMs + 1000), null)
    failReadStorageKey = ''
    assert.deepStrictEqual(storage.get('pomodoro_pending_sync'), original)
  })

  await test('onShow stops reconciliation while pending storage is unreadable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._syncThemeFromStorage = () => {}
    page._pageVisible = false
    let reconcileCalls = 0
    page._reconcileUnknownStartAttempt = async () => { reconcileCalls++; return 'none' }
    failReadStorageKey = 'pomodoro_pending_sync'
    await page.onShow()
    failReadStorageKey = ''
    assert.strictEqual(reconcileCalls, 0)
    assert.strictEqual(page.data.pageEntered, true)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('active-session recovery fails closed before any server fetch when local snapshot is unreadable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    let getCount = 0
    api.get = async () => { getCount++; return null }
    failReadStorageKey = 'pomodoro_running_state'
    const cached = page._getCachedActiveSession()
    const active = await page._fetchActiveSession()
    failReadStorageKey = ''
    api.get = async () => null
    assert.ok(cached && cached.storageUnreadable)
    assert.ok(active && active.storageUnreadable)
    assert.strictEqual(getCount, 0)
  })

  await test('cold restore does not treat unreadable pause adjustment as zero', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    storage.set('pomodoro_pause', {
      sessionId: 52,
      totalPausedMs: 1000,
      pauseStartTime: nowMs - 1000,
    })
    failReadStorageKey = 'pomodoro_pause_adjustment'
    const restored = page._restoreSession({
      id: 52,
      preset: 'standard',
      work_duration: 25,
      break_duration: 5,
      start_time: new Date(nowMs - 30_000).toISOString(),
      total_paused_sec: 0,
      subject_id: null,
      subject_code: '',
      subject_name: '未分类',
    })
    failReadStorageKey = ''
    assert.strictEqual(restored, false)
    assert.strictEqual(page.data.phase, 'idle')
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('terminal conflict storage failure keeps the pending terminal mutation durable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    storage.set('pomodoro_pending_sync', [{
      action: 'complete', sessionId: 53, savedAt: nowMs, clientActionAt: nowMs, nonce: 'terminal-keep',
    }])
    api.post = async () => ({ status: 'interrupted' })
    failSetStorageKey = 'pomodoro_terminal_conflict'
    const synced = await page._retryPendingPomodoroSync()
    failSetStorageKey = ''
    api.post = async () => ({ status: 'running' })
    assert.strictEqual(synced, false)
    const queue = storage.get('pomodoro_pending_sync')
    assert.ok(Array.isArray(queue) && queue.length === 1)
    assert.strictEqual(queue[0].nonce, 'terminal-keep')
    assert.strictEqual(storage.has('pomodoro_terminal_conflict'), false)
  })

  await test('terminal conflict is not acknowledged when durable cleanup cannot finish', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page.data.showCelebration = true
    const conflict = { sessionId: 54, requestedAction: 'complete', serverStatus: 'interrupted', savedAt: nowMs }
    storage.set('pomodoro_terminal_conflict', conflict)
    storage.set('pomodoro_completion', { sessionId: 54, breakSec: 300 })
    const peeked = page._consumePomodoroTerminalConflict(54, 'complete')
    assert.strictEqual(peeked.sessionId, 54)
    failRemoveStorageKey = 'pomodoro_terminal_conflict'
    const handled = page._handlePomodoroTerminalConflict(54, peeked)
    failRemoveStorageKey = ''
    assert.strictEqual(handled, false)
    assert.ok(storage.get('pomodoro_terminal_conflict'))
    assert.strictEqual(page.data.showCelebration, true)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('start is never POSTed before unknown-start recovery data is durable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    page._startRequestSeq = 1
    let postCount = 0
    api.post = async () => { postCount++; return { id: 61, status: 'running', client_start_id: 'runtime-test-start-id' } }
    failSetStorageKey = 'pomodoro_unknown_start'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 1)
    failSetStorageKey = ''
    assert.strictEqual(result.handled, true)
    assert.strictEqual(postCount, 0)
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('late start response keeps a cancel credential when pending storage is unavailable', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = false
    page._startRequestSeq = 2
    api.post = async (url, body) => ({
      id: 62,
      status: 'running',
      client_start_id: body.client_start_id,
      start_time: new Date(nowMs - 1000).toISOString(),
    })
    failSetStorageKey = 'pomodoro_pending_sync'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 1)
    failSetStorageKey = ''
    assert.strictEqual(result.handled, true)
    const marker = storage.get('pomodoro_unknown_start')
    assert.ok(marker && marker.cancelIfFound)
    assert.ok(Number(marker.cancelAt) > 0)
    assert.strictEqual(storage.has('pomodoro_pending_sync'), false)
  })

  await test('successful start is not accepted while unknown-start cleanup cannot be persisted', async () => {
    storage.clear(); toasts.length = 0
    const page = createPage()
    page._pageVisible = true
    page._startRequestSeq = 3
    page.data.phase = 'ceremony'
    api.post = async (url, body) => ({
      id: 63,
      status: 'running',
      client_start_id: body.client_start_id,
      start_time: new Date(nowMs).toISOString(),
    })
    failRemoveStorageKey = 'pomodoro_unknown_start'
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: 1, chapter_id: null, preset: 'standard', work_duration: 25, break_duration: 5,
    }, 3)
    failRemoveStorageKey = ''
    assert.strictEqual(result.handled, true)
    assert.strictEqual(page.data.phase, 'idle')
    assert.ok(storage.get('pomodoro_unknown_start'))
    assert.ok(toasts.some(item => String(item.title).includes('本地存储异常')))
  })

  await test('slower older stats response cannot overwrite newer totals', async () => {
    storage.clear()
    const page = createPage()
    const pending = []
    api.get = () => new Promise(resolve => pending.push(resolve))
    const first = page.loadTodayStats()
    const second = page.loadTodayStats()
    pending[1]({ today_sessions: 8, today_duration_sec: 3600 })
    await second
    pending[0]({ today_sessions: 7, today_duration_sec: 3000 })
    await first
    assert.strictEqual(page.data.todaySessions, 8)
    assert.strictEqual(page.data.todayDurationText, '1时0分')
    api.get = async () => null
  })

  console.log('\n==============================')
  console.log('Passed:', passed, ' Failed:', failed)
  console.log('==============================\n')
  if (failed) process.exit(1)
})()
