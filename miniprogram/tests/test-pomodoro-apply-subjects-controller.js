const { test } = require('node:test')
const assert = require('node:assert')

const { buildApplySubjectsPlan } = require('../pages/pomodoro/utils/apply-subjects-controller')

test('apply subjects: returns base patch with choices and loading state', () => {
  const flat = [
    { id: 1, code: 'ds', name: '数据结构', _isCore: true },
  ]
  const plan = buildApplySubjectsPlan(flat, {})
  assert.ok(plan.patches.length >= 1)
  assert.strictEqual(plan.patches[0].subjectsLoading, false)
  assert.strictEqual(plan.patches[0].subjectsError, '')
  assert.ok(Array.isArray(plan.patches[0].subjects))
  assert.ok(Array.isArray(plan.leaves))
})

test('apply subjects: no route selection when fromSubjectId and fromSubjectCode absent', () => {
  const flat = [{ id: 1, code: 'ds', name: 'DS', _isCore: true }]
  const plan = buildApplySubjectsPlan(flat, {})
  assert.strictEqual(plan.patches.length, 1)
})

test('apply subjects: route selection added when fromSubjectId matches', () => {
  const flat = [
    { id: 10, code: 'ds', name: '数据结构', _isCore: true, _isAggregate: false },
  ]
  const plan = buildApplySubjectsPlan(flat, { fromSubjectId: 10 })
  assert.ok(plan.patches.length >= 2)
})

test('apply subjects: legacy selection added when selectedSubject matches a leaf', () => {
  const flat = [
    { id: 10, code: 'ds', name: '数据结构', _isCore: true, _isAggregate: false },
  ]
  const plan = buildApplySubjectsPlan(flat, { selectedSubject: { code: 'ds' } })
  assert.ok(plan.patches.length >= 2)
})

test('apply subjects: empty flat still produces base patch', () => {
  const plan = buildApplySubjectsPlan([], {})
  assert.strictEqual(plan.patches.length, 1)
  assert.strictEqual(plan.patches[0].subjectsLoading, false)
})
