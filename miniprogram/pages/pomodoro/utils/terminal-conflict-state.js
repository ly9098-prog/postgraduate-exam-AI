function isValidTerminalConflict(value) {
  return !!(value && value.sessionId && value.requestedAction)
}

function matchesTerminalConflict(conflict, sessionId, requestedAction) {
  return isValidTerminalConflict(conflict) &&
    String(conflict.sessionId) === String(sessionId) &&
    conflict.requestedAction === requestedAction
}

function createTerminalConflict(sessionId, requestedAction, serverStatus, savedAt) {
  return { sessionId, requestedAction, serverStatus, savedAt }
}

function isStorageConflict(value) {
  return !!(value && value.storageUnreadable)
}

module.exports = {
  isValidTerminalConflict,
  matchesTerminalConflict,
  createTerminalConflict,
  isStorageConflict,
}
