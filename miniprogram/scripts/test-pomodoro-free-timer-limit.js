/**
 * test-pomodoro-free-timer-limit.js
 *
 * Regression test for 5-hour maximum duration on the free timer.
 *
 * Verifies:
 *   1. FREE_TIMER_MAX_MS constant = 5h exactly
 *   2. Display is capped at 05:00:00
 *   3. Auto-finish triggers at >= 5h
 *   4. Shared _completeFreeTimerSession for both manual and auto end
 *   5. Reentry protection via _freeTimerFinalizing
 *   6. Pause isolation (paused time not counted)
 *   7. onUnload / onHide lifecycle cleanup
 *   8. Mode info text updated from "无时长限制" to "最长5小时"
 *   9. >= used for limit check (not ===)
 *  10. UI tick checks limit via _checkFreeTimerLimitAndAutoEnd
 */

/* eslint-disable no-console */
const assert = require('assert')
const path = require('path')
const fs = require('fs')
const { formatElapsedSec } = require('../pages/pomodoro/utils/timer-math')

var testsPassed = 0
var testsFailed = 0

function t(desc, fn) {
  try {
    fn()
    testsPassed++
    console.log('  ✓', desc)
  } catch (e) {
    testsFailed++
    console.error('  ✗', desc, '-', e.message)
  }
}

// ══════════════════════════════════════════════════════════════════
// 1. Source text — constants
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 1. Source code constants ---')

var js = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
var pageSupportSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/pomodoro-page-support.js'), 'utf8')
var recoveryAdapterSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/pomodoro-recovery-page-adapter.js'), 'utf8')
var sessionControlAdapterSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/pomodoro-session-control-page-adapter.js'), 'utf8')
var confirmEndFreeTimerCtrlSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/confirm-end-free-timer-controller.js'), 'utf8')
var freeTimerLimitCtrlSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/free-timer-limit-controller.js'), 'utf8')
var resetToIdleCtrlSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/reset-to-idle-controller.js'), 'utf8')
var freeRestoreSrc = fs.readFileSync(
  path.join(__dirname, '../pages/pomodoro/utils/free-session-restore-controller.js'),
  'utf8'
)
var activeSyncSrc = fs.readFileSync(
  path.join(__dirname, '../pages/pomodoro/utils/active-sync-controller.js'),
  'utf8'
)

t('FREE_TIMER_MAX_MS is defined', function () {
  assert.ok(pageSupportSrc.indexOf('FREE_TIMER_MAX_MS') >= 0)
})

t('FREE_TIMER_MAX_MS equals exactly 5 hours in ms', function () {
  // Extract the constant value
  var match = pageSupportSrc.match(/FREE_TIMER_MAX_MS\s*=\s*(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)/)
  if (match) {
    var val = parseInt(match[1], 10) * parseInt(match[2], 10) * parseInt(match[3], 10) * parseInt(match[4], 10)
    assert.strictEqual(val, 18000000, '5*60*60*1000 = 18000000')
  } else {
    // Try a direct number
    var directMatch = pageSupportSrc.match(/FREE_TIMER_MAX_MS\s*=\s*(\d+)/)
    if (directMatch) {
      assert.strictEqual(parseInt(directMatch[1], 10), 18000000)
    } else {
      assert.fail('Cannot parse FREE_TIMER_MAX_MS')
    }
  }
})

t('Limit check uses >= not ===', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.maxMs()') >= 0,
    'limit controller must read the injected max')
  assert.ok(activeSyncSrc.indexOf('elapsedMs >= options.maxMs') >= 0,
    'light sync must use >= for the free timer cap')
})

t('_freeTimerFinalizing field exists', function () {
  assert.ok(js.indexOf('_freeTimerFinalizing') >= 0)
})

t('_autoFinishFreeTimer method exists', function () {
  assert.ok(js.indexOf('_autoFinishFreeTimer(') >= 0)
})

t('_completeFreeTimerSession method exists', function () {
  assert.ok(js.indexOf('_completeFreeTimerSession(') >= 0)
})

t('_checkFreeTimerLimitAndAutoEnd method exists', function () {
  assert.ok(js.indexOf('_checkFreeTimerLimitAndAutoEnd(') >= 0)
})

t('_completeFreeTimerSession is called from _confirmEndFreeTimer', function () {
  assert.ok(confirmEndFreeTimerCtrlSrc.indexOf('completeFreeTimerSession') >= 0,
    '_confirmEndFreeTimer should use shared _completeFreeTimerSession')
})

t('_autoFinishFreeTimer uses _completeFreeTimerSession', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('await complete(options)') >= 0,
    '_autoFinishFreeTimer should use shared _completeFreeTimerSession')
})

t('_autoFinishFreeTimer checks _freeTimerFinalizing reentry guard', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('if (options.finalizing()) return') >= 0,
    'auto finish must have reentry protection')
})

t('_checkFreeTimerLimitAndAutoEnd checks _freeTimerFinalizing', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.finalizing()') >= 0,
    'limit check must also guard on _freeTimerFinalizing')
})

var updateFreeElapsedCtrlSrc = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/utils/update-free-elapsed-controller.js'), 'utf8')
t('_updateFreeElapsed caps display at FREE_TIMER_MAX_MS', function () {
  assert.ok(updateFreeElapsedCtrlSrc.indexOf('maxMs') >= 0,
    'update free elapsed controller should reference maxMs')
  assert.ok(updateFreeElapsedCtrlSrc.indexOf('Math.min') >= 0,
    'update free elapsed controller should use Math.min for capping')
})

t('Tick function calls _checkFreeTimerLimitAndAutoEnd', function () {
  assert.ok(js.indexOf('_checkFreeTimerLimitAndAutoEnd()') >= 0,
    'tick should call _checkFreeTimerLimitAndAutoEnd')
})

t('_checkFreeTimerLimitAndAutoEnd returns early when isPaused', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.isPaused()') >= 0,
    'limit check should guard on isPaused')
})

t('_restoreFreeSession caps elapsed at max', function () {
  assert.ok(freeRestoreSrc.indexOf('options.maxMs') >= 0,
    '_restoreFreeSession should cap at FREE_TIMER_MAX_MS')
})

t('_restoreFreeSession calls _checkFreeTimerLimitAndAutoEnd after interval start', function () {
  assert.ok(freeRestoreSrc.indexOf('_checkFreeTimerLimitAndAutoEnd()') >= 0,
    '_restoreFreeSession should check limit after restoring')
})

t('active light sync caps free timer display', function () {
  assert.ok(activeSyncSrc.indexOf('options.maxMs') >= 0,
    'active light sync should cap the free display via options.maxMs')
  assert.ok(recoveryAdapterSrc.indexOf('maxMs: FREE_TIMER_MAX_MS') >= 0,
    'active sync adapter must inject FREE_TIMER_MAX_MS as the sync cap')
})

t('onUnload clears timer interval', function () {
  var onUnloadMethod = extractMethod(js, 'onUnload')
  assert.ok(onUnloadMethod.indexOf('_clearTimer') >= 0,
    'onUnload must clear timer')
})

t('_resetToIdle clears free timer state', function () {
  assert.ok(resetToIdleCtrlSrc.indexOf('clearFreeTimerInterval') >= 0)
  assert.ok(resetToIdleCtrlSrc.indexOf('isFreeTimer: false') >= 0)
  assert.ok(resetToIdleCtrlSrc.indexOf("freeDisplayTime: '00:00:00'") >= 0)
})

// ══════════════════════════════════════════════════════════════════
// 2. WXML mode info text
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 2. WXML mode info text ---')

var wxml = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.wxml'), 'utf8')

t('Free timer mode info says "最长5小时" not "无时长限制"', function () {
  assert.ok(wxml.indexOf('无时长限制') === -1,
    'WXML must not say 无时长限制')
  assert.ok(wxml.indexOf('最长5小时') >= 0,
    'WXML must say 最长5小时')
})

t('Mode info text references free preset selection', function () {
  assert.ok(wxml.indexOf("selectedPreset === 'free'") >= 0)
})

// ══════════════════════════════════════════════════════════════════
// 3. Display and cap validation via formatElapsedSec
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 3. Display cap ---')

t('formatElapsedSec(18000) produces display 05:00:00', function () {
  var fmtResult = formatElapsedSec(18000)
  assert.strictEqual(fmtResult.display, '05:00:00', 'got ' + fmtResult.display)
})

t('formatElapsedSec(17999) produces display 04:59:59', function () {
  var fmtResult = formatElapsedSec(17999)
  assert.strictEqual(fmtResult.display, '04:59:59', 'got ' + fmtResult.display)
})

t('formatElapsedSec(0) produces display 00:00:00', function () {
  var fmtResult = formatElapsedSec(0)
  assert.strictEqual(fmtResult.display, '00:00:00', 'got ' + fmtResult.display)
})

t('formatElapsedSec handles negative gracefully', function () {
  var fmtResult = formatElapsedSec(-100)
  assert.strictEqual(fmtResult.display, '00:00:00', 'got ' + fmtResult.display)
})

// ══════════════════════════════════════════════════════════════════
// 4. Method extraction — static analysis
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 4. Behavior via static analysis ---')

t('_checkFreeTimerLimitAndAutoEnd returns false early for paused/not-free/finalizing', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('!options.isFreeTimer()') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.isPaused()') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.finalizing()') >= 0)
})

t('_updateFreeElapsed caps display at 05:00:00 via Math.min', function () {
  assert.ok(updateFreeElapsedCtrlSrc.indexOf('Math.min') >= 0)
  assert.ok(updateFreeElapsedCtrlSrc.indexOf('maxMs') >= 0)
})

t('_autoFinishFreeTimer clears interval and fixes elapsed to 5h', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('clearFreeTimerInterval') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('options.maxMs()') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('await complete(options)') >= 0)
})

t('_confirmEndFreeTimer calls _completeFreeTimerSession', function () {
  assert.ok(confirmEndFreeTimerCtrlSrc.indexOf('completeFreeTimerSession') >= 0)
})

t('_completeFreeTimerSession uses retryable server-authoritative completion', function () {
  assert.ok(freeTimerLimitCtrlSrc.indexOf('completeWithRetry') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('actual_duration_sec') < 0, 'no client actual_duration_sec (server computes it)')
  assert.ok(freeTimerLimitCtrlSrc.indexOf('resetToIdle') >= 0)
  assert.ok(freeTimerLimitCtrlSrc.indexOf('loadTodayStats') >= 0)
})

t('_resetToIdle fully clears free timer state', function () {
  assert.ok(resetToIdleCtrlSrc.indexOf('clearFreeTimerInterval') >= 0)
  assert.ok(resetToIdleCtrlSrc.indexOf('isFreeTimer: false') >= 0)
  assert.ok(resetToIdleCtrlSrc.indexOf("freeDisplayTime: '00:00:00'") >= 0)
  assert.ok(resetToIdleCtrlSrc.indexOf('showEndConfirm: false') >= 0)
})

t('onUnload calls _clearTimer', function () {
  var methodBody = extractMethod(js, 'onUnload')
  assert.ok(methodBody.indexOf('_clearTimer') >= 0)
})

t('_clearTimer calls _clearFreeTimerInterval', function () {
  var methodBody = extractMethod(js, '_clearTimer')
  assert.ok(methodBody.indexOf('_clearFreeTimerInterval') >= 0)
})

t('active light sync caps free timer elapsed at the injected max', function () {
  assert.ok(activeSyncSrc.indexOf('Math.min(elapsedMs, options.maxMs)') >= 0)
  assert.ok(activeSyncSrc.indexOf('elapsedMs >= options.maxMs') >= 0)
})

t('_restoreFreeSession caps elapsed at max and calls _checkFreeTimerLimitAndAutoEnd', function () {
  assert.ok(freeRestoreSrc.indexOf('options.maxMs') >= 0,
    '_restoreFreeSession must reference FREE_TIMER_MAX_MS')
  assert.ok(freeRestoreSrc.indexOf('_checkFreeTimerLimitAndAutoEnd') >= 0,
    '_restoreFreeSession must call _checkFreeTimerLimitAndAutoEnd')
})

t('Free timer controller checks the limit before scheduling the next tick', function () {
  assert.ok(sessionControlAdapterSrc.indexOf('shouldFinalize: () => page._checkFreeTimerLimitAndAutoEnd()') >= 0,
    'free timer capability must check the limit after each tick')
})

t('Countdown-related methods do not reference FREE_TIMER_MAX_MS', function () {
  var startTimerBody = extractMethod(js, '_startTimer')
  var beginCountdownBody = extractMethod(js, '_beginCountdown')
  var onWorkCompleteBody = extractMethod(js, '_onWorkComplete')
  var restoreBreakBody = extractMethod(js, '_restoreBreak')

  assert.ok(startTimerBody.indexOf('FREE_TIMER_MAX_MS') === -1)
  assert.ok(beginCountdownBody.indexOf('FREE_TIMER_MAX_MS') === -1)
  assert.ok(onWorkCompleteBody.indexOf('FREE_TIMER_MAX_MS') === -1)
  assert.ok(restoreBreakBody.indexOf('FREE_TIMER_MAX_MS') === -1)
})

t('No global button styles in pomodoro.wxss', function () {
  var wxss = fs.readFileSync(path.join(__dirname, '../pages/pomodoro/pomodoro.wxss'), 'utf8')
  var lines = wxss.split('\n')
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    if (line === 'button {' || line === 'button[' || line === 'button::') {
      throw new Error('pomodoro.wxss must not contain global button styles at line ' + (i + 1))
    }
  }
})

// ══════════════════════════════════════════════════════════════════
// 5. Pomodoro mode isolation
// ══════════════════════════════════════════════════════════════════
console.log('\n--- 5. Mode isolation ---')

t('_onWorkComplete does not handle free timer max limit', function () {
  var methodBody = extractMethod(js, '_onWorkComplete')
  assert.ok(methodBody.indexOf('FREE_TIMER_MAX_MS') === -1)
})

// ══════════════════════════════════════════════════════════════════
// Summary
// ══════════════════════════════════════════════════════════════════
console.log('\n==============================')
console.log('Passed:', testsPassed, ' Failed:', testsFailed)
console.log('==============================\n')

if (testsFailed > 0) process.exit(1)

// ── Helper: extract a method body from Page({...}) by name ──
function extractMethod(src, name) {
  // ES6 shorthand: name() {} or async name() {} or name: function() {}
  var patterns = [
    new RegExp('(?:^|,)\\s*(?:async\\s+)?' + name + '\\s*\\(', 'm'),
    new RegExp('(?:^|\\s)' + name + '\\s*:\\s*function\\s*\\(', 'm'),
  ]
  var startMatch = null
  for (var i = 0; i < patterns.length; i++) {
    startMatch = src.match(patterns[i])
    if (startMatch) break
  }
  if (!startMatch) return ''

  var j = startMatch.index + startMatch[0].length
  while (j < src.length && src[j] !== '{') j++
  if (j >= src.length) return ''
  j++

  var braceCount = 1
  var result = src.substring(startMatch.index, j)
  while (j < src.length && braceCount > 0) {
    var ch = src[j]
    result += ch
    if (ch === '{') braceCount++
    else if (ch === '}') braceCount--
    j++
  }
  return result
}
