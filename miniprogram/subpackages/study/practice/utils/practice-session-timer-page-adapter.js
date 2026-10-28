const {
  createPracticeSessionTimerController,
} = require('./practice-session-timer-controller')

function createPracticeSessionTimerPageController(page, monotonicNow, timers = {}) {
  const setIntervalFn = timers.setInterval || setInterval
  const clearIntervalFn = timers.clearInterval || clearInterval

  return createPracticeSessionTimerController({
    getSession: () => page._practiceSession,
    isPageAlive: () => page._pageAlive,
    monotonicNow,
    getTimer: () => page._timer,
    setTimer: timer => {
      page._timer = timer
    },
    setInterval: (callback, delay) => setIntervalFn(callback, delay),
    clearInterval: timer => clearIntervalFn(timer),
    formatElapsed: seconds => page._fmt(seconds),
    setData: patch => page.setData(patch),
  })
}

module.exports = {
  createPracticeSessionTimerPageController,
}
