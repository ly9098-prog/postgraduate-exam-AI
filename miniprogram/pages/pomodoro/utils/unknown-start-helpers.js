function buildUnknownStartPayload(attempt) {
  if (!attempt || !attempt.clientStartId) return null
  return {
    subject_id: attempt.subjectId,
    allocation_mode: attempt.allocationMode || 'single',
    chapter_id: attempt.chapterId || null,
    preset: attempt.preset,
    work_duration: Number(attempt.workDuration || 0),
    break_duration: Number(attempt.breakDuration || 0),
    notification_enabled: !!attempt.notificationEnabled,
    client_start_id: attempt.clientStartId,
  }
}

function matchesUnknownStartAttempt(session, attempt) {
  return !!(
    session && attempt && session.id && attempt.clientStartId &&
    session.client_start_id === attempt.clientStartId
  )
}

function buildUnknownStartAttempt(data, overrides, createClientStartId, now) {
  const opts = overrides || {}
  const clientStartId = opts.clientStartId || createClientStartId()
  return {
    requestedAt: now,
    cancelIfFound: false,
    cancelAt: null,
    clientStartId,
    subjectId: data.selectedSubjectId,
    chapterId: data.fromChapterId || null,
    preset: data.selectedPreset,
    workDuration: data.selectedPreset === 'debug' ? 1 : data.workDuration,
    breakDuration: data.selectedPreset === 'debug' ? 1 : data.breakDuration,
    allocationMode: data.allocationMode,
    notificationEnabled: false,
    taskType: data.selectedTaskType,
    ...opts,
  }
}

module.exports = {
  buildUnknownStartPayload,
  matchesUnknownStartAttempt,
  buildUnknownStartAttempt,
}

function startCancellationAt(session, cancelAt, now, parseServerTime) {
  const requestedAt = Number(cancelAt)
  const fallback = Number.isFinite(requestedAt) && requestedAt > 0 ? requestedAt : now
  const serverStartAt = session && session.start_time ? parseServerTime(session.start_time) : NaN
  return Number.isFinite(serverStartAt) ? Math.max(serverStartAt, fallback) : fallback
}

module.exports.startCancellationAt = startCancellationAt
