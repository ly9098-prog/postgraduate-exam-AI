const storage = require('./storage-core')
const { getChinaDate } = require('./china-time')

const PRACTICE_PREFIX = 'practice_resume_v1:'
const ACTIVE_PREFIX = 'study_active_v1:'
const TTL_MS = 24 * 60 * 60 * 1000

function userId() {
  const user = storage.get(storage.KEYS.USER) || {}
  const raw = [user.id, user.user_id, user.openid]
    .find(value => value != null && String(value).trim())
  return raw == null ? '' : String(raw).trim()
}

function key(prefix) {
  const owner = userId()
  return owner ? prefix + owner : ''
}

function clearActive(kind) {
  const activeKey = key(ACTIVE_PREFIX)
  const active = activeKey && storage.get(activeKey)
  if (active && (!kind || active.kind === kind)) storage.remove(activeKey)
}

function clearPractice() {
  const snapshotKey = key(PRACTICE_PREFIX)
  if (snapshotKey) storage.remove(snapshotKey)
  clearActive('practice')
}

function validPractice(snapshot, now) {
  return Boolean(snapshot && snapshot.version === 1 && snapshot.owner === userId() &&
    Number.isFinite(snapshot.createdAt) && snapshot.createdAt > 0 &&
    now >= snapshot.createdAt && now - snapshot.createdAt < TTL_MS &&
    typeof snapshot.batchToken === 'string' && snapshot.batchToken.trim() &&
    typeof snapshot.requestId === 'string' && snapshot.requestId.trim() &&
    Array.isArray(snapshot.questions) && snapshot.questions.length > 0 &&
    snapshot.questions.length <= 50 && snapshot.questions.every(question => question && question.id) &&
    new Set(snapshot.questions.map(question => String(question.id))).size === snapshot.questions.length &&
    Number.isInteger(snapshot.currentIndex) && snapshot.currentIndex >= 0 &&
    snapshot.currentIndex < snapshot.questions.length &&
    Number.isFinite(snapshot.elapsedMs) && snapshot.elapsedMs >= 0 && snapshot.elapsedMs < TTL_MS)
}

function readPractice(now = Date.now()) {
  const snapshotKey = key(PRACTICE_PREFIX)
  if (!snapshotKey) return null
  const snapshot = storage.get(snapshotKey)
  if (!validPractice(snapshot, now)) {
    if (snapshot) clearPractice()
    return null
  }
  return snapshot
}

function savePractice(snapshot, now = Date.now()) {
  const snapshotKey = key(PRACTICE_PREFIX)
  if (!snapshotKey) return false
  const previous = storage.get(snapshotKey)
  const createdAt = snapshot.createdAt || (
    previous && previous.requestId === snapshot.requestId ? previous.createdAt : now
  )
  const value = { ...snapshot, version: 1, owner: userId(), createdAt }
  if (!validPractice(value, now)) {
    clearPractice()
    return false
  }
  try {
    storage.setStrict(snapshotKey, value)
    storage.setStrict(key(ACTIVE_PREFIX), { version: 1, kind: 'practice', owner: userId() })
    return true
  } catch (error) {
    console.warn('保存练习恢复状态失败', error)
    return false
  }
}

function markReview(taskDate) {
  const activeKey = key(ACTIVE_PREFIX)
  if (!activeKey) return
  storage.set(activeKey, { version: 1, kind: 'review-today', taskDate, owner: userId() })
}

function readActive(now = Date.now()) {
  const activeKey = key(ACTIVE_PREFIX)
  if (!activeKey) return null
  const active = storage.get(activeKey)
  if (!active) return null
  const valid = active.version === 1 && active.owner === userId() && (
    active.kind === 'practice' ? Boolean(readPractice(now)) :
      active.kind === 'review-today' && active.taskDate === getChinaDate(0, now)
  )
  if (!valid) {
    storage.remove(activeKey)
    return null
  }
  return active
}

function readPending(now = Date.now()) {
  const pendingKey = key('practice_pending_submission_v1:')
  if (!pendingKey) return null
  const pending = storage.get(pendingKey)
  if (!pending) return null
  const freshness = Number(pending.updatedAt || pending.createdAt)
  if (!freshness || now - freshness >= TTL_MS || freshness > now) {
    storage.remove(pendingKey)
    return null
  }
  return pending.version === 1 && pending.submission &&
    ['pending', 'blocked'].includes(pending.status) ? pending : null
}

module.exports = {
  userId, readPractice, savePractice, clearPractice, markReview, clearActive, readActive, readPending,
}
