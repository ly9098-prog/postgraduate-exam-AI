const assert = require('node:assert/strict')
const { buildEndConfirmViewModel } = require('../pages/pomodoro/utils/end-confirm-view-model')

// ── free-complete mode ──

const freeShort = buildEndConfirmViewModel('free-complete', { elapsedSec: 0 })
assert.equal(freeShort.endConfirmTheme, 'free')
assert.equal(freeShort.endConfirmTitle, '结束自由计时？')
assert.equal(freeShort.endConfirmLine1, '当前计时时长较短')
assert.equal(freeShort.endConfirmLine2, '确认后仍会结束本次计时。')
assert.equal(freeShort.endConfirmLine3, '')
assert.equal(freeShort.endConfirmOkText, '确认结束')
assert.equal(freeShort.endConfirmCancelText, '继续计时')

const freeLong = buildEndConfirmViewModel('free-complete', { elapsedSec: 3661 })
assert.equal(freeLong.endConfirmLine1, '本次已专注')
assert.ok(freeLong.endConfirmLine2.includes('小时'))
assert.ok(freeLong.endConfirmLine2.includes('分'))
assert.equal(freeLong.endConfirmLine3, '确认后将计入学习统计。')

// ── countdown-interrupt mode (focus phase) ──

const countdownFocus = buildEndConfirmViewModel('countdown-interrupt', {
  phase: 'running',
  totalSec: 1500,
  remainingSec: 300,
})
assert.equal(countdownFocus.endConfirmTheme, 'focus')
assert.equal(countdownFocus.endConfirmTitle, '结束本次专注？')
assert.equal(countdownFocus.endConfirmOkText, '结束')
assert.equal(countdownFocus.endConfirmCancelText, '继续专注')
assert.ok(countdownFocus.endConfirmLine2.length > 0)

const countdownNoElapsed = buildEndConfirmViewModel('countdown-interrupt', {
  phase: 'running',
  totalSec: 1500,
  remainingSec: 1500,
})
assert.equal(countdownNoElapsed.endConfirmLine1, '确认后将结束当前番茄钟。')
assert.equal(countdownNoElapsed.endConfirmLine2, '')
assert.equal(countdownNoElapsed.endConfirmLine3, '')

// ── countdown-interrupt mode (break phase) ──

const countdownBreak = buildEndConfirmViewModel('countdown-interrupt', {
  phase: 'break',
  totalSec: 300,
  remainingSec: 60,
})
assert.equal(countdownBreak.endConfirmTheme, 'break')
assert.equal(countdownBreak.endConfirmTitle, '结束休息？')
assert.equal(countdownBreak.endConfirmCancelText, '继续休息')

// ── unknown mode throws ──

try {
  buildEndConfirmViewModel('unknown', {})
  assert.fail('should have thrown')
} catch (e) {
  assert.ok(e.message.includes('Unknown confirm mode'))
}

console.log('Pomodoro end confirm view model passed: free/countdown/break/unknown')
