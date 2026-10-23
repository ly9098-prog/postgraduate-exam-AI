function createCountdownSessionRestoreController(options) {
  return {
    restore(session) {
      return restore(session, options)
    },
  }
}

function restore(session, options) {
  const confirm = resolveConfirmGuard(session, options)
  if (confirm.done) return confirm.result

  const base = resolveBase(session, options)
  if (base.done) return base.result
  return applyRestore(session, base, options)
}

function resolveConfirmGuard(session, options) {
  const page = options.page
  let snapshot = page._confirmTimerSnapshot
  if (!snapshot) {
    const stored = page._safeGetPomodoroStorage(
      'pomodoro_confirm_pause',
      'restore countdown confirm'
    )
    if (!stored.ok) {
      page._showPomodoroPersistenceError()
      return { done: true, result: false }
    }
    snapshot = stored.value
  }
  const preservesConfirm = snapshot &&
    snapshot.sessionId === session.id &&
    page.data.showEndConfirm
  return preservesConfirm
    ? { done: true, result: true }
    : { done: false }
}

function resolveBase(session, options) {
  const page = options.page
  const startTime = options.parseServerTime(session.start_time)
  const totalSec = session.work_duration * 60
  if (!Number.isFinite(startTime) || !Number.isFinite(totalSec) || totalSec <= 0) {
    page._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
    page._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
    page._resetToIdle()
    options.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
    return { done: true, result: true }
  }

  const storedPause = page._safeGetPomodoroStorage(
    'pomodoro_pause',
    'restore countdown pause'
  )
  if (!storedPause.ok) {
    page._showPomodoroPersistenceError()
    return { done: true, result: false }
  }

  const pausedAtMs = session.paused_at ? options.parseServerTime(session.paused_at) : null
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

  const restored = options.computeCountdownRestore({
    serverPausedSec: session.total_paused_sec || 0,
    savedPause: storedPause.value,
    pausedAtMs,
    now,
    startTime,
    totalSec,
    sessionId: session.id,
    totalPausedMs,
  })
  return { done: false, now, totalSec, startTime, restored }
}

function applyRestore(session, base, options) {
  const projection = resolveProjection(session, options)
  if (base.restored.remaining <= 0) {
    return completeExpired(session, base, projection, options)
  }
  return renderRunning(session, base, projection, options)
}

function resolveProjection(session, options) {
  const page = options.page
  const subject = options.resolveRestoredSubject({
    session,
    subjects: page.data.subjects,
    lookupSubjectIdByCode: code => page._lookupSubjectIdByCode(code),
  })
  const taskType = options.pomodoroTaskTypes.typeForSession(session)
  if (taskType) options.pomodoroTaskTypes.recordSession(session, taskType)
  return {
    subject,
    taskType: taskType || '',
    taskTypeLabel: taskType ? options.pomodoroTaskTypes.label(taskType) : '未分类',
  }
}

function buildSessionView(session, projection) {
  const { subject, taskType, taskTypeLabel } = projection
  return {
    selectedSubjectId: subject.subjectId,
    selectedSubject: subject.subjectId ? subject.selectedSubject : null,
    allocationMode: subject.aggregate ? 'equal_408_core_v1' : 'single',
    selectedTaskType: taskType,
    selectedTaskTypeLabel: taskTypeLabel,
    selectedPreset: session.preset || 'standard',
    workDuration: session.work_duration,
    breakDuration: session.break_duration,
  }
}

function buildCelebrationOptions(session, projection) {
  const { allocationMode, ...options } = buildSessionView(session, projection)
  return options
}

function completeExpired(session, base, projection, options) {
  const page = options.page
  page._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
  page._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
  page._completePomodoroWithRetry(session.id, base.restored.completedAt).then(synced => {
    const conflict = page._consumePomodoroTerminalConflict(session.id, 'complete')
    if (conflict) {
      page._handlePomodoroTerminalConflict(session.id, conflict)
      return
    }
    if (synced) page.loadTodayStats()
  }).catch(() => {})

  page._timerState.totalPausedMs = 0
  page._timerState.pauseStartTime = null
  page.setData({
    ...buildSessionView(session, projection),
    isPaused: false,
  })
  page._updateComputedFields()
  page.loadTodayStats()
  options.vibrateLong()
  page._showCompletionCelebration(session.id, buildCelebrationOptions(session, projection))
  return true
}

function renderRunning(session, base, projection, options) {
  const page = options.page
  const { restored } = base
  const display = options.formatCountdownDisplay(restored.remaining)
  page._timerState.sessionId = session.id
  page._timerState.sessionStartTime = base.startTime
  page._timerState.remainingSec = restored.remaining
  page._timerState.totalPausedMs = restored.totalPausedMs
  page._timerState.pauseStartTime = restored.isPaused ? base.now : null
  page._timerState.progress = restored.progress
  page.setData({
    ...buildSessionView(session, projection),
    phase: options.runningPhase,
    ringCanvasVisible: true,
    displayMin: display.min,
    displaySec: display.sec,
    isPaused: restored.isPaused,
  })

  if (restored.isPaused) {
    page._safeSetPomodoroStorage('pomodoro_pause', {
      totalPausedMs: restored.totalPausedMs,
      pauseStartTime: base.now,
      sessionId: session.id,
    })
    options.nextTick(() => {
      page._initCanvas(true)
      page.drawRing(base.totalSec, false)
    })
  } else {
    page._startTimer(base.totalSec)
  }
  page._updateComputedFields()
  return true
}

module.exports = { createCountdownSessionRestoreController }
