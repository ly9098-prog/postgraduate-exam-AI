function createFreeSessionRestoreController(options) {
  return {
    restore(session) {
      return restore(session, options)
    },
  }
}

function restore(session, options) {
  const base = resolveBase(session, options)
  if (base.done) return base.result
  return applyRestore(session, base, options)
}

function resolveBase(session, options) {
  const page = options.page
  const startTime = options.parseServerTime(session.start_time)
  if (!Number.isFinite(startTime) || startTime <= 0) {
    page._safeRemovePomodoroStorage('pomodoro_free_pause', 'best-effort cleanup')
    page._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
    page._resetToIdle()
    return { done: true, result: true }
  }

  const storedPause = page._safeGetPomodoroStorage(
    'pomodoro_free_pause',
    'restore free pause'
  )
  if (!storedPause.ok) {
    page._showPomodoroPersistenceError()
    return { done: true, result: false }
  }

  const pausedAtMs = session.paused_at
    ? options.parseServerTime(session.paused_at)
    : null
  const now = options.now()
  let totalPausedMs = options.resolvePausedMs({
    serverPausedSec: session.total_paused_sec || 0,
    savedPause: storedPause.value,
    pausedAtMs,
    now,
    sessionId: session.id,
  }).totalPausedMs
  totalPausedMs = page._mergeLocalPauseAdjustment(session.id, totalPausedMs, true)
  if (totalPausedMs === null) {
    page._showPomodoroPersistenceError()
    return { done: true, result: false }
  }

  return { done: false, startTime, storedPause, pausedAtMs, now, totalPausedMs }
}

function applyRestore(session, base, options) {
  const page = options.page
  const restored = options.computeFreeRestore({
    serverPausedSec: session.total_paused_sec || 0,
    savedPause: base.storedPause.value,
    pausedAtMs: base.pausedAtMs,
    now: base.now,
    startTime: base.startTime,
    maxMs: options.maxMs,
    sessionId: session.id,
    totalPausedMs: base.totalPausedMs,
  })
  const formatted = options.formatElapsedSec(restored.elapsed)

  page._timerState.sessionId = session.id
  page._timerState.sessionStartTime = base.startTime
  page._timerState.totalPausedMs = restored.totalPausedMs
  page._timerState.freeDisplayOffsetMs = 0
  page._timerState.pauseStartTime = restored.isPaused ? base.now : null

  const projection = resolveProjection(session, options)
  render(session, restored, formatted, projection, options)
  options.nextTick(() => {
    page._initCanvas(true)
    page.drawRing(0, false)
  })
  if (!restored.isPaused) {
    page._startFreeTimerInterval()
    page._checkFreeTimerLimitAndAutoEnd()
  }
  return true
}

function resolveProjection(session, options) {
  const page = options.page
  const subject = options.resolveRestoredSubject({
    session,
    subjects: page.data.subjects,
    lookupSubjectIdByCode: code => page._lookupSubjectIdByCode(code),
  })
  const sessionTaskType = options.pomodoroTaskTypes.typeForSession(session)
  const taskTypeLabel = sessionTaskType
    ? options.pomodoroTaskTypes.label(sessionTaskType)
    : '未分类'
  if (sessionTaskType) {
    options.pomodoroTaskTypes.recordSession(session, sessionTaskType)
  }
  return {
    subject,
    taskType: sessionTaskType || '',
    taskTypeLabel,
  }
}

function render(session, restored, formatted, projection, options) {
  const page = options.page
  const { subject, taskType, taskTypeLabel } = projection
  page._clearTimer()
  page._timerState.elapsedSec = restored.elapsed
  page._timerState.freeFriendlyText = formatted.friendly
  page._timerState.progress = 1
  page.setData({
    phase: options.runningPhase,
    ringCanvasVisible: true,
    isFreeTimer: true,
    selectedSubjectId: subject.subjectId,
    selectedSubject: subject.selectedSubject,
    allocationMode: subject.aggregate ? 'equal_408_core_v1' : 'single',
    selectedTaskType: taskType,
    selectedTaskTypeLabel: taskTypeLabel,
    selectedPreset: 'free',
    workDuration: 0,
    breakDuration: 0,
    isPaused: restored.isPaused,
    freeDisplayTime: formatted.display,
    showEndConfirm: false,
  })
  page._updateComputedFields()
}

module.exports = { createFreeSessionRestoreController }
