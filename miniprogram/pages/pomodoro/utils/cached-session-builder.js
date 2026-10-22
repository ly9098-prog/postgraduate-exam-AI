function buildCachedActiveSession(local, toISOString) {
  if (!local) return null
  const cachedStartTime = Number(local.sessionStartTime)
  if (!Number.isFinite(cachedStartTime) || cachedStartTime <= 0 || !local.sessionId) return null
  const isPaused = !!local.isPaused
  return {
    id: local.sessionId,
    start_time: toISOString(cachedStartTime),
    work_duration: Number(local.workDuration || 0),
    break_duration: Number(local.breakDuration || 0),
    preset: local.selectedPreset || 'standard',
    status: isPaused ? 'paused' : 'running',
    paused_at: isPaused && local.pauseStartTime
      ? toISOString(local.pauseStartTime)
      : null,
    total_paused_sec: Math.floor(Number(local.totalPausedMs || 0) / 1000),
    subject_id: local.selectedSubjectId,
    subject_code: local.selectedSubjectCode || '',
    subject_name: local.selectedSubjectName || '',
    allocation_mode: local.allocationMode || 'single',
    task_type: local.selectedTaskType || '',
    _local_elapsed_sec: local.isFreeTimer ? Number(local.elapsedSec || 0) : undefined,
  }
}

module.exports = { buildCachedActiveSession }
