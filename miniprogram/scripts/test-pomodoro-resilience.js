/**
 * Regression checks for Pomodoro lifecycle/network resilience.
 * Usage: node scripts/test-pomodoro-resilience.js
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

let passed = 0
let failed = 0
function t(name, fn) {
  try { fn(); passed++; console.log('  ✓ ' + name) }
  catch (e) { failed++; console.error('  ✗ ' + name + ' - ' + e.message) }
}

const src = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
function method(name) {
  const startToken = `  ${name}(`
  const asyncToken = `  async ${name}(`
  let start = src.indexOf(startToken)
  if (start < 0) start = src.indexOf(asyncToken)
  assert.ok(start >= 0, 'missing method ' + name)
  let brace = src.indexOf('{', start)
  let depth = 0, quote = '', escaped = false, line = false, block = false
  for (let i = brace; i < src.length; i++) {
    const ch = src[i], nx = src[i + 1]
    if (line) { if (ch === '\n') line = false; continue }
    if (block) { if (ch === '*' && nx === '/') { block = false; i++ } continue }
    if (quote) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === quote) quote = ''
      continue
    }
    if (ch === '/' && nx === '/') { line = true; i++; continue }
    if (ch === '/' && nx === '*') { block = true; i++; continue }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue }
    if (ch === '{') depth++
    if (ch === '}' && --depth === 0) return src.slice(start, i + 1)
  }
  return ''
}

console.log('\n--- Lifecycle race guards ---')
const onShow = method('onShow')
const onHide = method('onHide')
t('onShow versions active reconciliation', () => assert.ok(onShow.includes('activeSyncSeq')))
t('onShow ignores a response after the page is hidden', () => assert.ok(onShow.includes('!this._pageVisible || activeSyncSeq !== this._activeSyncSeq')))
t('onHide invalidates in-flight reconciliation', () => assert.ok(onHide.includes('this._activeSyncSeq = (this._activeSyncSeq || 0) + 1')))

console.log('\n--- Free cold restore ---')
const restoreFree = method('_restoreFreeSession')
t('free restore seeds sessionStartTime before elapsed helper', () => {
  const seed = restoreFree.indexOf('this._timerState.sessionStartTime = startTime')
  const calc = restoreFree.indexOf('this._getFreeElapsedMs()')
  assert.ok(seed >= 0 && calc >= 0 && seed < calc)
})
t('free restore caps display at five hours', () => assert.ok(restoreFree.includes('FREE_TIMER_MAX_MS')))

console.log('\n--- Optimistic pause/resume ---')
for (const name of ['_pauseSession', '_pauseFreeTimer']) {
  const m = method(name)
  t(name + ' updates paused UI before network drain', () => {
    assert.ok(m.indexOf('isPaused: true') >= 0)
    assert.ok(m.indexOf('isPaused: true') < m.indexOf('_retryPendingPomodoroSync'))
  })
  t(name + ' persists a pending pause sync', () => assert.ok(m.includes("_setPendingPomodoroSync('pause'")))
  t(name + ' releases actionLoading before network completes', () => {
    assert.ok(m.indexOf('actionLoading: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
}
for (const name of ['_resumeSession', '_resumeFreeTimer']) {
  const m = method(name)
  t(name + ' updates running UI before network drain', () => {
    assert.ok(m.indexOf('isPaused: false') >= 0)
    assert.ok(m.indexOf('isPaused: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
  t(name + ' persists a pending resume sync', () => assert.ok(m.includes("_setPendingPomodoroSync('resume'")))
  t(name + ' releases actionLoading before network completes', () => {
    assert.ok(m.indexOf('actionLoading: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
}

console.log('\n--- Pending completion reliability ---')
const retry = method('_retryPendingPomodoroSync')
const complete = method('_completePomodoroWithRetry')
const queueReader = method('_getPendingPomodoroSyncQueue')
t('pending network actions survive beyond the 6h running-state TTL', () => {
  assert.ok(src.includes('POMODORO_PENDING_SYNC_TTL_MS = 7 * 24 * 60 * 60 * 1000'))
})
t('pending sync storage is an ordered queue and migrates legacy single-slot data', () => {
  assert.ok(queueReader.includes('Array.isArray(raw)'))
  assert.ok(queueReader.includes('list = [raw]'))
  assert.ok(method('_setPendingPomodoroSync').includes('queue.push(pending)'))
})
t('legacy completeAfter is migrated into a terminal queue item', () => {
  assert.ok(queueReader.includes('raw.completeAfter'))
  assert.ok(queueReader.includes("action: 'complete'"))
})
t('queued mutations preserve client event timestamps for offline replay', () => {
  assert.ok(method('_setPendingPomodoroSync').includes('clientActionAt'))
  assert.ok(retry.includes('client_action_at'))
})
t('pending queue drains strictly from the head', () => {
  assert.ok(retry.includes('const pending = queue[0]'))
  assert.ok(retry.includes('this._clearPendingPomodoroSync(pending)'))
})
t('completion is queued after earlier pause/resume actions', () => {
  assert.ok(complete.includes("_setPendingPomodoroSync('complete', sessionId, clientActionAt)"))
  assert.ok(complete.includes('_retryPendingPomodoroSync'))
})
t('automatic countdown completion uses retryable completion', () => assert.ok(method('_onWorkComplete').includes('_completePomodoroWithRetry')))
t('free completion uses retryable completion', () => assert.ok(method('_completeFreeTimerSession').includes('_completePomodoroWithRetry')))

console.log('\n--- Start lifecycle guards ---')
const startSession = method('startSession')
const startFree = method('_startFreeSession')
t('start ceremony uses a lifecycle generation', () => assert.ok(startSession.includes('_startRequestSeq')))
t('start ceremony aborts before POST after page hide', () => {
  assert.ok(startSession.includes('!this._pageVisible || startSeq !== this._startRequestSeq'))
  assert.ok(startSession.indexOf('!this._pageVisible || startSeq !== this._startRequestSeq') < startSession.indexOf("api.post('/pomodoro/start'"))
})
t('late start response is queued for interrupt instead of becoming a ghost session', () => {
  assert.ok(startSession.includes("_setPendingPomodoroSync('interrupt', session.id)"))
  assert.ok(startFree.includes("_setPendingPomodoroSync('interrupt', session.id)"))
})
t('onHide invalidates in-flight start requests', () => assert.ok(onHide.includes('_startRequestSeq = (this._startRequestSeq || 0) + 1')))

console.log('\n--- Break restore ---')
const startBreak = method('_startBreak')
const restoreBreak = method('_restoreBreak')
t('break restore preserves original start time and total duration', () => {
  assert.ok(src.includes('breakStartTime + totalMs - Date.now()'))
  assert.ok(restoreBreak.includes('startTime: Number(saved.startTime)'))
  assert.ok(restoreBreak.includes('Number(saved.totalSec)'))
})
t('break progress is based on original total instead of rebasing to remaining', () => {
  assert.ok(src.includes('this._timerState.progress = remainingMs / totalMs'))
  assert.ok(!restoreBreak.includes('_startBreak(remaining'))
})
t('onShow restores break before pending network synchronization', () => {
  assert.ok(onShow.indexOf('restoredBreak = this._restoreBreak()') < onShow.indexOf('await this._retryPendingPomodoroSync()'))
})

console.log('\n--- Canvas reuse ---')
const startTimer = method('_startTimer')
const initCanvas = method('_initCanvas')
t('timer restart can reuse an existing/in-flight canvas', () => assert.ok(src.includes('this._initCanvas(!options.reuseCanvas)')))
t('canvas init suppresses duplicate in-flight initialization', () => assert.ok(initCanvas.includes('this._canvasInitPending')))

console.log('\n--- Free end-confirm ring recovery ---')
const cancelEndConfirm = method('cancelEndConfirm')
const redrawFreeRing = method('_redrawFreeRingAfterOverlay')
t('free ring recovery forces a fresh canvas after overlay dismissal', () => {
  assert.ok(redrawFreeRing.includes('this._timerState.progress = 1'))
  assert.ok(redrawFreeRing.includes('this._initCanvas(true)'))
  assert.ok(redrawFreeRing.includes('this.drawRing(0, false)'))
})
t('free end-confirm cancel redraws the ring in all recovery branches', () => {
  const hits = cancelEndConfirm.match(/this\._redrawFreeRingAfterOverlay\(\)/g) || []
  assert.ok(hits.length >= 3, 'expected redraw in fallback, paused and running branches')
})
t('free ring redraw waits until the confirm overlay is gone', () => {
  assert.ok(redrawFreeRing.includes('wx.nextTick'))
  assert.ok(redrawFreeRing.includes('this.data.showEndConfirm'))
})

console.log('\n--- Canvas re-entry positioning ---')
const wxml = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.wxml'), 'utf8')
const wxss = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.wxss'), 'utf8')
t('native canvas is truly hidden while end-confirm overlay is visible', () => {
  // Native Canvas can sit above cover-view on real devices even when CSS opacity is 0.
  // The confirm overlay must therefore use the native `hidden` switch; cancel paths
  // already force a stable-layout canvas rebuild before revealing it again.
  assert.ok(wxml.includes('hidden="{{showEndConfirm || !ringCanvasVisible}}"'))
})

t('countdown cancel rebuilds canvas after native hidden is removed', () => {
  const countdown = cancelEndConfirm.slice(cancelEndConfirm.indexOf("if (mode === 'countdown-interrupt'"), cancelEndConfirm.indexOf("if (mode === 'free-complete')"))
  const initHits = countdown.match(/this\._initCanvas\(true\)/g) || []
  const drawHits = countdown.match(/this\.drawRing\(/g) || []
  assert.ok(initHits.length >= 2, 'expected paused and running countdown cancel branches to rebuild canvas')
  assert.ok(drawHits.length >= 2, 'expected paused and running countdown cancel branches to redraw ring')
})
t('native canvas uses normal flow instead of absolute positioning', () => {
  const block = wxss.slice(wxss.indexOf('.ring-canvas {'), wxss.indexOf('.ring-canvas-ready'))
  assert.ok(block.includes('position: relative'))
  assert.ok(!block.includes('position: absolute'))
})
t('ring wrapper fills the stage without absolute positioning', () => {
  const start = wxss.indexOf('.ring-wrapper {')
  const end = wxss.indexOf('}', start)
  const block = wxss.slice(start, end + 1)
  assert.ok(block.includes('position: relative'))
  assert.ok(block.includes('width: 100%'))
  assert.ok(block.includes('height: 100%'))
})
t('canvas init ignores stale selector callbacks by generation', () => {
  assert.ok(initCanvas.includes('_canvasInitSeq'))
  assert.ok(method('_scheduleCanvasInit').includes('initSeq !== this._canvasInitSeq'))
})
t('canvas waits for a stable stage-aligned layout before binding context', () => {
  const m = method('_scheduleCanvasInit')
  assert.ok(m.includes("select('.ring-stage').boundingClientRect()"))
  assert.ok(m.includes('stageAligned'))
  assert.ok(m.includes('stable'))
})
t('canvas is revealed only after a successful draw', () => {
  assert.ok(src.includes('ringCanvasPaintReady: false'))
  assert.ok(method('drawRing').includes('this.setData({ ringCanvasPaintReady: true })'))
})
t('reset-to-idle invalidates stale canvas init callbacks', () => {
  assert.ok(method('_resetToIdle').includes('this._canvasInitSeq = (this._canvasInitSeq || 0) + 1'))
})
t('free light-sync rebuilds canvas if page-hide interrupted initialization', () => {
  const m = method('_syncActiveSessionLight')
  assert.ok(m.includes('if (!this._canvasReady || !this._ctx)'))
  assert.ok(m.includes('this.drawRing(0, false)'))
})
t('hide always discards native canvas context', () => {
  assert.ok(onHide.includes('this._canvasReady = false'))
  assert.ok(onHide.includes('this._ctx = null'))
  assert.ok(!onHide.includes('if (this._canvasInitPending)'))
})
t('unload invalidates in-flight canvas initialization', () => {
  assert.ok(method('onUnload').includes('this._canvasInitSeq = (this._canvasInitSeq || 0) + 1'))
})

console.log('\n==============================')
console.log('Passed:', passed, ' Failed:', failed)
console.log('==============================\n')
if (failed) process.exit(1)
