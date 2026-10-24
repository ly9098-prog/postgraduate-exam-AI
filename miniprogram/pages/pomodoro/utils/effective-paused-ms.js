/**
 * Compute effective paused milliseconds from a server session, including
 * any currently-active pause interval and local adjustment merge.
 * Pure planner — caller injects now/parseServerTime/mergeLocal.
 */
function buildEffectivePausedMs(session, options) {
  const serverBaseMs = (session.total_paused_sec || 0) * 1000
  let serverEffectiveMs = serverBaseMs

  if (session.paused_at) {
    const pausedAtMs = options.parseServerTime(session.paused_at)
    if (Number.isFinite(pausedAtMs)) {
      serverEffectiveMs += Math.max(0, options.now() - pausedAtMs)
    }
  }

  return options.mergeLocalAdjustment(session.id, serverEffectiveMs)
}

module.exports = { buildEffectivePausedMs }
