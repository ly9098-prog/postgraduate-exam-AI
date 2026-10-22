const assert = require('node:assert/strict')
const {
  isValidTerminalConflict,
  matchesTerminalConflict,
  createTerminalConflict,
  isStorageConflict,
} = require('../pages/pomodoro/utils/terminal-conflict-state')

assert.equal(isValidTerminalConflict(null), false)
assert.equal(isValidTerminalConflict({}), false)
assert.equal(isValidTerminalConflict({ sessionId: 1 }), false)
assert.equal(isValidTerminalConflict({ requestedAction: 'complete' }), false)
assert.equal(isValidTerminalConflict({ sessionId: 1, requestedAction: 'complete' }), true)
assert.equal(isValidTerminalConflict({ sessionId: '0', requestedAction: '' }), false)

const conflict = { sessionId: 1, requestedAction: 'complete', serverStatus: 'interrupted', savedAt: 10 }
assert.equal(matchesTerminalConflict(conflict, 1, 'complete'), true)
assert.equal(matchesTerminalConflict(conflict, '1', 'complete'), true)
assert.equal(matchesTerminalConflict(conflict, 2, 'complete'), false)
assert.equal(matchesTerminalConflict(conflict, 1, 'interrupt'), false)
assert.equal(matchesTerminalConflict(conflict, '1', 'complete'), true)
assert.equal(matchesTerminalConflict(null, 1, 'complete'), false)

assert.deepEqual(createTerminalConflict(2, 'interrupt', 'completed', 20), {
  sessionId: 2,
  requestedAction: 'interrupt',
  serverStatus: 'completed',
  savedAt: 20,
})
assert.equal(isStorageConflict({ storageUnreadable: true }), true)
assert.equal(isStorageConflict({ storageUnreadable: false }), false)
assert.equal(isStorageConflict(conflict), false)

console.log('Pomodoro terminal conflict state passed: validation/match/storage')
