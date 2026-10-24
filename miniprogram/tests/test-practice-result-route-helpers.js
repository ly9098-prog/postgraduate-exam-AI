const assert = require('node:assert/strict')
const { test } = require('node:test')
const { normalizePracticeReturnRoute, safeDecodeJson } = require('../subpackages/study/practice-result/utils/route-helpers')

test('normalizePracticeReturnRoute: accepts valid knowledge detail route', () => {
  assert.equal(normalizePracticeReturnRoute('/subpackages/knowledge/knowledge-detail/index?id=1'), '/subpackages/knowledge/knowledge-detail/index?id=1')
})

test('normalizePracticeReturnRoute: accepts valid study knowledge subject route', () => {
  assert.equal(normalizePracticeReturnRoute('/subpackages/study/knowledge-subject/index'), '/subpackages/study/knowledge-subject/index')
})

test('normalizePracticeReturnRoute: rejects invalid route', () => {
  assert.equal(normalizePracticeReturnRoute('/pages/home/home'), '')
})

test('normalizePracticeReturnRoute: rejects empty', () => {
  assert.equal(normalizePracticeReturnRoute(''), '')
})

test('normalizePracticeReturnRoute: rejects null', () => {
  assert.equal(normalizePracticeReturnRoute(null), '')
})

test('normalizePracticeReturnRoute: truncates long input', () => {
  const long = '/subpackages/knowledge/knowledge-detail/index?' + 'x'.repeat(600)
  const result = normalizePracticeReturnRoute(long)
  assert.ok(result.length <= 512)
})

test('safeDecodeJson: parses valid JSON', () => {
  assert.deepEqual(safeDecodeJson('{"a":1}'), { a: 1 })
})

test('safeDecodeJson: parses URI-encoded JSON', () => {
  assert.deepEqual(safeDecodeJson(encodeURIComponent('{"b":2}')), { b: 2 })
})

test('safeDecodeJson: returns null for non-object', () => {
  assert.equal(safeDecodeJson('"hello"'), null)
})

test('safeDecodeJson: returns null for invalid JSON', () => {
  assert.equal(safeDecodeJson('not json'), null)
})

test('safeDecodeJson: returns null for null', () => {
  assert.equal(safeDecodeJson(null), null)
})

test('safeDecodeJson: returns null for empty', () => {
  assert.equal(safeDecodeJson(''), null)
})
