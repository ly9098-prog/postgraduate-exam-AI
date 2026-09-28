/**
 * Tests for pomodoro/utils/subject-cache.js — 24h subject-tree cache.
 *
 * Run: cd miniprogram && node tests/test-pomodoro-subject-cache.js
 */

var passed = 0
var failed = 0

function assertEqual(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:', JSON.stringify(actual))
}

function assertTrue(value, msg) {
  assertEqual(Boolean(value), true, msg)
}

var store = {}
global.wx = {
  getStorageSync: function (key) { return store[key] },
  setStorageSync: function (key, value) { store[key] = value },
  removeStorageSync: function (key) { delete store[key] },
}

var subjectCache = require('../pages/pomodoro/utils/subject-cache')
var TTL = subjectCache.SUBJECT_CACHE_TTL_MS

// ── TTL constant ──
assertEqual(TTL, 24 * 60 * 60 * 1000, 'TTL must be exactly 24h')

// ── Empty cache ──
subjectCache.clearSubjectCache()
assertEqual(subjectCache.readSubjectCache(), null, 'empty cache returns null')

// ── Write then read ──
var subjects = [{ id: 1, code: 'data_structure', name: '数据结构' }]
assertTrue(subjectCache.writeSubjectCache(subjects), 'write returns true')
var read = subjectCache.readSubjectCache()
assertTrue(Array.isArray(read) && read.length === 1, 'read returns cached array')
assertEqual(read[0].code, 'data_structure', 'cached payload preserved')

// ── Reject empty list (no negative caching) ──
assertEqual(subjectCache.writeSubjectCache([]), false, 'empty list must not be cached')
assertEqual(subjectCache.writeSubjectCache(null), false, 'null must not be cached')

// ── Expiry: exactly 24h is still valid, just over is stale ──
var now = Date.now()
subjectCache.writeSubjectCache(subjects)
var savedAt = store[subjectCache.SUBJECT_CACHE_KEY].savedAt
assertTrue(subjectCache.isCacheValid({ savedAt: now - TTL, subjects: subjects }, now), 'exactly 24h is valid')
assertEqual(
  subjectCache.isCacheValid({ savedAt: now - TTL - 1, subjects: subjects }, now),
  false,
  'past 24h is stale'
)

// ── Corrupt entries are treated as cache miss ──
assertEqual(subjectCache.isCacheValid(null, now), false, 'null entry invalid')
assertEqual(subjectCache.isCacheValid({ savedAt: now, subjects: 'oops' }, now), false, 'non-array subjects invalid')
assertEqual(subjectCache.isCacheValid({ savedAt: 'bad', subjects: subjects }, now), false, 'bad savedAt invalid')
assertEqual(
  subjectCache.isCacheValid({ savedAt: now - TTL - 1, subjects: subjects }, now),
  false,
  'stale entry invalid'
)

// ── Storage read failure degrades to miss ──
global.wx.getStorageSync = function () { throw new Error('storage broken') }
assertEqual(subjectCache.readSubjectCache(), null, 'storage read failure returns null')

// ── Storage write failure degrades to false ──
global.wx.setStorageSync = function () { throw new Error('storage full') }
assertEqual(subjectCache.writeSubjectCache(subjects), false, 'storage write failure returns false')

// ── Clear is best-effort ──
global.wx.removeStorageSync = function () { throw new Error('storage broken') }
subjectCache.clearSubjectCache()
passed++

console.log('\n============================')
console.log('Tests:', passed + failed + ', passed:', passed + ', failed:', failed)
console.log('============================\n')

process.exit(failed > 0 ? 1 : 0)
