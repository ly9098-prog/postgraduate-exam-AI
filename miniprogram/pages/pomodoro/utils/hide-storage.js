function buildRunningSnapshot(view, timer, now) {
  return {
    sessionStartTime: timer.sessionStartTime,
    workDuration: view.workDuration,
    breakDuration: view.breakDuration,
    selectedPreset: view.selectedPreset,
    selectedSubjectId: view.selectedSubjectId,
    selectedSubjectCode: view.selectedSubject ? view.selectedSubject.code : '',
    selectedSubjectName: view.selectedSubject ? view.selectedSubject.name : '',
    allocationMode: view.allocationMode,
    selectedTaskType: view.selectedTaskType,
    isPaused: view.isPaused,
    totalPausedMs: timer.totalPausedMs,
    pauseStartTime: view.isPaused ? (timer.pauseStartTime || now()) : null,
    sessionId: timer.sessionId,
    isFreeTimer: view.isFreeTimer,
    elapsedSec: timer.elapsedSec,
    freeDisplayOffsetMs: 0,
    savedAt: now(),
  }
}

function cancelUnknownStartOnHide(options) {
  const stored = options.readStorage('pomodoro_unknown_start', 'onHide unknown start')
  if (stored.ok && stored.value) {
    options.writeStorage('pomodoro_unknown_start', {
      ...stored.value,
      cancelIfFound: true,
      cancelAt: options.now(),
    }, 'onHide cancel unknown start')
  }
}

function persistSessionOnHide(options) {
  const view = options.view()
  const confirm = options.confirmSnapshot()
  if (view.showEndConfirm && confirm) {
    options.writeStorage('pomodoro_confirm_pause', confirm, 'onHide confirm snapshot')
  }
  const stored = options.readStorage('pomodoro_completion', 'onHide completion')
  const timer = options.timer()
  if (stored.ok && !stored.value && view.phase === 'running' && timer.sessionId && !view.showCelebration) {
    options.writeStorage(
      'pomodoro_running_state',
      buildRunningSnapshot(view, timer, options.now),
      'onHide running snapshot',
    )
  }
}

module.exports = { buildRunningSnapshot, cancelUnknownStartOnHide, persistSessionOnHide }
