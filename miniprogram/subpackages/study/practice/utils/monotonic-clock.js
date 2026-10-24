let performanceClock = null
let performanceClockUsable = false

function monotonicNow() {
  try {
    if (!performanceClock && typeof wx !== 'undefined' && typeof wx.getPerformance === 'function') {
      try {
        performanceClock = wx.getPerformance()
        performanceClockUsable = typeof performanceClock.now === 'function'
      } catch (_) {
        performanceClock = null
        performanceClockUsable = false
      }
    }
    if (performanceClockUsable) {
      return performanceClock.now()
    }
  } catch (_) {}
  return Date.now()
}

module.exports = {
  monotonicNow,
}
