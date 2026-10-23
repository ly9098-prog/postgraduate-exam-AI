function createTerminalConflictController(options) {
  const state = { conflict: null }
  return {
    record: (sessionId, requestedAction, serverStatus) => record(
      sessionId,
      requestedAction,
      serverStatus,
      options,
      state
    ),
    read: () => read(options, state),
    consume: (sessionId, requestedAction) => consume(sessionId, requestedAction, options, state),
    consumeAny: () => read(options, state),
    ack: conflict => ack(conflict, options, state),
    handle: (sessionId, conflict) => handle(sessionId, conflict, options, state),
  }
}

function record(sessionId, requestedAction, serverStatus, options, state) {
  const conflict = options.createConflict(
    sessionId,
    requestedAction,
    serverStatus,
    options.now()
  )
  if (!options.setStorage(options.storageKey, conflict, 'terminal conflict')) {
    return false
  }
  state.conflict = conflict
  return true
}

function read(options, state) {
  if (state.conflict) return state.conflict
  const stored = options.getStorage(options.storageKey, 'terminal conflict')
  if (!stored.ok) return { storageUnreadable: true }
  const conflict = stored.value
  if (options.isValidConflict(conflict)) {
    state.conflict = conflict
    return conflict
  }
  return null
}

function consume(sessionId, requestedAction, options, state) {
  const conflict = read(options, state)
  if (options.isStorageConflict(conflict)) return conflict
  if (!options.matchesConflict(conflict, sessionId, requestedAction)) return null
  return conflict
}

function ack(conflict, options, state) {
  if (!conflict || options.isStorageConflict(conflict)) return false
  if (!options.removeStorage(options.storageKey, 'terminal conflict ack')) {
    return false
  }
  if (
    state.conflict &&
    state.conflict.sessionId === conflict.sessionId &&
    state.conflict.requestedAction === conflict.requestedAction
  ) {
    state.conflict = null
  }
  return true
}

function handle(sessionId, conflict, options, state) {
  return options.handleTerminalConflict({
    isStorageError: options.isStorageConflict,
    persistenceError: options.persistenceError,
    dropSessionActions: options.dropSessionActions,
    getStorage: options.getStorage,
    removeStorage: options.removeStorage,
    ackConflict: value => ack(value, options, state),
    get completionBreakSec() {
      return options.getCompletionBreakSec()
    },
    set completionBreakSec(value) {
      options.setCompletionBreakSec(value)
    },
    clearTimer: options.clearTimer,
    setData: options.setData,
    resetIdle: options.resetIdle,
    showToast: options.showToast,
    loadStats: options.loadStats,
  }, sessionId, conflict)
}

module.exports = { createTerminalConflictController }
