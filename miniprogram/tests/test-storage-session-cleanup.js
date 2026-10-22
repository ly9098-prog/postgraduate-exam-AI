// Run: node miniprogram/tests/test-storage-session-cleanup.js
const assert = require('node:assert/strict')

const values = new Map()
global.wx = {
  getStorageSync: key => values.has(key) ? values.get(key) : '',
  setStorageSync: (key, value) => values.set(key, value),
  removeStorageSync: key => values.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(values.keys()) }),
}

const storage = require('../utils/storage')

const preserved = [
  'other_screen_cache',
  'exam_attempt_pending_v3:12',
  'practice_pending_submission_v1:12',
  'review_today_draft_v1:9:2026-10-23',
  'ai_cache:9',
]
const cleared = [
  'token',
  'refresh_token',
  'user',
  'exam_attempt_pending_v1:12',
  'exam_attempt_pending_v2:12',
  'review_today_draft_v1:8:2026-10-23',
  'lastPracticeResult',
]

preserved.forEach(key => values.set(key, { key }))
cleared.forEach(key => values.set(key, { key }))
values.set('privacy_acceptance', { accepted: true })
values.set('debug_snapshot:test', { debug: true })

storage.clearSession({ preservePrivacyAcceptance: true })

cleared.forEach(key => assert.equal(values.has(key), false, `${key} should be cleared`))
assert.equal(values.has('privacy_acceptance'), true, 'privacy acceptance must be preserved')
assert.equal(values.has('debug_snapshot:test'), false, 'debug snapshots should be cleared by default')

storage.clearSession({ preservePrivacyAcceptance: false, includeDebugSnapshots: true })

preserved
  .filter(key => key.indexOf('exam_attempt_pending_') === 0 || key.indexOf('review_today_draft') === 0)
  .forEach(key => assert.equal(values.has(key), false, `${key} should be cleared on full logout`))

console.log('Storage session cleanup regression passed')
