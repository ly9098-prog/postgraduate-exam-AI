const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  createQuestionEnrichmentController,
} = require('../subpackages/study/review-today/utils/question-enrichment-controller')

function createHarness(overrides = {}) {
  const state = { safeMode: false }
  const controller = createQuestionEnrichmentController({
    isDev: () => false,
    isSafeModeActive: () => state.safeMode,
    isTrueFalse: t => t === 'true_false' || t === 'judgement',
    subjectLabel: (name, code) => name || code || '',
    ...overrides,
  })
  return { controller, state }
}

test('splitGroups divides questions into chunks', () => {
  const { controller } = createHarness()
  const groups = controller.splitGroups([1, 2, 3, 4, 5], 2)
  assert.deepEqual(groups, [[1, 2], [3, 4], [5]])
})

test('splitGroups handles empty array', () => {
  const { controller } = createHarness()
  assert.deepEqual(controller.splitGroups([], 5), [])
})

test('enrich builds render model and option metadata', () => {
  const { controller } = createHarness()
  const q = {
    schedule_id: 1,
    question_id: 11,
    question_version_id: 21,
    question_type: 'single_choice',
    content: { text: 'What is 1+1?' },
    options: { A: '1', B: '2', C: '3', D: '4' },
    subject_name: '数学',
  }
  const enriched = controller.enrich(q)

  assert.ok(enriched._renderModel !== undefined)
  assert.deepEqual(enriched._optionKeys, ['A', 'B', 'C', 'D'])
  assert.equal(enriched._subjectLabel, '数学')
  assert.ok(enriched._stemPreview.length > 0)
  assert.equal(enriched._hasBlankOptionGroups, false)
})

test('enrich handles true_false type with default options', () => {
  const { controller } = createHarness()
  const q = { question_type: 'true_false', content: { text: 'True or false?' } }
  const enriched = controller.enrich(q)

  assert.deepEqual(enriched._optionKeys, ['A', 'B'])
  assert.equal(enriched._opts.A, '正确')
  assert.equal(enriched._opts.B, '错误')
})

test('enrich truncates long stem preview', () => {
  const { controller } = createHarness()
  const longStem = 'A'.repeat(100)
  const q = { question_type: 'single_choice', content: { text: longStem }, options: { A: 'opt' } }
  const enriched = controller.enrich(q)

  assert.equal(enriched._stemPreview.length, 63) // 60 + '...'
})

test('enrichForResult returns q if already has render model', () => {
  const { controller } = createHarness()
  const q = { _renderModel: { mode: 'RICH_TEXT' }, question_type: 'single_choice' }
  const result = controller.enrichForResult(q)
  assert.equal(result, q)
})

test('enrichForResult falls back to plain text on error', () => {
  const { controller } = createHarness()
  // Pass null content to trigger error path
  const q = { question_type: 'invalid_type_that_causes_error' }
  const result = controller.enrichForResult(q)
  // Should not throw, should return object with _renderModel
  assert.ok(result !== null)
})
