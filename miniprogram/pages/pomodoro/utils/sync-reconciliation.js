function isTerminalAction(action) {
  return action === 'complete' || action === 'interrupt'
}

function canReconcilePendingSync(error) {
  const statusCode = Number(error && error.statusCode) || 0
  return statusCode === 404 || statusCode === 409
}

function decidePendingSyncReconciliation(pending, error, active) {
  const statusCode = Number(error && error.statusCode) || 0
  if (statusCode !== 404 && statusCode !== 409) {
    return { kind: 'not-reconcilable' }
  }

  if (active && active.id === pending.sessionId) {
    if (pending.action === 'pause' && active.status === 'paused') {
      return { kind: 'acknowledge' }
    }
    if (pending.action === 'resume' && active.status === 'running') {
      return { kind: 'acknowledge' }
    }

    if (error && error.code === 'POMODORO_CLOCK_SKEW') {
      const retries = Number(pending.clockSkewRetries || 0)
      return retries < 2
        ? { kind: 'retry-with-calibration', retries }
        : { kind: 'keep-pending' }
    }

    if (
      error &&
      (error.code === 'POMODORO_STALE_ACTION' || error.code === 'POMODORO_NOT_READY')
    ) {
      return {
        kind: 'restore-active',
        clearTerminalCompletion: isTerminalAction(pending.action),
      }
    }
  }

  if (!active || active.id !== pending.sessionId) {
    return { kind: 'drop-session' }
  }

  return { kind: 'keep-pending' }
}

module.exports = { canReconcilePendingSync, isTerminalAction, decidePendingSyncReconciliation }
