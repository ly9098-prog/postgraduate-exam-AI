function resolvePausedMs(options) {
  const serverBaseMs = Math.max(0, Number(options.serverPausedSec || 0) * 1000)
  const savedPause = options.savedPause
  let totalPausedMs = serverBaseMs
  let isPaused = false

  if (savedPause && savedPause.sessionId === options.sessionId) {
    const savedTotal = Number(savedPause.totalPausedMs || 0)
    const pauseStart = Number(savedPause.pauseStartTime || options.now)
    totalPausedMs = Number.isFinite(savedTotal) && Number.isFinite(pauseStart)
      ? savedTotal + Math.max(0, options.now - pauseStart)
      : serverBaseMs
    isPaused = true
  } else if (options.pausedAtMs !== null && options.pausedAtMs !== undefined) {
    const pausedAtMs = Number(options.pausedAtMs)
    if (Number.isFinite(pausedAtMs)) {
      totalPausedMs = serverBaseMs + Math.max(0, options.now - pausedAtMs)
      isPaused = true
    }
  }

  if (!Number.isFinite(totalPausedMs) || totalPausedMs < 0) totalPausedMs = 0
  return { totalPausedMs, isPaused }
}

function computeCountdownRestore(options) {
  const paused = resolvePausedMs(options)
  const hasPausedOverride = options.totalPausedMs !== undefined && options.totalPausedMs !== null
  const pausedOverride = Number(options.totalPausedMs)
  const totalPausedMs = hasPausedOverride && Number.isFinite(pausedOverride)
    ? Math.max(0, pausedOverride)
    : paused.totalPausedMs
  const elapsed = Math.floor((options.now - options.startTime - totalPausedMs) / 1000)
  const remaining = Number.isFinite(options.totalSec) && Number.isFinite(elapsed)
    ? Math.max(0, options.totalSec - elapsed)
    : 0
  return {
    ...paused,
    totalPausedMs,
    elapsed,
    remaining,
    progress: options.totalSec > 0 ? remaining / options.totalSec : 0,
    completedAt: Math.min(
      options.now,
      options.startTime + Math.max(0, totalPausedMs) + options.totalSec * 1000,
    ),
  }
}

function computeFreeRestore(options) {
  const paused = resolvePausedMs(options)
  const hasPausedOverride = options.totalPausedMs !== undefined && options.totalPausedMs !== null
  const pausedOverride = Number(options.totalPausedMs)
  const totalPausedMs = hasPausedOverride && Number.isFinite(pausedOverride)
    ? Math.max(0, pausedOverride)
    : paused.totalPausedMs
  let elapsed = Math.max(0, Math.floor((options.now - options.startTime - totalPausedMs) / 1000))
  elapsed = Math.min(elapsed, Math.floor(options.maxMs / 1000))
  return { ...paused, totalPausedMs, elapsed }
}

function resolveRestoredSubject(options) {
  const subjectId = options.session.subject_id ||
    (options.lookupSubjectIdByCode ? options.lookupSubjectIdByCode(options.session.subject_code) : null) ||
    null
  const aggregate = options.session.allocation_mode === 'equal_408_core_v1'
  const restored = (options.subjects || []).find(item => Number(item.id) === Number(subjectId))
  return {
    subjectId,
    subjectCode: options.session.subject_code || '',
    subjectName: options.session.subject_name || '未分类',
    aggregate,
    selectedSubject: subjectId
      ? (restored || {
        id: subjectId,
        code: options.session.subject_code || '',
        name: options.session.subject_name || '未分类',
        _isAggregate: aggregate,
      })
      : null,
  }
}

module.exports = {
  resolvePausedMs,
  computeCountdownRestore,
  computeFreeRestore,
  resolveRestoredSubject,
}
