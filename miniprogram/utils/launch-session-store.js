const storage = require('./storage-core')
const { getChinaDate } = require('./china-time')
const { recordResumeEvent } = require('./launch-resume-diagnostics')

const PRACTICE_PREFIX = 'practice_resume_v1:'
const ACTIVE_PREFIX = 'study_active_v1:'
const TTL_MS = 24 * 60 * 60 * 1000
const GUEST_KEY = 'guest_trial_draft_v1'
const GUEST_RESULT_KEY = 'guestPracticeResult'
const GUEST_TYPES = new Set([
  'single_choice', 'multiple_choice', 'true_false', 'fill_blank',
  'multi_blank_choice', 'multi_blank_multiple_choice', 'subjective',
])

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
    now - snapshot.createdAt < TTL_MS &&
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
    if (snapshot) {
      recordResumeEvent('practice_invalid')
      clearPractice()
    }
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
    recordResumeEvent('practice_invalid')
    clearPractice()
    return false
  }
  try {
    storage.setStrict(snapshotKey, value)
    storage.setStrict(key(ACTIVE_PREFIX), { version: 1, kind: 'practice', owner: userId() })
    if (!previous || previous.requestId !== snapshot.requestId) recordResumeEvent('practice_saved')
    return true
  } catch (error) {
    recordResumeEvent('practice_save_failed')
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
  if (!freshness || now - freshness >= TTL_MS) {
    storage.remove(pendingKey)
    return null
  }
  return pending.version === 1 && pending.submission &&
    ['pending', 'blocked'].includes(pending.status) ? pending : null
}

function validGuest(snapshot, now) {
  if (!snapshot || !Array.isArray(snapshot.questions) ||
    !snapshot.questions.length || snapshot.questions.length > 30) return false
  const ids = new Set(snapshot.questions.map(question => String(question && question.id)))
  const answers = snapshot.answerMap
  return Boolean(snapshot.version === 2 &&
    typeof snapshot.batchToken === 'string' && snapshot.batchToken.trim() &&
    Number.isFinite(snapshot.createdAt) && snapshot.createdAt > 0 && snapshot.createdAt <= now &&
    Number.isFinite(snapshot.expiresAt) && snapshot.expiresAt > now &&
    snapshot.expiresAt <= snapshot.createdAt + TTL_MS &&
    snapshot.questions.every(question => question &&
      Number.isSafeInteger(Number(question.id)) && Number(question.id) > 0 &&
      GUEST_TYPES.has(question.question_type)) && ids.size === snapshot.questions.length &&
    answers && typeof answers === 'object' && !Array.isArray(answers) &&
    Object.keys(answers).every(id => ids.has(id) &&
      typeof answers[id] === 'string' && answers[id].length <= 4096) &&
    Number.isInteger(snapshot.currentIndex) && snapshot.currentIndex >= 0 &&
    snapshot.currentIndex < snapshot.questions.length &&
    Number.isFinite(snapshot.elapsedMs) && snapshot.elapsedMs >= 0 && snapshot.elapsedMs < TTL_MS)
}

function readGuest(now = Date.now()) {
  const snapshot = storage.get(GUEST_KEY)
  if (!snapshot) return { snapshot: null, notice: '' }
  if (!validGuest(snapshot, now)) {
    clearGuest()
    return { snapshot: null, notice: '上次体验已过期或损坏，请重新取题' }
  }
  return { snapshot, notice: '' }
}

function saveGuest(snapshot, now = Date.now()) {
  const value = { ...snapshot, version: 2 }
  if (!validGuest(value, now)) return false
  try {
    storage.setStrict(GUEST_KEY, value)
    return true
  } catch (_) {
    return false
  }
}

function clearGuest() {
  storage.remove(GUEST_KEY)
}

function saveGuestResult(payload, now = Date.now()) {
  const value = { ...payload, _guestResultVersion: 1, _createdAt: now }
  try {
    storage.setStrict(GUEST_RESULT_KEY, value)
    return true
  } catch (_) {
    return false
  }
}

function readGuestResult(now = Date.now()) {
  const value = storage.get(GUEST_RESULT_KEY)
  if (!value || typeof value !== 'object' || value._guestResultVersion !== 1 ||
    !Number.isFinite(value._createdAt) || value._createdAt <= 0 ||
    now - value._createdAt >= TTL_MS) return null
  const questions = Array.isArray(value.questions) ? value.questions : []
  const results = Array.isArray(value.results) ? value.results : []
  if ((!questions.length && !results.length) || questions.length > 30 || results.length > 30) return null
  return value
}

function clearGuestResult() {
  storage.remove(GUEST_RESULT_KEY)
}

module.exports = {
  userId, readPractice, savePractice, clearPractice, markReview, clearActive, readActive, readPending,
  readGuest, saveGuest, clearGuest, saveGuestResult, readGuestResult, clearGuestResult,
}
