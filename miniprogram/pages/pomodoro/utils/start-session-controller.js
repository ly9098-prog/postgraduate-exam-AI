function createStartSessionController(options) {
  return {
    start() {
      return start(options)
    },
    startFree(existingStartSeq) {
      return startFree(existingStartSeq, options)
    },
  }
}

async function start(options) {
  const page = options.page
  if (
    page._startInFlight ||
    page.data.phase === options.phases.CEREMONY ||
    page.data.phase === options.phases.RUNNING
  ) return
  page._startInFlight = true
  const startSeq = (page._startRequestSeq || 0) + 1
  page._startRequestSeq = startSeq
  try {
    const action = await prepareStart(startSeq, options)
    if (!action) return
    if (action === 'free') {
      await page._startFreeSession(startSeq)
      return
    }
    await launchCountdown(startSeq, options)
  } catch (error) {
    await handleStartFailure(error, startSeq, 'countdown', options)
  } finally {
    page._startInFlight = false
  }
}

async function prepareStart(startSeq, options) {
  const page = options.page
  const unresolved = await page._reconcileUnknownStartAttempt()
  if (isStale(startSeq, options)) return null
  if (unresolved === 'offline') {
    options.showToast({ title: '上次启动结果待确认，请联网后重试', icon: 'none' })
    return null
  }
  if (unresolved === 'storage_error') {
    page._showPomodoroPersistenceError()
    return null
  }
  if (unresolved === 'restored' || unresolved === 'cancelled') return null

  if (!(await flushPendingStart(startSeq, options))) return null
  if (!page.data.selectedSubjectId || !page.data.selectedSubject) {
    options.showToast({ title: '请选择学习科目', icon: 'none' })
    return null
  }
  if (page.data.subjectsError) {
    options.showToast({ title: '科目加载异常，请重试', icon: 'none' })
    return null
  }
  return page.data.selectedPreset === 'free' ? 'free' : 'countdown'
}

async function flushPendingStart(startSeq, options) {
  const page = options.page
  const pendingQueue = page._getPendingPomodoroSyncQueue()
  if (pendingQueue === null) {
    page._showPomodoroPersistenceError()
    return false
  }
  if (!pendingQueue.length) return true
  const synced = await page._retryPendingPomodoroSync()
  if (isStale(startSeq, options)) return false
  if (synced) return true
  options.showToast({ title: '上次专注尚未同步，请联网后重试', icon: 'none' })
  return false
}

async function launchCountdown(startSeq, options) {
  const page = options.page
  page.setData({ phase: options.phases.CEREMONY })
  const delay = page.data.selectedPreset === 'debug'
    ? options.debugCeremonyDelayMs
    : options.ceremonyDelayMs
  await options.wait(delay)
  if (isStale(startSeq, options) || page.data.phase !== options.phases.CEREMONY) return
  const result = await page._postPomodoroStartWithReconciliation({
    subject_id: page.data.selectedSubjectId,
    allocation_mode: page.data.allocationMode,
    chapter_id: page.data.fromChapterId || null,
    preset: page.data.selectedPreset,
    work_duration: page.data.selectedPreset === 'debug' ? 1 : page.data.workDuration,
    break_duration: page.data.selectedPreset === 'debug' ? 1 : page.data.breakDuration,
  }, startSeq)
  acceptStartedSession(result, 'countdown', options)
}

async function startFree(existingStartSeq, options) {
  const page = options.page
  const startSeq = existingStartSeq || ((page._startRequestSeq || 0) + 1)
  if (!existingStartSeq) page._startRequestSeq = startSeq
  try {
    if (!(await flushPendingStart(startSeq, options))) return
    const result = await page._postPomodoroStartWithReconciliation({
      subject_id: page.data.selectedSubjectId,
      allocation_mode: page.data.allocationMode,
      chapter_id: page.data.fromChapterId || null,
      preset: 'free',
      work_duration: 0,
      break_duration: 0,
    }, startSeq)
    acceptStartedSession(result, 'free', options)
  } catch (error) {
    await handleStartFailure(error, startSeq, 'free', options)
  }
}

function acceptStartedSession(result, mode, options) {
  if (result.handled || !result.session) return
  const page = options.page
  options.pomodoroTaskTypes.recordSession(result.session, page.data.selectedTaskType)
  if (mode === 'free') {
    page._beginFreeTimer(result.session)
  } else {
    page._beginCountdown(result.session)
  }
}

async function handleStartFailure(error, startSeq, mode, options) {
  if (isStale(startSeq, options)) return
  const page = options.page
  const detail = (error && (error.detail || error.message || '')) || ''
  const activeConflict = (error && error.statusCode === 409) ||
    /active|running|进行中/.test(detail)
  if (activeConflict) {
    options.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
    await restoreActiveConflict(startSeq, mode, options)
    return
  }
  options.showToast({
    title: mode === 'free' ? '启动失败，请重试' : '启动失败',
    icon: 'none',
  })
  if (mode === 'countdown') page.setData({ phase: options.phases.IDLE })
}

async function restoreActiveConflict(startSeq, mode, options) {
  const page = options.page
  const active = await page._fetchActiveSession()
  if (isStale(startSeq, options)) return
  if (page._isPomodoroStorageError(active)) {
    page._showPomodoroPersistenceError()
    if (mode === 'countdown') page.setData({ phase: options.phases.IDLE })
    return
  }
  if (active) {
    const restored = page._restoreSession(active)
    if (mode === 'countdown' && restored === false) {
      page.setData({ phase: options.phases.IDLE })
    }
    return
  }
  if (mode === 'countdown') page.setData({ phase: options.phases.IDLE })
}

function isStale(startSeq, options) {
  const page = options.page
  return !page._pageVisible || startSeq !== page._startRequestSeq
}

module.exports = { createStartSessionController }
