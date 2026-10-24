const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildPracticeResultUrl } = require('../subpackages/study/practice/utils/result-url-builder')

test('builds full result URL with all params', () => {
  const url = buildPracticeResultUrl({
    correct: 3,
    wrong: 1,
    skipped: 1,
    partial: 0,
    total: 5,
    subjectId: 12,
    subjectName: '数据结构',
    duration: 120,
    cacheKey: 'pr_123_abc',
    requestId: 'req_456',
    resultCacheStored: true,
    source: 'home',
    returnTo: 'dashboard',
  })
  assert.ok(url.startsWith('/subpackages/study/practice-result/index'))
  assert.ok(url.includes('?correct=3'))
  assert.ok(url.includes('&wrong=1'))
  assert.ok(url.includes('&skipped=1'))
  assert.ok(url.includes('&partial=0'))
  assert.ok(url.includes('&total=5'))
  assert.ok(url.includes('&subject_id=12'))
  assert.ok(url.includes('&subject_name=' + encodeURIComponent('数据结构')))
  assert.ok(url.includes('&duration=120'))
  assert.ok(url.includes('&_ck=pr_123_abc'))
  assert.ok(url.includes('&_rid=' + encodeURIComponent('req_456')))
  assert.ok(url.includes('&_recover=0'))
  assert.ok(url.includes('&source=' + encodeURIComponent('home')))
  assert.ok(url.includes('&return_to=' + encodeURIComponent('dashboard')))
})

test('sets _recover=1 when cache not stored', () => {
  const url = buildPracticeResultUrl({
    correct: 0, wrong: 0, skipped: 0, partial: 0, total: 0,
    subjectId: 1, subjectName: '', duration: 0,
    cacheKey: 'ck', requestId: '', resultCacheStored: false,
    source: '', returnTo: '',
  })
  assert.ok(url.includes('&_recover=1'))
})

test('handles missing optional fields with defaults', () => {
  const url = buildPracticeResultUrl({
    subjectId: 1,
    cacheKey: 'ck',
  })
  assert.ok(url.includes('?correct=0'))
  assert.ok(url.includes('&wrong=0'))
  assert.ok(url.includes('&skipped=0'))
  assert.ok(url.includes('&partial=0'))
  assert.ok(url.includes('&total=0'))
  assert.ok(url.includes('&duration=0'))
  assert.ok(url.includes('&_recover=1'))
  assert.ok(url.includes('&subject_name='))
  assert.ok(url.includes('&_rid='))
  assert.ok(url.includes('&source='))
  assert.ok(url.includes('&return_to='))
})

test('encodes special characters in subject name', () => {
  const url = buildPracticeResultUrl({
    subjectId: 1,
    subjectName: 'A&B=C',
    cacheKey: 'ck',
    resultCacheStored: true,
  })
  assert.ok(url.includes('&subject_name=' + encodeURIComponent('A&B=C')))
})
