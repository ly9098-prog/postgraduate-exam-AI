const assert = require('node:assert/strict')
const {
  buildCompletionCelebration,
  pickMotto,
} = require('../pages/pomodoro/utils/completion-celebration')

const MOTTOES = ['m1', 'm2', 'm3']

function makeContext(overrides) {
  return Object.assign({
    data: {
      workDuration: 25,
      breakDuration: 5,
      selectedPreset: 'standard',
      selectedSubject: { id: 10, code: 'CS', name: '计算机' },
      selectedSubjectId: 10,
      selectedTaskType: 'lecture',
    },
    mottoes: MOTTOES,
    nextCelebrationType: () => 'confetti',
    MathRandom: () => 0.5,
  }, overrides || {})
}

// ── pickMotto ──

assert.equal(pickMotto(MOTTOES, () => 0), 'm1')
assert.equal(pickMotto(MOTTOES, () => 0.99), 'm3')
assert.equal(pickMotto(['only'], undefined), 'only')

// ── buildCompletionCelebration: basic ──

const basic = buildCompletionCelebration(42, {}, makeContext())
assert.equal(basic.completionFlag.sessionId, 42)
assert.equal(basic.completionFlag.breakSec, 300)
assert.equal(basic.completionFlag.selectedPreset, 'standard')
assert.equal(basic.completionFlag.selectedSubjectCode, 'CS')
assert.equal(basic.completionFlag.selectedSubjectName, '计算机')
assert.equal(basic.completionFlag.allocationMode, 'single')
assert.equal(basic.completionFlag.selectedTaskType, 'lecture')
assert.equal(basic.completionFlag.motto, 'm2')
assert.equal(basic.completionFlag.type, 'confetti')

assert.equal(basic.viewData.phase, 'idle')
assert.equal(basic.viewData.showCelebration, true)
assert.equal(basic.viewData.ringCanvasVisible, false)
assert.equal(basic.viewData.celebrationMotto, 'm2')
assert.equal(basic.viewData.celebrationType, 'confetti')
assert.equal(basic.viewData.selectedSubjectId, 10)
assert.equal(basic.viewData.selectedTaskType, 'lecture')

// ── options override data ──

const overridden = buildCompletionCelebration(7, {
  workDuration: 50,
  breakDuration: 10,
  selectedPreset: 'long',
  selectedSubject: { id: 20, code: 'MATH', name: '数学', _isAggregate: true },
  selectedSubjectId: 20,
  selectedTaskType: 'review',
  selectedTaskTypeLabel: '复习',
  motto: 'custom motto',
  type: 'fireworks',
}, makeContext())
assert.equal(overridden.completionFlag.breakSec, 600)
assert.equal(overridden.completionFlag.selectedSubjectCode, 'MATH')
assert.equal(overridden.completionFlag.allocationMode, 'equal_408_core_v1')
assert.equal(overridden.completionFlag.motto, 'custom motto')
assert.equal(overridden.completionFlag.type, 'fireworks')
assert.equal(overridden.viewData.celebrationMotto, 'custom motto')
assert.equal(overridden.viewData.workDuration, 50)
assert.equal(overridden.viewData.selectedTaskTypeLabel, '复习')

// ── debug preset breakSec ──

const debug = buildCompletionCelebration(1, { selectedPreset: 'debug' }, makeContext())
assert.equal(debug.completionFlag.breakSec, 5)

// ── invalid task type fallback ──

const invalidTask = buildCompletionCelebration(1, { selectedTaskType: 'invalid' }, makeContext())
assert.equal(invalidTask.completionFlag.selectedTaskType, '')
assert.equal(invalidTask.viewData.selectedTaskTypeLabel, '未分类')

// ── aggregate subject from data ──

const aggData = buildCompletionCelebration(1, {}, makeContext({
  data: {
    workDuration: 25,
    breakDuration: 5,
    selectedPreset: 'standard',
    selectedSubject: { id: 5, code: 'AGG', name: '聚合', _isAggregate: true },
    selectedSubjectId: 5,
    selectedTaskType: 'lecture',
  },
}))
assert.equal(aggData.completionFlag.allocationMode, 'equal_408_core_v1')

console.log('Pomodoro completion celebration passed: build/pickMotto/overrides/debug/invalid/aggregate')
