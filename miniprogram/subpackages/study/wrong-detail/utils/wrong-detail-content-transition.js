function onAiSwipeStart(page, e) {
if (page._switching) return
const touch = e && e.touches && e.touches[0]
if (!touch) return
page._aiSwipeStart = {
x: Number(touch.clientX),
y: Number(touch.clientY),
ts: Date.now(),
}
}

function onAiSwipeEnd(page, e) {
const start = page._aiSwipeStart
page._aiSwipeStart = null
if (!start || page._switching) return
const touch = e && e.changedTouches && e.changedTouches[0]
if (!touch) return
const dx = Number(touch.clientX) - start.x
const dy = Number(touch.clientY) - start.y
const absX = Math.abs(dx)
const absY = Math.abs(dy)
if (absX < 56 || absX <= absY * 1.2) return
const targetIdx = dx < 0 ? page.data.currentIdx + 1 : page.data.currentIdx - 1
if (targetIdx < 0 || targetIdx >= page.data.questionIds.length) return
page._navigateTo(targetIdx, 150, dx < 0 ? 'left' : 'right')
}

function onAiSwipeCancel(page) {
page._aiSwipeStart = null
}

function _beginContentSwitchTransition(page, direction) {
if (!page._alive) return
const dir = direction === 'right' ? 'right' : 'left'
if (page._contentTransitionTimer) {
clearTimeout(page._contentTransitionTimer)
page._contentTransitionTimer = null
}
page._contentTransitionStartedAt = Date.now()
page._contentTransitionDirection = dir
page.setData({
contentTransitionClass: dir === 'left' ? 'content-slide-out-left' : 'content-slide-out-right',
})
}

async function _waitForContentSwitchOut(page, direction, animMs, { QUESTION_SWITCH_OUT_MS, _sleep }) {
const dir = direction === 'right' ? 'right' : 'left'
if (!page._contentTransitionStartedAt || page._contentTransitionDirection !== dir) {
page._beginContentSwitchTransition(dir)
}
const requested = Number(animMs)
const waitTarget = Number.isFinite(requested) && requested > 0
? Math.min(QUESTION_SWITCH_OUT_MS, requested)
: QUESTION_SWITCH_OUT_MS
const elapsed = Date.now() - page._contentTransitionStartedAt
if (elapsed < waitTarget) await _sleep(waitTarget - elapsed)
}

function _finishContentSwitchTransition(page, direction, { QUESTION_SWITCH_IN_MS }) {
const dir = direction === 'right' ? 'right' : 'left'
const inClass = dir === 'left' ? 'content-slide-in-right' : 'content-slide-in-left'
if (page._contentTransitionTimer) clearTimeout(page._contentTransitionTimer)
page._contentTransitionStartedAt = 0
page._contentTransitionDirection = ''
page.setData({ contentTransitionClass: inClass })
page._contentTransitionTimer = setTimeout(() => {
page._contentTransitionTimer = null
page._switching = false
page._clearSwitchWatchdog()
if (page._alive) page.setData({ contentTransitionClass: '' })
}, QUESTION_SWITCH_IN_MS)
}

function _cancelContentSwitchTransition(page) {
if (page._contentTransitionTimer) {
clearTimeout(page._contentTransitionTimer)
page._contentTransitionTimer = null
}
page._contentTransitionStartedAt = 0
page._contentTransitionDirection = ''
if (page._alive) page.setData({ contentTransitionClass: '' })
}

function _armSwitchWatchdog(page, ms, { QUESTION_SWITCH_WATCHDOG_MS }) {
page._clearSwitchWatchdog()
var duration = Number(ms) > 0 ? Number(ms) : QUESTION_SWITCH_WATCHDOG_MS
var self = page
page._switchWatchdogTimer = setTimeout(function() {
self._switchWatchdogTimer = null
console.warn('[wrong-detail] 切题锁看门狗触发，强制复位')
self._forceResetSwitchLock()
}, duration)
}

function _clearSwitchWatchdog(page) {
if (page._switchWatchdogTimer) {
clearTimeout(page._switchWatchdogTimer)
page._switchWatchdogTimer = null
}
}

function _forceResetSwitchLock(page) {
page._navigationSeq = Number(page._navigationSeq || 0) + 1
page._switching = false
if (page._contentTransitionTimer) {
clearTimeout(page._contentTransitionTimer)
page._contentTransitionTimer = null
}
if (page._switchMaskTimer) {
clearTimeout(page._switchMaskTimer)
page._switchMaskTimer = null
}
page._contentTransitionStartedAt = 0
page._contentTransitionDirection = ''
page._clearSwitchWatchdog()
if (page._alive) {
page.setData({ contentTransitionClass: '', showSwitchMask: false, aiRegenerating: false })
}
}

module.exports = {
  onAiSwipeStart,
  onAiSwipeEnd,
  onAiSwipeCancel,
  _beginContentSwitchTransition,
  _waitForContentSwitchOut,
  _finishContentSwitchTransition,
  _cancelContentSwitchTransition,
  _armSwitchWatchdog,
  _clearSwitchWatchdog,
  _forceResetSwitchLock,
}
