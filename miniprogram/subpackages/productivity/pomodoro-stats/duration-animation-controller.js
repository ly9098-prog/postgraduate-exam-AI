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
  let step = 0
  let lastText = startText
  let lastValue = startValue
  let lastSessions = startSessionCount

  options.setData({ durationValueAnimating: true })

  const tick = () => {
    if (!options.isAlive() || !options.isVisible() || token !== options.getToken()) return

    step += 1
    const progress = Math.min(1, step / steps)
    const eased = viewHelpers.easeInOutCubic(progress)
    let nextValue = Math.round(startValue + durationDelta * eased)
    let nextSessions = Math.round(startSessionCount + sessionDelta * eased)

    nextValue = durationDelta >= 0
      ? Math.max(lastValue, Math.min(targetValue, nextValue))
      : Math.min(lastValue, Math.max(targetValue, nextValue))
    nextSessions = sessionDelta >= 0
      ? Math.max(lastSessions, Math.min(targetSessionCount, nextSessions))
      : Math.min(lastSessions, Math.max(targetSessionCount, nextSessions))

    const isFinal = progress >= 1
    if (isFinal) {
      nextValue = targetValue
      nextSessions = targetSessionCount
    }
    lastValue = nextValue
    lastSessions = nextSessions
    options.setDisplayDurationSec(nextValue)

    const nextText = formatMin(nextValue)
    if (nextText !== lastText || nextSessions !== options.getDisplaySessions() || isFinal) {
      lastText = nextText
      options.setData({
        _dispTodaySessions: nextSessions,
        ...displayPatch(nextText),
        durationValueAnimating: !isFinal,
      })
    }

    if (!isFinal) options.setTimer(options.setTimeout(tick, interval))
    else options.setTimer(null)
  }

  options.setTimer(options.setTimeout(tick, interval))
}

module.exports = {
  createDurationAnimationController,
}
