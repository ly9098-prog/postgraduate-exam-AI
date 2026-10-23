const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  buildQuestionRequestParams,
  validateKnowledgeScope,
  findQuestionBatchError,
} = require('../subpackages/study/practice/utils/question-batch')

const baseOptions = {
  subjectId: 12,
  selectedMode: 'random',
  selectedSubjectHasChildren: true,
  count: 8,
  traceId: 'trace-1',
  launchQuestionIds: '',
  launchAllowRepeat: false,
  launchPlanToken: '',
  launchKnowledgePointId: 34,
  launchIncludeDescendants: true,
  launchKnowledgePoint: '',
}

test('builds sequential, targeted, and normal question request params', () => {
  assert.deepEqual(buildQuestionRequestParams(baseOptions), {
    subject_id: 12,
    include_children: true,
    count: 8,
    mode: 'random',
    _traceId: 'trace-1',
    exclude_answered: true,
    no_repeat_days: 30,
    use_leitner: true,
    knowledge_point_id: 34,
    include_descendants: true,
  })

  assert.deepEqual(buildQuestionRequestParams({
    ...baseOptions,
    selectedMode: 'sequential',
    selectedSubjectHasChildren: true,
  }), {
    subject_id: 12,
    include_children: false,
    count: 8,
    mode: 'sequential',
    _traceId: 'trace-1',
    exclude_answered: false,
    use_leitner: false,
    knowledge_point_id: 34,
    include_descendants: true,
  })

  assert.deepEqual(buildQuestionRequestParams({
    ...baseOptions,
    launchQuestionIds: '9,8',
    launchAllowRepeat: false,
  }), {
    subject_id: 12,
    include_children: true,
    count: 8,
    mode: 'random',
    _traceId: 'trace-1',
    question_ids: '9,8',
    exclude_answered: false,
    use_leitner: false,
    knowledge_point_id: 34,
    include_descendants: true,
  })
})

test('validates include-descendants knowledge scope contract', () => {
  assert.equal(validateKnowledgeScope({
    root_knowledge_point_id: 34,
    include_descendants: true,
    knowledge_point_count: 2,
  }, 34), true)
  for (const scope of [
    null,
    { root_knowledge_point_id: 35, include_descendants: true, knowledge_point_count: 2 },
    { root_knowledge_point_id: 34, include_descendants: false, knowledge_point_count: 2 },
    { root_knowledge_point_id: 34, include_descendants: true, knowledge_point_count: 0 },
  ]) {
    assert.equal(validateKnowledgeScope(scope, 34), false)
  }
})

test('detects invalid IDs, unsupported types, and subject scope mismatches', () => {
  const answerableTypes = new Set(['single_choice'])
  assert.deepEqual(findQuestionBatchError([
    { id: 1, question_type: 'single_choice', subject_id: 12 },
    { id: 1, question_type: 'single_choice', subject_id: 12 },
    { id: 'bad', question_type: 'single_choice', subject_id: 12 },
  ], { answerableTypes, allowedScopeIds: new Set([12]) }), {
    kind: 'invalid_ids',
    invalidQuestionIds: ['bad'],
    duplicateQuestionIds: [1],
  })

  assert.deepEqual(findQuestionBatchError([
    { id: 1, question_type: 'essay', subject_id: 12 },
  ], { answerableTypes, allowedScopeIds: new Set([12]) }), {
    kind: 'unsupported_type',
    rejected: [{ id: 1, question_type: 'essay', subject_id: 12 }],
  })

  assert.deepEqual(findQuestionBatchError([
    { id: 1, question_type: 'single_choice', subject_id: 13, subject_code: 'other' },
  ], { answerableTypes, allowedScopeIds: new Set([12]) }), {
    kind: 'subject_scope',
    allowedScopeIds: [12],
    rejected: [{ id: 1, subject_id: 13, subject_code: 'other' }],
  })

  assert.equal(findQuestionBatchError([
    { id: 1, question_type: 'single_choice', subject_id: 13 },
  ], { answerableTypes, allowedScopeIds: new Set() }), null)
})
