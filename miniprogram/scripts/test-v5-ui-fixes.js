/**
 * v5 targeted regression checks for the UI/data fixes requested in this patch.
 * Pure static/runtime checks: no backend or WeChat runtime required.
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const diagnosis = require('../subpackages/study/utils/error-diagnosis')

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}
function exists(rel) {
  return fs.existsSync(path.resolve(__dirname, '..', rel))
}

// 1) Timer ring: v8 intentionally restores the original Canvas dial. Keep this
// historical test aligned with the latest user-approved renderer rather than
// asserting the superseded v5 CSS replacement.
const pomodoroWxml = source('pages/pomodoro/pomodoro.wxml')
const pomodoroWxss = source('pages/pomodoro/pomodoro.wxss')
const pomodoroJs = source('pages/pomodoro/pomodoro.js')
assert.ok(pomodoroWxml.includes('type="2d"'))
assert.ok(pomodoroWxml.includes('id="progress-ring"'))
assert.ok(!pomodoroWxml.includes('class="progress-ring-css'))
assert.ok(!pomodoroWxml.includes('class="free-ring-static'))
assert.ok(!pomodoroJs.includes('USE_CSS_RING'), 'superseded CSS renderer flag must be removed')
assert.ok(pomodoroJs.includes('createLinearGradient'))
assert.ok(/lineWidth\s*=\s*12/.test(pomodoroJs))
assert.ok(pomodoroWxss.includes('.ring-time-free'))
assert.ok(pomodoroWxss.includes('-webkit-text-fill-color: transparent'))
assert.ok(pomodoroWxss.includes('animation: free-shimmer 4s linear infinite'))
assert.ok(!pomodoroWxss.includes('-webkit-text-fill-color: currentColor'), 'legacy v5 flat-text override must stay removed')

// 2) Wrong-book overview card uses the v8 web-sourced Lucide-family assets and
// keeps the compact pill layout introduced earlier.
const wrongBookWxml = source('subpackages/study/wrong-book/wrong-book.wxml')
const wrongBookWxss = source('subpackages/study/wrong-book/wrong-book.wxss')
for (const icon of [
  'assets/icons/wrong-book/notebook-text.svg',
  'assets/icons/wrong-book/badge-check.svg',
  'assets/icons/wrong-book/chart-increasing.svg',
]) {
  assert.ok(exists(icon), `${icon} should exist`)
  assert.ok(wrongBookWxml.includes('/' + icon), `${icon} should be used by the overview card`)
}
assert.ok(wrongBookWxss.includes('border-radius: 999rpx'))
assert.ok(!wrongBookWxss.includes('backdrop-filter:'), 'avoid unsupported backdrop-filter dependency')

// 3-6) Wrong-detail persisted cause + no inline AI recommendation + icon affordances.
const wrongDetailWxml = source('subpackages/study/wrong-detail/wrong-detail.wxml')
const wrongDetailJs = source('subpackages/study/wrong-detail/wrong-detail.js')
assert.ok(!wrongDetailWxml.includes('AI 推荐'))
assert.ok(!wrongDetailJs.includes('/diagnosis/suggest'))
assert.ok(wrongDetailJs.includes('api.get(`/wrong-questions/${id}/diagnosis`'))
assert.ok(wrongDetailJs.includes("user_confirmed: true"), 'manual save should remain locally confirmed')
for (const icon of [
  'assets/icons/wrong-detail/circle-question-mark.svg',
  'assets/icons/wrong-detail/badge-check.svg',
  'assets/icons/wrong-detail/circle-arrow-right.svg',
]) {
  assert.ok(exists(icon), `${icon} should exist`)
  assert.ok(wrongDetailWxml.includes('/' + icon), `${icon} should be rendered`)
}
assert.ok(wrongDetailWxml.includes('aria-label="{{nextErrorAction.actionLabel}}"'))
assert.ok(!wrongDetailWxml.includes('<text>{{nextErrorAction.actionLabel}}</text>'))

// Persisted API shapes that previously caused "暂未分类" must normalize reliably.
assert.strictEqual(diagnosis.normalizeDiagnosis({
  diagnosis: { primary_type: 'misread', user_confirmed: true, effective_source: 'user' },
}).userConfirmed, true)
assert.strictEqual(diagnosis.normalizeDiagnosis({
  data: { primary_type: 'careless', effective_source: 'user' },
}).primaryType, 'careless')
assert.strictEqual(diagnosis.normalizeDiagnosis({
  primary_type: 'concept_mistake', effective_source: 'user', user_confirmed: false,
}).userConfirmed, true)
assert.strictEqual(diagnosis.normalizeDiagnosis({ success: true }), null)

console.log('v5 targeted UI/data regression checks passed')
