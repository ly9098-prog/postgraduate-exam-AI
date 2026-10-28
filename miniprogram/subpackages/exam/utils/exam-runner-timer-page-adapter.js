const api = require('../../../utils/api')

function pad2(n) { return String(Math.max(0, Number(n) || 0)).padStart(2, '0') }
function formatClock(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${pad2(h)}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`
}

function buildExamTimerPageCapabilities(page) {
  return {
    now: () => api.now(),
    formatClock,
    isPageAlive: () => page._pageAlive,
    isAttemptTerminal: () => page._attemptTerminal,
    isTerminalNavigation: () => page._terminalNavigation,
    isTimeExpired: () => page.data.timeExpired,
    getRemainingText: () => page.data.remainingText,
    setData: patch => page.setData(patch),
    getBaseRemaining: () => page._timerBaseRemaining,
    setBaseRemaining: value => { page._timerBaseRemaining = value },
    getStartedAt: () => page._timerStartedAt,
    setStartedAt: value => { page._timerStartedAt = value },
    getTimer: () => page._timer,
    setTimer: timer => { page._timer = timer },
    setInterval,
    clearInterval,
    onExpired: () => {
      page._retainPendingForSubmit = true
      page._persistPending()
      page.submitExam({ auto: true }).catch(() => {})
    },
  }
}

module.exports = {
  buildExamTimerPageCapabilities,
}
