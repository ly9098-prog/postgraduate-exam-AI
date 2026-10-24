const assert = require('node:assert/strict')
const { test } = require('node:test')
const { isPayloadRequestValid, extractCreatedAtFromCacheKey } = require('../subpackages/study/practice-result/utils/cache-validation')

test('isPayloadRequestValid: false for null', () => {
  assert.equal(isPayloadRequestValid(null, 'req-1'), false)
})

test('isPayloadRequestValid: true when no expected ID', () => {
  assert.equal(isPayloadRequestValid({ request_id: 'x' }, ''), true)
  assert.equal(isPayloadRequestValid({}, ''), true)
})

test('isPayloadRequestValid: matches request_id', () => {
  assert.equal(isPayloadRequestValid({ request_id: 'req-1' }, 'req-1'), true)
})

test('isPayloadRequestValid: matches requestId', () => {
  assert.equal(isPayloadRequestValid({ requestId: 'req-1' }, 'req-1'), true)
})

test('isPayloadRequestValid: unwraps data property', () => {
  assert.equal(isPayloadRequestValid({ data: { request_id: 'req-1' } }, 'req-1'), true)
})

test('isPayloadRequestValid: mismatch returns false', () => {
  assert.equal(isPayloadRequestValid({ request_id: 'req-2' }, 'req-1'), false)
})

test('isPayloadRequestValid: empty actual returns false', () => {
  assert.equal(isPayloadRequestValid({ request_id: '' }, 'req-1'), false)
})

test('isPayloadRequestValid: trims whitespace', () => {
  assert.equal(isPayloadRequestValid({ request_id: '  req-1  ' }, 'req-1'), true)
})

test('extractCreatedAtFromCacheKey: extracts timestamp', () => {
  assert.equal(extractCreatedAtFromCacheKey('pr_1234567890_abc'), 1234567890)
})

test('extractCreatedAtFromCacheKey: returns 0 for no match', () => {
  assert.equal(extractCreatedAtFromCacheKey('other_key'), 0)
})

test('extractCreatedAtFromCacheKey: returns 0 for null', () => {
  assert.equal(extractCreatedAtFromCacheKey(null), 0)
})

test('extractCreatedAtFromCacheKey: returns 0 for empty', () => {
  assert.equal(extractCreatedAtFromCacheKey(''), 0)
})
