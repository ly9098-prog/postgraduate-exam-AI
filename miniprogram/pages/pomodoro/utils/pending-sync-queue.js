const POMODORO_PENDING_SYNC_KEY = 'pomodoro_pending_sync'
const POMODORO_PENDING_SYNC_MAX_ACTIONS = 200
const POMODORO_PENDING_SYNC_NON_TERMINAL_LIMIT = 196

function writeQueue(ctx, queue) {
  if (!Array.isArray(queue)) return false
  if (!queue.length) return ctx.storage.remove(POMODORO_PENDING_SYNC_KEY, 'pending queue')
  return ctx.storage.write(POMODORO_PENDING_SYNC_KEY, queue, 'pending queue')
}

function readQueue(ctx) {
  const stored = ctx.storage.read(POMODORO_PENDING_SYNC_KEY, 'pending queue')
  if (!stored.ok) return null
  const raw = stored.value
  if (!raw) return []
  const list = Array.isArray(raw) ? raw : migrateLegacyEntry(ctx, raw)
  const validActions = ['pause', 'resume', 'complete', 'interrupt']
  const valid = list.filter(item => {
    const savedAt = Number(item && item.savedAt)
    return !!(item && item.sessionId && validActions.includes(item.action) &&
      Number.isFinite(savedAt) && savedAt > 0)
  })
  if (valid.length !== list.length || !Array.isArray(raw)) {
    if (!writeQueue(ctx, valid)) return null
  }
  return valid
}

function migrateLegacyEntry(ctx, raw) {
  // Preserve the old single-slot completeAfter marker during queue migration.
  const list = [raw]
  if (raw.completeAfter && raw.sessionId && raw.action !== 'complete') {
    list.push({
      action: 'complete',
      sessionId: raw.sessionId,
      savedAt: Number(raw.savedAt || ctx.now()),
      clientActionAt: Number(raw.savedAt || ctx.now()),
      nonce: `${raw.nonce || 'legacy'}-complete`,
    })
  }
  return list
}

function enqueueAction(ctx, action, sessionId, clientActionAt) {
  const queue = readQueue(ctx)
  if (queue === null) return null
  const last = queue[queue.length - 1]
  if (last && last.sessionId === sessionId && last.action === action) return last
  const terminal = action === 'complete' || action === 'interrupt'
  if (terminal) {
    const existing = queue.find(item => item.sessionId === sessionId && item.action === action)
    if (existing) return existing
  }
  const limit = terminal ? POMODORO_PENDING_SYNC_MAX_ACTIONS : POMODORO_PENDING_SYNC_NON_TERMINAL_LIMIT
  if (queue.length >= limit) {
    ctx.logger.warn('pomodoro pending queue safety valve reached', { action, sessionId, length: queue.length })
    return null
  }
  const pending = {
    action,
    sessionId,
    savedAt: ctx.now(),
    clientActionAt: Number.isFinite(clientActionAt) ? clientActionAt : ctx.now(),
    nonce: `${ctx.now()}-${ctx.random().toString(36).slice(2, 8)}`,
  }
  queue.push(pending)
  return writeQueue(ctx, queue) ? pending : null
}

function clearQueue(ctx, expected) {
  if (!expected) return writeQueue(ctx, [])
  const queue = readQueue(ctx)
  if (queue === null) return false
  return writeQueue(ctx, queue.filter(item => item.nonce !== expected.nonce))
}

function updateQueue(ctx, expected, patch) {
  const queue = readQueue(ctx)
  if (queue === null) return null
  const next = queue.map(item => item.nonce === expected.nonce ? { ...item, ...patch } : item)
  if (!writeQueue(ctx, next)) return null
  return next.find(item => item.nonce === expected.nonce) || null
}

// Each page owns its adapter; durable storage is the only queue source of truth.
function createPendingSyncQueue({ storage, now, random = Math.random, logger = console }) {
  const ctx = { storage, now, random, logger }
  return {
    write: queue => writeQueue(ctx, queue),
    read: () => readQueue(ctx),
    head: () => {
      const queue = readQueue(ctx)
      return queue === null ? { storageUnreadable: true } : (queue[0] || null)
    },
    has: (sessionId, actions) => {
      const queue = readQueue(ctx)
      if (queue === null) return true
      const allowed = Array.isArray(actions) ? actions : [actions]
      return queue.some(item => item.sessionId === sessionId && allowed.includes(item.action))
    },
    enqueue: (action, sessionId, clientActionAt) => enqueueAction(ctx, action, sessionId, clientActionAt),
    clear: expected => clearQueue(ctx, expected),
    update: (expected, patch) => updateQueue(ctx, expected, patch),
  }
}

module.exports = { createPendingSyncQueue }
