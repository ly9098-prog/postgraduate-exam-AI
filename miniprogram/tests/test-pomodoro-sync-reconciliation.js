const assert = require('node:assert/strict')
const {
  canReconcilePendingSync,
  isTerminalAction,
  decidePendingSyncReconciliation,
} = require('../pages/pomodoro/utils/sync-reconciliation')

for (const [error, expected] of [
  [{ statusCode: 404 }, true],
  [{ statusCode: 409 }, true],
  [{ statusCode: '409' }, true],
  [{ statusCode: 500 }, false],
  [{}, false],
  [null, false],
]) {
  assert.equal(canReconcilePendingSync(error), expected)
}

for (const [action, expected] of [
  ['complete', true],
  ['interrupt', true],
  ['pause', false],
  ['resume', false],
  [null, false],
]) {
  assert.equal(isTerminalAction(action), expected)
}

const pending = { sessionId: 10, action: 'pause', clockSkewRetries: 0 }

assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 500 }, null),
  { kind: 'not-reconcilable' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(pending, null, null),
  { kind: 'not-reconcilable' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 404 }, { id: 10, status: 'paused' }),
  { kind: 'acknowledge' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(
    { ...pending, action: 'resume' },
    { statusCode: 409 },
    { id: 10, status: 'running' },
  ),
  { kind: 'acknowledge' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 404 }, { id: 10, status: 'running' }),
  { kind: 'keep-pending' },
)

assert.deepEqual(
  decidePendingSyncReconciliation(
    pending,
    { statusCode: 409, code: 'POMODORO_CLOCK_SKEW' },
    { id: 10, status: 'running' },
  ),
  { kind: 'retry-with-calibration', retries: 0 },
)
assert.deepEqual(
  decidePendingSyncReconciliation(
    { ...pending, clockSkewRetries: 1 },
    { statusCode: 409, code: 'POMODORO_CLOCK_SKEW' },
    { id: 10, status: 'running' },
  ),
  { kind: 'retry-with-calibration', retries: 1 },
)
assert.deepEqual(
  decidePendingSyncReconciliation(
    { ...pending, clockSkewRetries: 2 },
    { statusCode: 409, code: 'POMODORO_CLOCK_SKEW' },
    { id: 10, status: 'running' },
  ),
  { kind: 'keep-pending' },
)

for (const code of ['POMODORO_STALE_ACTION', 'POMODORO_NOT_READY']) {
  assert.deepEqual(
    decidePendingSyncReconciliation(
      pending,
      { statusCode: 409, code },
      { id: 10, status: 'running' },
    ),
    { kind: 'restore-active', clearTerminalCompletion: false },
  )
  assert.deepEqual(
    decidePendingSyncReconciliation(
      { ...pending, action: 'complete' },
      { statusCode: 409, code },
      { id: 10, status: 'running' },
    ),
    { kind: 'restore-active', clearTerminalCompletion: true },
  )
}

assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 404 }, { id: 11, status: 'paused' }),
  { kind: 'drop-session' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 404 }, null),
  { kind: 'drop-session' },
)
assert.deepEqual(
  decidePendingSyncReconciliation(pending, { statusCode: 404 }, { id: 10, status: 'running' }),
  { kind: 'keep-pending' },
)

console.log('Pomodoro sync reconciliation passed: loss/clock/stale/drop decisions')
