function createUnknownStartController(options) {
  return {
    reconcile(explicitAttempt) {
      return reconcile(explicitAttempt, options)
    },
    postStart(payload, startSeq) {
      return postStart(payload, startSeq, options)
    },
  }
}

async function reconcile(explicitAttempt, options) {
  const page = options.page
  const stored = page._safeGetPomodoroStorage(options.storageKey, 'unknown start')
  if (!stored.ok) return 'storage_error'
  const attempt = resolveStoredAttempt(explicitAttempt, stored.value)
  const prepared = prepareAttempt(attempt, options)
  if (prepared.done) return prepared.result
  let session
  try {
    session = await options.post('/pomodoro/start', prepared.payload)
  } catch (error) {
    return resolveReconcileError(error, options)
  }
  return applyReconciledSession(session, attempt, options)
}

function resolveStoredAttempt(explicitAttempt, storedAttempt) {
  if (!storedAttempt ||
      (explicitAttempt && storedAttempt.clientStartId !== explicitAttempt.clientStartId)) {
    return explicitAttempt
  }
  return storedAttempt
}

function prepareAttempt(attempt, options) {
  if (!attempt || !attempt.clientStartId) {
    if (
      attempt &&
      !options.page._safeRemovePomodoroStorage(options.storageKey, 'invalid unknown start')
    ) return { done: true, result: 'storage_error' }
    return { done: true, result: 'none' }
  }
  const payload = options.buildPayload(attempt)
  if (!payload) {
    const removed = options.page._safeRemovePomodoroStorage(
      options.storageKey,
      'invalid unknown start payload'
    )
    return { done: true, result: removed ? 'none' : 'storage_error' }
  }
  return { done: false, payload }
}

function resolveReconcileError(error, options) {
  const statusCode = Number(error && error.statusCode) || 0
  if (statusCode === 0 || statusCode >= 500) return 'offline'
  const removed = options.page._safeRemovePomodoroStorage(
    options.storageKey,
    'settled failed start'
  )
  return removed ? 'none' : 'storage_error'
}

async function applyReconciledSession(session, attempt, options) {
  const page = options.page
  if (!options.matches(session, attempt)) {
    return removeResult('mismatched unknown start', options)
  }
  options.recordSession(session, attempt.taskType || page.data.selectedTaskType)
  if (attempt.cancelIfFound && isActive(session)) {
    return cancelReconciledSession(session, attempt, options)
  }
  if (isActive(session)) return restoreReconciledSession(session, options)
  return removeResult('resolved terminal start', options, 'settled')
}

async function cancelReconciledSession(session, attempt, options) {
  const page = options.page
  const cancelAt = cancellationAt(session, attempt.cancelAt, options)
  const pending = page._setPendingPomodoroSync('interrupt', session.id, cancelAt)
  if (!pending) {
    page._safeSetPomodoroStorage(options.storageKey, {
      ...attempt,
      cancelIfFound: true,
      cancelAt,
    }, 'retain cancelled unknown start')
    return 'storage_error'
  }
  page._safeRemovePomodoroStorage(
    options.storageKey,
    'interrupt queued for unknown start'
  )
  await page._retryPendingPomodoroSync()
  page._resetToIdle()
  return 'cancelled'
}

async function restoreReconciledSession(session, options) {
  const page = options.page
  if (!page._safeRemovePomodoroStorage(options.storageKey, 'resolved active start')) {
    return 'storage_error'
  }
  if (page._pageVisible && page._restoreSession(session) === false) return 'storage_error'
  return 'restored'
}

function removeResult(reason, options, successResult = 'none') {
  return options.page._safeRemovePomodoroStorage(options.storageKey, reason)
    ? successResult
    : 'storage_error'
}

function isActive(session) {
  return session.status === 'running' || session.status === 'paused'
}

function cancellationAt(session, cancelAt, options) {
  return options.startCancellationAt(
    session,
    cancelAt,
    options.now(),
    options.parseServerTime
  )
}

async function postStart(payload, startSeq, options) {
  const page = options.page
  const clientStartId = payload.client_start_id || options.createClientStartId()
  const requestPayload = { ...payload, client_start_id: clientStartId }
  const attempt = options.buildAttempt(
    page.data,
    {
      clientStartId,
      subjectId: requestPayload.subject_id,
      chapterId: requestPayload.chapter_id || null,
      preset: requestPayload.preset,
      workDuration: requestPayload.work_duration,
      breakDuration: requestPayload.break_duration,
      notificationEnabled: !!requestPayload.notification_enabled,
    },
    options.createClientStartId,
    options.now(),
  )
  if (!page._safeSetPomodoroStorage(
    options.storageKey,
    attempt,
    'before pomodoro start'
  )) {
    page._showPomodoroPersistenceError()
    page._resetToIdle()
    return handledResult()
  }
  let session
  try {
    session = await options.post('/pomodoro/start', requestPayload)
  } catch (error) {
    return resolvePostError(error, attempt, options)
  }
  return settlePostedSession(session, attempt, startSeq, options)
}

async function resolvePostError(error, attempt, options) {
  const page = options.page
  const statusCode = Number(error && error.statusCode) || 0
  const uncertain = statusCode === 0 || statusCode >= 500
  if (uncertain) {
    const resolution = await options.reconcile(attempt)
    if (resolution === 'cancelled' || resolution === 'restored') return handledResult()
    if (resolution === 'settled') {
      page._resetToIdle()
      return handledResult()
    }
    if (resolution === 'storage_error') {
      page._showPomodoroPersistenceError()
      page._resetToIdle()
      return handledResult()
    }
  } else if (!page._safeRemovePomodoroStorage(
    options.storageKey,
    'failed pomodoro start'
  )) {
    page._showPomodoroPersistenceError()
    page._resetToIdle()
    return handledResult()
  }
  throw error
}

function settlePostedSession(session, attempt, startSeq, options) {
  const page = options.page
  const latestStored = page._safeGetPomodoroStorage(
    options.storageKey,
    'completed pomodoro start'
  )
  const latestAttempt = latestStored.ok && latestStored.value
    ? latestStored.value
    : attempt
  if (!page._pageVisible || startSeq !== page._startRequestSeq) {
    queueLateInterrupt(session, latestAttempt, options)
    return handledResult()
  }
  if (
    !latestStored.ok ||
    !page._safeRemovePomodoroStorage(options.storageKey, 'accepted pomodoro start')
  ) {
    page._showPomodoroPersistenceError()
    page._resetToIdle()
    return handledResult()
  }
  return { handled: false, session }
}

function queueLateInterrupt(session, latestAttempt, options) {
  const page = options.page
  const cancelAt = cancellationAt(session, latestAttempt.cancelAt, options)
  const pending = page._setPendingPomodoroSync('interrupt', session.id, cancelAt)
  if (pending) {
    page._safeRemovePomodoroStorage(
      options.storageKey,
      'start cancelled after response'
    )
    page._retryPendingPomodoroSync()
    return
  }
  page._safeSetPomodoroStorage(options.storageKey, {
    ...latestAttempt,
    cancelIfFound: true,
    cancelAt,
  }, 'retain cancelled start after response')
}

function handledResult() {
  return { handled: true, session: null }
}

module.exports = { createUnknownStartController }
