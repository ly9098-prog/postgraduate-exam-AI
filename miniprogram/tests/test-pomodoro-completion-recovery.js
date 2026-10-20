const assert = require('node:assert/strict')
const { test } = require('node:test')
const { buildCompletionRecovery } = require('../pages/pomodoro/utils/completion-recovery')

const taskTypes = {
  TYPE_MAP: { new_questions: true, review: true },
  label: type => ({ new_questions: '新题', review: '复习' })[type],
}

function current() {
  return {
    selectedSubjectId: 11,
    selectedSubject: { id: 11, code: 'old-code', name: '原科目' },
    selectedPreset: 'standard',
    workDuration: 25,
    breakDuration: 5,
    selectedTaskType: 'new_questions',
    selectedTaskTypeLabel: '新题',
  }
}

test('legacy completion preserves selection and restores celebration flags', () => {
  const { breakSec, view } = buildCompletionRecovery({ sessionId: 1, motto: 'done' }, current(), taskTypes)
  assert.equal(breakSec, null)
  assert.deepEqual(view, {
    ...current(),
    selectedSubject: { ...current().selectedSubject, _isAggregate: false },
    phase: 'idle',
    isPaused: false,
    showEndConfirm: false,
    showCelebration: true,
    celebrationMotto: 'done',
    celebrationType: 'excellent',
    allocationMode: 'single',
  })
})

test('completion snapshot replaces subject, aggregate mode, preset and task type', () => {
  const completion = {
    sessionId: 1,
    selectedSubjectId: 22,
    selectedSubjectCode: 'exam408',
    selectedSubjectName: '408',
    allocationMode: 'equal_408_core_v1',
    selectedPreset: 'long',
    selectedTaskType: 'review',
    workDuration: '50',
    breakDuration: '10',
    breakSec: '600',
    type: 'good',
  }
  const { breakSec, view } = buildCompletionRecovery(completion, current(), taskTypes)
  assert.equal(breakSec, 600)
  assert.equal(view.workDuration, 50)
  assert.equal(view.breakDuration, 10)
  assert.equal(view.selectedPreset, 'long')
  assert.equal(view.celebrationType, 'good')
  assert.deepEqual(view.selectedSubject, { id: 22, code: 'exam408', name: '408', _isAggregate: true })
  assert.equal(view.allocationMode, 'equal_408_core_v1')
  assert.equal(view.selectedTaskType, 'review')
  assert.equal(view.selectedTaskTypeLabel, '复习')
})

test('explicit empty or invalid task type clears classification; inherited field does not', () => {
  for (const selectedTaskType of ['', null, undefined, 'unknown']) {
    const { view } = buildCompletionRecovery({ selectedTaskType }, current(), taskTypes)
    assert.equal(view.selectedTaskType, '')
    assert.equal(view.selectedTaskTypeLabel, '未分类')
  }
  const inherited = Object.create({ selectedTaskType: 'review' })
  const { view } = buildCompletionRecovery(inherited, current(), taskTypes)
  assert.equal(view.selectedTaskType, 'new_questions')
  assert.equal(view.selectedTaskTypeLabel, '新题')
})

test('preserves numeric coercion and break clamping for stored snapshots', () => {
  for (const [input, expected] of [
    [undefined, null], [null, 0], ['', 0], ['10', 10], [-4, 0],
    [Infinity, null], ['bad', null],
  ]) {
    assert.equal(buildCompletionRecovery({ breakSec: input }, current(), taskTypes).breakSec, expected)
  }
  for (const [input, expected] of [
    [undefined, 25], [null, 0], ['', 0], ['30', 30], [-4, -4],
    [Infinity, 25], ['bad', 25],
  ]) {
    assert.equal(buildCompletionRecovery({ workDuration: input }, current(), taskTypes).view.workDuration, expected)
  }
})

test('subject fallback preserves missing-ID identity and legacy code/name fallback', () => {
  const existing = current()
  const { view } = buildCompletionRecovery({ selectedSubjectId: 22 }, existing, taskTypes)
  assert.deepEqual(view.selectedSubject, { id: 22, code: 'old-code', name: '原科目', _isAggregate: false })
  existing.selectedSubjectId = null
  const missing = buildCompletionRecovery({}, existing, taskTypes)
  assert.equal(missing.view.selectedSubject, existing.selectedSubject)
})

test('does not mutate frozen completion or current view state', () => {
  const existing = current()
  Object.freeze(existing.selectedSubject)
  Object.freeze(existing)
  const completion = Object.freeze({ selectedSubjectId: 22, selectedTaskType: 'review' })
  buildCompletionRecovery(completion, existing, taskTypes)
  assert.equal(existing.selectedSubjectId, 11)
  assert.equal(existing.selectedSubject._isAggregate, undefined)
  assert.equal(completion.selectedSubjectCode, undefined)
})
