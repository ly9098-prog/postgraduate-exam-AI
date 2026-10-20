/**
 * Regression tests for Pomodoro resume latency / dial rendering.
 * Usage: node scripts/test-pomodoro-resume-latency.js
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

let passed = 0
let failed = 0
function t(name, fn) {
  try {
    fn()
    passed++
    console.log('  ✓ ' + name)
  } catch (e) {
    failed++
    console.error('  ✗ ' + name + ' - ' + e.message)
  }
}

const root = path.resolve(__dirname, '..')
const jsPath = path.join(root, 'pages/pomodoro/pomodoro.js')
const cssPath = path.join(root, 'pages/pomodoro/pomodoro.wxss')
const src = fs.readFileSync(jsPath, 'utf8')
const css = fs.readFileSync(cssPath, 'utf8')

function extractMethod(source, name) {
  const re = new RegExp('(?:^|\\n)  (?:async )?' + name.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&') + '\\([^\\n]*\\) \\{')
  const m = source.match(re)
  if (!m) return ''
  const start = m.index + (m[0][0] === '\n' ? 1 : 0)
  let i = source.indexOf('{', start) + 1
  let depth = 1
  let state = 'code'
  let quote = ''
  let escaped = false
  while (i < source.length && depth > 0) {
    const ch = source[i]
    const next = source[i + 1]
    if (state === 'line') {
      if (ch === '\n') state = 'code'
    } else if (state === 'block') {
      if (ch === '*' && next === '/') { state = 'code'; i++ }
    } else if (state === 'string') {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === quote) state = 'code'
    } else {
      if (ch === '/' && next === '/') { state = 'line'; i++ }
      else if (ch === '/' && next === '*') { state = 'block'; i++ }
      else if (ch === "'" || ch === '"' || ch === '`') { state = 'string'; quote = ch }
      else if (ch === '{') depth++
      else if (ch === '}') depth--
    }
    i++
  }
  return source.slice(start, i)
}

console.log('\n--- Static recovery ordering ---')
const onShow = extractMethod(src, 'onShow')
t('onShow delegates cached and server recovery to the tested recovery module', () => {
  assert.ok(onShow.includes('await this._recoverActiveSession(pendingSync, activeSyncSeq)'))
  const recovery = extractMethod(src, '_recoverActiveSession')
  assert.ok(recovery.includes('readCached: () => this._getCachedActiveSession()'))
  assert.ok(recovery.includes('fetchActive: () => this._fetchActiveSession()'))
})
t('page entrance is enabled before network reconciliation', () => {
  const enteredIdx = onShow.indexOf('this.setData({ pageEntered: true })')
  const fetchIdx = onShow.indexOf('await this._recoverActiveSession(pendingSync, activeSyncSeq)')
  assert.ok(enteredIdx >= 0 && enteredIdx < fetchIdx)
})
t('server recovery can clear stale local state through the page adapter', () => {
  const recovery = extractMethod(src, '_recoverActiveSession')
  assert.ok(recovery.includes('isRunning: () => this.data.phase === PHASE.RUNNING'))
  assert.ok(recovery.includes('resetIdle: () => this._resetToIdle()'))
})

console.log('\n--- Countdown background resume ---')
const lightSync = extractMethod(src, '_syncActiveSessionLight')
t('light sync restarts normal countdown after onHide cleared timer', () => {
  assert.ok(lightSync.includes('this._startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })'))
})
t('light sync derives remaining time from wall clock', () => {
  assert.ok(lightSync.includes('now - this._timerState.sessionStartTime - totalPausedMs'))
  assert.ok(lightSync.includes('totalSec * 1000 - elapsedMs'))
})
t('free timer interval is restarted only while running', () => {
  assert.ok(lightSync.includes('if (!this.data.isPaused)'))
  assert.ok(lightSync.includes('this._startFreeTimerInterval()'))
})

console.log('\n--- Canvas first paint and refresh ---')
const initCanvas = extractMethod(src, '_initCanvas')
const drawRing = extractMethod(src, 'drawRing')
t('canvas rebuild clears previous draw throttle state', () => {
  assert.ok(initCanvas.includes('this._lastDrawnProgress = undefined'))
  assert.ok(initCanvas.includes('this._lastDrawnIsBreak = undefined'))
  assert.ok(initCanvas.includes('this._lastDrawnAt = 0'))
})
t('ring throttle is duration-aware instead of fixed 1/360 only', () => {
  assert.ok(drawRing.includes('0.8 / totalSec'))
})
t('ring is forced to refresh within about one second', () => {
  assert.ok(drawRing.includes('sinceLastDraw < 1000'))
  assert.ok(drawRing.includes('this._lastDrawnAt = now'))
})
t('removed artificial 50/100/200ms drawRing startup delays', () => {
  assert.ok(!/setTimeout\([^\n]*drawRing[^\n]*,\s*(50|100|200)\s*\)/.test(src))
})

console.log('\n--- Visual entrance latency ---')
t('page entrance animation <= 0.2s', () => {
  const m = css.match(/animation:\s*page-enter\s+([0-9.]+)s/)
  assert.ok(m)
  assert.ok(Number(m[1]) <= 0.2, 'page animation=' + m[1] + 's')
})
t('timer dial entrance animation <= 0.2s', () => {
  const m = css.match(/animation:\s*timer-in\s+([0-9.]+)s/)
  assert.ok(m)
  assert.ok(Number(m[1]) <= 0.2, 'timer animation=' + m[1] + 's')
})

console.log('\n==============================')
console.log('Passed:', passed, ' Failed:', failed)
console.log('==============================\n')
if (failed) process.exit(1)
