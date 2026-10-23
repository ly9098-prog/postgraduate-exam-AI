function createPendingSyncController(options) {
  const state = { drainPromise: null }
  return {
    drain: () => drain(options, state),
    reconcileFailure: (pending, error) => reconcileFailure(pending, error, options),
    complete: (sessionId, clientActionAt) => enqueueTerminal(
      'complete',
      sessionId,
      clientActionAt,
      options,
      state
    ),
    interrupt: (sessionId, clientActionAt) => enqueueTerminal(
      'interrupt',
      sessionId,
      clientActionAt,
      options,
      state
    ),
  }
}

function drain(options, state) {
  if (state.drainPromise) return state.drainPromise
  state.drainPromise = runDrain(options).finally(() => {
    state.drainPromise = null
  })
  return state.drainPromise
}

async function runDrain(options) {
  while (true) {
    const queue = options.getQueue()
    if (queue === null) {
      options.persistenceError()
      return false
    }
    if (!queue.length) {
      options.clearRetryTimer(true)
      return true
    }

    const pending = queue[0]
    try {
      const response = await options.post(
        `/pomodoro/${pending.sessionId}/${pending.action}`,
        buildActionBody(pending, options)
      )
      const terminalResult = handleTerminalResponse(pending, response, options)
      if (terminalResult === false) return false
      if (terminalResult === true) continue
      if (!acknowledgeCommittedAction(pending, options)) return false
    } catch (error) {
      const reconciled = await reconcileFailure(pending, error, options)
      if (!reconciled) {
        options.scheduleRetry(error)
        return false
      }
      options.clearRetryTimer(true)
    }
  }
}

function buildActionBody(pending, options) {
  const actionAtMs = Number(pending.clientActionAt)
  if (!Number.isFinite(actionAtMs) || actionAtMs <= 0) return {}
  const clientActionAt = options.formatClientActionAt(actionAtMs)
  return clientActionAt ? { client_action_at: clientActionAt } : {}
}

function handleTerminalResponse(pending, response, options) {
  if (pending.action !== 'complete' && pending.action !== 'interrupt') return null
  const expectedStatus = pending.action === 'complete' ? 'completed' : 'interrupted'
  if (!response || !response.status) return null
  if (response.status === expectedStatus) return null
  if (!options.recordTerminalConflict(pending.sessionId, pending.action, response.status)) {
    options.persistenceError()
    return false
  }
  if (!options.dropSessionActions(pending.sessionId)) {
    options.persistenceError()
    return false
  }
  options.clearRetryTimer(true)
  return true
}

function acknowledgeCommittedAction(pending, options) {
  options.clearRetryTimer(true)
  if (!options.clearPending(pending)) {
    options.logError(
      'pomodoro pending action committed but local acknowledgement could not be persisted',
      pending
    )
    options.persistenceError()
    return false
  }
  if (pending.action === 'pause' || pending.action === 'resume') {
    options.maybeClearAdjustment(pending.sessionId)
  }
  return true
}

async function reconcileFailure(pending, error, options) {
  if (!options.canReconcile(error)) return false
  let active
  try {
    active = await options.getActive()
  } catch (_) {
    return false
  }
  const decision = options.decideReconciliation(pending, error, active)
  if (decision.kind === 'not-reconcilable' || decision.kind === 'keep-pending') {
    return false
  }
  if (decision.kind === 'acknowledge') {
    if (!options.clearPending(pending)) return false
    options.maybeClearAdjustment(pending.sessionId)
    return true
  }
  if (decision.kind === 'retry-with-calibration') {
    options.updatePending(pending, {
      clientActionAt: options.now(),
      clockSkewRetries: decision.retries + 1,
    })
    return true
  }
  if (decision.kind === 'restore-active') {
    if (decision.clearTerminalCompletion &&
        !clearStaleTerminalCompletion(pending, options)) return false
    if (options.isVisible() && options.restoreSession(active) === false) return false
    if (!options.clearPending(pending)) return false
    options.maybeClearAdjustment(pending.sessionId)
    return true
  }
  return options.dropSessionActions(pending.sessionId)
}

function clearStaleTerminalCompletion(pending, options) {
  const stored = options.getStorage('pomodoro_completion', 'stale terminal reconcile')
  if (!stored.ok) return false
  const completion = stored.value
  if (
    completion &&
    completion.sessionId === pending.sessionId &&
    !options.removeStorage('pomodoro_completion', 'stale terminal reconcile')
  ) return false
  options.removeStorage('pomodoro_break', 'best-effort cleanup')
  options.setCompletionBreakSec(null)
  options.setData({ showCelebration: false, showEndConfirm: false })
  return true
}

async function enqueueTerminal(action, sessionId, clientActionAt, options, state) {
  if (!sessionId) return false
  const pending = options.enqueue(action, sessionId, clientActionAt)
  if (!pending) {
    options.persistenceError()
    return false
  }
  const synced = await drain(options, state)
  const conflict = options.readConflict()
  if (options.isStorageConflict(conflict)) return false
  return !!synced &&
    !options.hasPending(sessionId, action) &&
    !matchesConflict(conflict, sessionId, action)
}

function matchesConflict(conflict, sessionId, action) {
  return !!(
    conflict &&
    String(conflict.sessionId) === String(sessionId) &&
    conflict.requestedAction === action
  )
}

module.exports = { createPendingSyncController }
