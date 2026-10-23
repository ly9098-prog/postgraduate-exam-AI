/**
 * Controller for the five-hour free-timer limit.
 *
 * The finalizing flag lives in controller state; all page effects are
 * injected as callbacks.
 */

const { formatElapsedSec } = require('./timer-math')

function createFreeTimerLimitController(options) {
  return {
    check: () => check(options),
    autoFinish: () => autoFinish(options),
    complete: () => complete(options),
  }
}

function check(options) {
  if (!options.isFreeTimer() || options.isPaused() || options.finalizing()) return false
  if (options.getEffectiveFreeElapsedMs() < options.maxMs()) return false
  options.autoFinish()
  return true
}

async function autoFinish(options) {
  if (options.finalizing()) return
  options.setFinalizing(true)
  options.clearFreeTimerInterval()

  const elapsedSec = Math.floor(options.maxMs() / 1000)
  const fmt = options.formatElapsedSec(elapsedSec)
  options.setElapsedSec(elapsedSec)
  options.setData({ freeDisplayTime: fmt.display })
  options.showToast({
    title: '自由计时已达5小时上限，已自动结束',
    icon: 'none',
    duration: 2000,
  })

  await complete(options)
  options.setFinalizing(false)
}

function complete(options) {
  const sessionId = options.getSessionId()
  if (!sessionId) return
  options.clearFreeTimerInterval()
  options.completeWithRetry(sessionId, options.now()).then(synced => {
    const conflict = options.consumeTerminalConflict(sessionId, 'complete')
    if (conflict) {
      options.handleTerminalConflict(sessionId, conflict)
      return
    }
    options.showToast({
      title: synced ? '已记录本次专注' : '网络恢复后将自动同步',
      icon: 'none',
      duration: 2000,
    })
    if (synced) options.loadTodayStats()
  })
  // Do not keep the end-confirm UI blocked behind a request timeout.
  options.resetToIdle()
}

module.exports = { createFreeTimerLimitController, formatElapsedSec }
