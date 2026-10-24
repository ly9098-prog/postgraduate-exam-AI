const assert = require('node:assert/strict')
const { test } = require('node:test')
const { resolveBatchErrorRecovery } = require('../subpackages/study/practice/utils/batch-error-recovery')

test('returns null for no error', () => {
  assert.equal(resolveBatchErrorRecovery(null, {}), null)
  assert.equal(resolveBatchErrorRecovery(undefined, {}), null)
})

test('returns null for error without kind', () => {
  assert.equal(resolveBatchErrorRecovery({}, {}), null)
})

test('maps invalid_ids error', () => {
  const result = resolveBatchErrorRecovery(
    { kind: 'invalid_ids', invalidQuestionIds: [1], duplicateQuestionIds: [2] },
    { subjectId: '12', traceId: 'trace-1' }
  )
  assert.equal(result.kind, 'invalid_ids')
  assert.ok(result.resetMessage.includes('练习批次题目异常'))
  assert.equal(result.toastTitle, '练习批次异常，请重试')
  assert.equal(result.logTag, '[PRACTICE_INVALID_BATCH_QUESTION_IDS]')
  assert.equal(result.logDetail.selectedSubjectId, 12)
  assert.equal(result.logDetail.traceId, 'trace-1')
  assert.deepEqual(result.logDetail.invalidQuestionIds, [1])
  assert.deepEqual(result.logDetail.duplicateQuestionIds, [2])
})

test('maps unsupported_type error', () => {
  const result = resolveBatchErrorRecovery(
    { kind: 'unsupported_type', rejected: [{ id: 3 }] },
    { subjectId: 5, traceId: 't' }
  )
  assert.equal(result.kind, 'unsupported_type')
  assert.ok(result.resetMessage.includes('暂不支持作答'))
  assert.equal(result.toastTitle, '题型暂不支持，请重试')
  assert.deepEqual(result.logDetail.rejected, [{ id: 3 }])
})

test('maps subject_scope error', () => {
  const result = resolveBatchErrorRecovery(
    { kind: 'subject_scope', allowedScopeIds: [1, 2], rejected: [{ id: 3 }] },
    { subjectId: 5, traceId: 't', includeChildren: true }
  )
  assert.equal(result.kind, 'subject_scope')
  assert.ok(result.resetMessage.includes('题目科目异常'))
  assert.equal(result.toastTitle, '题目科目异常，请重试')
  assert.equal(result.logDetail.includeChildren, true)
  assert.deepEqual(result.logDetail.allowedScopeIds, [1, 2])
})

test('returns null for unknown error kind', () => {
  assert.equal(resolveBatchErrorRecovery({ kind: 'unknown' }, {}), null)
})

test('handles missing context fields', () => {
  const result = resolveBatchErrorRecovery(
    { kind: 'invalid_ids' },
    {}
  )
  assert.equal(result.logDetail.selectedSubjectId, NaN)
  assert.equal(result.logDetail.traceId, '')
})
