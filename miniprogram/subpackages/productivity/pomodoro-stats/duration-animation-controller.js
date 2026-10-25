const viewHelpers = require('./view-helpers')
const { formatMin, buildDurationSegments } = require('./duration-formatter')

function createDurationAnimationController(options) {
  return {
    cancel(resetState) {
      cancelImpl(options, resetState)
    },
    animate(fromSec, toSec, fromSessions, toSessions) {
      animateImpl(options, fromSec, toSec, fromSessions, toSessions)
    },
  }
}

function cancelImpl(options, resetState) {
  options.incrementToken()
  const timer = options.getTimer()
  if (timer) {
    options.clearTimeout(timer)
    options.setTimer(null)
  }
  if (resetState && options.isAlive()) {
    options.setData({ durationValueAnimating: false })
  }
}

function animateImpl(options, fromSec, toSec, fromSessions, toSessions) {
  const startValue = Math.max(0, Number(fromSec) || 0)
  const targetValue = Math.max(0, Number(toSec) || 0)
  const startSessionCount = Math.max(0, Number(fromSessions) || 0)
  const targetSessionCount = Math.max(0, Number(toSessions) || 0)

  cancelImpl(options, false)
  const token = options.getToken()
  const startText = formatMin(startValue)
  const targetText = formatMin(targetValue)
  const displayPatch = options.getDurationDisplayPatch
    ? options.getDurationDisplayPatch
    : text => ({
      _dispTodayDurationText: text,
      _dispTodayDurationSegments: buildDurationSegments(text),
    })

  options.setDisplayDurationSec(startValue)
  if (startText === targetText && startSessionCount === targetSessionCount) {
    options.setDisplayDurationSec(targetValue)
    options.setData({
      _dispTodaySessions: targetSessionCount,
      ...displayPatch(targetText),
      durationValueAnimating: false,
    })
    return
  }

  const steps = 12
  const interval = Math.round(620 / steps)
  const durationDelta = targetValue - startValue
  const sessionDelta = targetSessionCount - startSessionCount
  const state = {
    step: 0,
    lastText: startText,
    lastValue: startValue,
    lastSessions: startSessionCount,
  }

  options.setData({ durationValueAnimating: true })

  const tick = () => durationTick(options, {
    token, steps, interval, startValue, targetValue,
    startSessionCount, targetSessionCount, durationDelta, sessionDelta,
    displayPatch, state,
  })
  options.setTimer(options.setTimeout(tick, interval))
}

function durationTick(options, ctx) {
  if (!options.isAlive() || !options.isVisible() || ctx.token !== options.getToken()) return
  const { steps, interval, startValue, targetValue, startSessionCount, targetSessionCount, durationDelta, sessionDelta, displayPatch, state } = ctx

  state.step += 1
  const progress = Math.min(1, state.step / steps)
  const eased = viewHelpers.easeInOutCubic(progress)
  let nextValue = Math.round(startValue + durationDelta * eased)
  let nextSessions = Math.round(startSessionCount + sessionDelta * eased)

  nextValue = durationDelta >= 0
    ? Math.max(state.lastValue, Math.min(targetValue, nextValue))
    : Math.min(state.lastValue, Math.max(targetValue, nextValue))
  nextSessions = sessionDelta >= 0
    ? Math.max(state.lastSessions, Math.min(targetSessionCount, nextSessions))
    : Math.min(state.lastSessions, Math.max(targetSessionCount, nextSessions))

  const isFinal = progress >= 1
  if (isFinal) { nextValue = targetValue; nextSessions = targetSessionCount }
  state.lastValue = nextValue
  state.lastSessions = nextSessions
  options.setDisplayDurationSec(nextValue)

  const nextText = formatMin(nextValue)
  if (nextText !== state.lastText || nextSessions !== options.getDisplaySessions() || isFinal) {
    state.lastText = nextText
    options.setData({
      _dispTodaySessions: nextSessions,
      ...displayPatch(nextText),
      durationValueAnimating: !isFinal,
    })
  }

  if (!isFinal) options.setTimer(options.setTimeout(() => durationTick(options, ctx), interval))
  else options.setTimer(null)
}

module.exports = {
  createDurationAnimationController,
}
