function createStatsController(options) {
  const state = { requestSeq: 0 }
  return {
    invalidate: () => invalidate(state),
    load: () => load(options, state),
  }
}

function invalidate(state) {
  state.requestSeq += 1
}

// Today's totals are refreshed from several lifecycle/conflict paths. Only the
// newest request may write the view, so a slower pre-completion response can
// never overwrite a newer post-completion total.
async function load(options, state) {
  const seq = (state.requestSeq += 1)
  try {
    const stats = await options.get('/pomodoro/stats')
    if (seq !== state.requestSeq) return
    const durationSec = stats.today_duration_sec || 0
    const minutes = Math.floor(durationSec / 60)
    options.setTodayDurationSec(durationSec)
    options.setData({
      todaySessions: stats.today_sessions || 0,
      todayDurationText: minutes >= 60
        ? `${Math.floor(minutes / 60)}时${minutes % 60}分`
        : `${minutes}分钟`,
    })
  } catch (_) {}
}

module.exports = { createStatsController }
