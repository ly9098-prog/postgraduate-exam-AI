const FRAME_INTERVAL_MS = 80
const ANIMATION_DURATIONS = {
  streakDays: 600,
  goalDone: 600,
  levelProgress: 500,
}

function clear(page) {
  if (page._animTimer) {
    clearTimeout(page._animTimer)
    page._animTimer = null
  }
}

function updateField(options) {
  const {
    data,
    key,
    fromVal,
    toVal,
    duration,
    elapsed,
  } = options
  if (fromVal === toVal) return true
  const progress = Math.min(elapsed / duration, 1)
  const eased = 1 - Math.pow(1 - progress, 3)
  const current = Math.round(fromVal + (toVal - fromVal) * eased)
  data[key] = Math.min(toVal, Math.max(Math.min(fromVal, toVal), current))
  return progress >= 1
}

function tick(page, state) {
  if (!page._alive || !page._visible) {
    page._animTimer = null
    return
  }
  const elapsed = Date.now() - state.startTime
  const data = {}
  const durations = state.durations || ANIMATION_DURATIONS
  const streakDone = updateField({
    data,
    key: '_animStreakDays',
    fromVal: state.from.streakDays,
    toVal: state.to.streakDays,
    duration: durations.streakDays,
    elapsed,
  })
  const goalDone = updateField({
    data,
    key: '_animGoalDone',
    fromVal: state.from.goalDone,
    toVal: state.to.goalDone,
    duration: durations.goalDone,
    elapsed,
  })
  const levelDone = updateField({
    data,
    key: '_animLevelProgress',
    fromVal: state.from.levelProgress,
    toVal: state.to.levelProgress,
    duration: durations.levelProgress,
    elapsed,
  })
  if (Object.keys(data).length > 0) page.setData(data)
  if (!streakDone || !goalDone || !levelDone) {
    page._animTimer = setTimeout(() => tick(page, state), FRAME_INTERVAL_MS)
    return
  }
  page.setData({
    _animStreakDays: state.to.streakDays,
    _animGoalDone: state.to.goalDone,
    _animLevelProgress: state.to.levelProgress,
  })
  page._animTimer = null
}

function start(page) {
  clear(page)
  const targets = page._growthTargets
  const from = {
    streakDays: page.data._animStreakDays,
    goalDone: page.data._animGoalDone,
    levelProgress: page.data._animLevelProgress,
  }
  const to = {
    streakDays: targets.streakDays,
    goalDone: targets.todayGoalDone,
    levelProgress: targets.levelProgress,
  }
  const unchanged = from.streakDays === to.streakDays &&
    from.goalDone === to.goalDone &&
    from.levelProgress === to.levelProgress
  if (unchanged) return
  const state = { from, to, durations: ANIMATION_DURATIONS, startTime: Date.now() }
  page._animTimer = setTimeout(() => tick(page, state), FRAME_INTERVAL_MS)
}

module.exports = { clear, start, tick }
